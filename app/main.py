import asyncio
import base64
import hmac
import logging
import secrets
from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, converter, storage
from .segmenter import segment_markdown
from .tts.engines import create_engine
from .tts.queue import AUDIO_MIME, PRIORITY_AHEAD, PRIORITY_NOW, TTSQueue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("personalreader")

tts = TTSQueue(create_engine(config.TTS_ENGINE))
# Um documento por vez: o docling já ocupa todos os núcleos num PDF grande.
convert_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="docling")


@asynccontextmanager
async def lifespan(_: FastAPI):
    for meta in storage.list_all():
        if meta["status"] == "processing":
            meta.update(status="error", error="Conversão interrompida (o servidor reiniciou). Envie o arquivo de novo.")
            storage.save_meta(meta)
    tts.start()
    yield
    convert_pool.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="Personal Reader", lifespan=lifespan)


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if config.APP_PASSWORD:
        header = request.headers.get("authorization", "")
        ok = False
        if header.lower().startswith("basic "):
            try:
                _, _, password = base64.b64decode(header[6:]).decode("utf-8").partition(":")
                ok = hmac.compare_digest(password, config.APP_PASSWORD)
            except ValueError:
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="personalreader"'})
    return await call_next(request)


class _Deleted(Exception):
    """O documento foi apagado enquanto convertia."""


def _convert(doc_id: str, path: Path) -> None:
    meta = storage.load_meta(doc_id)
    if meta is None:
        return

    def progress(done: int, total: int) -> None:
        if not storage.doc_dir(doc_id):
            raise _Deleted  # para de converter um documento que não existe mais
        meta["progress"] = {"done": done, "total": total}
        storage.save_meta(meta)

    try:
        markdown = converter.to_markdown(path, progress)
        content = segment_markdown(markdown)
        if not content["segments"]:
            raise ValueError("Nenhum texto legível encontrado no arquivo.")
        storage.save_content(doc_id, markdown, content)
        meta.update(status="ready", segments=len(content["segments"]))
    except _Deleted:
        log.info("conversão de %s interrompida: documento apagado", path.name)
        return
    except Exception as exc:  # noqa: BLE001 - mostrado ao usuário
        log.exception("falha ao converter %s", path.name)
        meta.update(status="error", error=str(exc) or type(exc).__name__)
    if storage.doc_dir(doc_id):  # pode ter sido apagado durante a conversão
        storage.save_meta(meta)


# --------------------------------------------------------------------- API


@app.get("/api/health")
def health():
    return {**tts.status(), "audio": AUDIO_MIME, "max_prefetch": config.MAX_PREFETCH}


@app.get("/api/config")
def client_config():
    return {
        "extensions": sorted(converter.allowed_extensions()),
        "max_upload_mb": config.MAX_UPLOAD_MB,
        "max_prefetch": config.MAX_PREFETCH,
        "voices": [
            {"id": v.id, "label": v.label, "group": v.group, "languages": list(v.languages)}
            for v in tts.engine.voices()
        ],
    }


@app.get("/api/documents")
def documents():
    return storage.list_all()


@app.post("/api/documents", status_code=201)
async def upload(file: UploadFile):
    name = Path(file.filename or "documento").name
    ext = Path(name).suffix.lower()
    if ext not in converter.allowed_extensions():
        raise HTTPException(415, f"Formato {ext or '(sem extensão)'} não suportado.")

    doc_id = storage.new_id()
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    target = config.DOCS_DIR / doc_id / f"original{ext}"
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with target.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                out.close()
                storage.delete(doc_id)
                raise HTTPException(413, f"Arquivo maior que {config.MAX_UPLOAD_MB} MB.")
            out.write(chunk)

    meta = storage.create(doc_id, name, size)
    convert_pool.submit(_convert, doc_id, target)
    return meta


@app.get("/api/documents/{doc_id}")
def document(doc_id: str):
    meta = storage.load_meta(doc_id)
    if meta is None:
        raise HTTPException(404, "Documento não encontrado.")
    if meta["status"] == "ready":
        meta["content"] = storage.load_content(doc_id)
    return meta


@app.delete("/api/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str):
    tts.cancel_doc(doc_id)
    if not storage.delete(doc_id):
        raise HTTPException(404, "Documento não encontrado.")


def _segment_text(doc_id: str, index: int) -> str:
    content = storage.load_content(doc_id)
    if content is None:
        raise HTTPException(404, "Documento não encontrado ou ainda em processamento.")
    segments = content["segments"]
    if not 0 <= index < len(segments):
        raise HTTPException(404, "Frase fora do documento.")
    return segments[index]["text"]


@app.get("/api/documents/{doc_id}/segments/{index}/audio")
async def segment_audio(doc_id: str, index: int, voice: str = ""):
    if tts.load_error:
        raise HTTPException(503, f"Motor de voz indisponível: {tts.load_error}")
    text = _segment_text(doc_id, index)
    _, future = tts.submit(text, tts.engine.get_voice(voice), doc_id, PRIORITY_NOW)
    try:
        path = await asyncio.wrap_future(future)
    except (CancelledError, asyncio.CancelledError):
        return JSONResponse({"detail": "Síntese cancelada."}, status_code=409)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Falha ao gerar o áudio: {exc}") from exc
    return FileResponse(path, media_type=AUDIO_MIME, headers={"Cache-Control": "private, max-age=86400"})


class PrefetchRequest(BaseModel):
    voice: str = ""
    start: int
    end: int  # exclusivo


@app.post("/api/documents/{doc_id}/prefetch")
def prefetch(doc_id: str, req: PrefetchRequest):
    """Enfileira as próximas frases e descarta pendências fora da janela pedida.

    O cliente só pede até o próximo ponto de confirmação, então uma aba
    esquecida aberta não fica consumindo CPU com o livro inteiro.
    """
    content = storage.load_content(doc_id)
    if content is None:
        raise HTTPException(404, "Documento não encontrado ou ainda em processamento.")
    segments = content["segments"]
    start = max(0, req.start)
    end = min(len(segments), req.end, start + config.MAX_PREFETCH)
    voice = tts.engine.get_voice(req.voice)

    ready = []
    keys = set()
    for i in range(start, end):
        key, future = tts.submit(segments[i]["text"], voice, doc_id, PRIORITY_AHEAD + (i - start))
        keys.add(key)
        ready.append(future.done() and not future.cancelled() and future.exception() is None)
    tts.cancel_doc(doc_id, keep=keys)
    return {"start": start, "end": end, "ready": ready}


# O token evita que o navegador use um index.html velho após deploy.
_BUILD = secrets.token_hex(4)


@app.get("/")
def index():
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return Response(html.replace("__BUILD__", _BUILD), media_type="text/html")


app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
