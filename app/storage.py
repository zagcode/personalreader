"""Documentos em disco: data/docs/<id>/{meta.json, content.json, source.md, original.*}."""

import json
import re
import shutil
import time
import uuid
from pathlib import Path

from .config import DOCS_DIR

_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def new_id() -> str:
    return uuid.uuid4().hex


def doc_dir(doc_id: str) -> Path | None:
    if not _ID_RE.match(doc_id):
        return None
    path = DOCS_DIR / doc_id
    return path if path.is_dir() else None


def create(doc_id: str, name: str, size: int) -> dict:
    (DOCS_DIR / doc_id).mkdir(parents=True, exist_ok=True)
    meta = {
        "id": doc_id,
        "name": name,
        "size": size,
        "status": "processing",
        "error": None,
        "created": time.time(),
        "segments": 0,
    }
    save_meta(meta)
    return meta


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def save_meta(meta: dict) -> None:
    _write_json(DOCS_DIR / meta["id"] / "meta.json", meta)


def load_meta(doc_id: str) -> dict | None:
    d = doc_dir(doc_id)
    if not d or not (d / "meta.json").exists():
        return None
    return json.loads((d / "meta.json").read_text(encoding="utf-8"))


def save_content(doc_id: str, markdown: str, content: dict) -> None:
    d = DOCS_DIR / doc_id
    (d / "source.md").write_text(markdown, encoding="utf-8")
    _write_json(d / "content.json", content)


def load_content(doc_id: str) -> dict | None:
    d = doc_dir(doc_id)
    if not d or not (d / "content.json").exists():
        return None
    return json.loads((d / "content.json").read_text(encoding="utf-8"))


def list_all() -> list[dict]:
    metas = []
    for d in DOCS_DIR.iterdir():
        meta = load_meta(d.name) if d.is_dir() else None
        if meta:
            metas.append(meta)
    return sorted(metas, key=lambda m: m["created"], reverse=True)


def delete(doc_id: str) -> bool:
    d = doc_dir(doc_id)
    if not d:
        return False
    shutil.rmtree(d)
    return True
