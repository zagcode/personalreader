"""Conversão de arquivos para Markdown com docling (padrão único para qualquer formato)."""

import logging
import re
import threading
from collections.abc import Callable
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

_converter = None
_lock = threading.Lock()

PLAIN_TEXT = {".txt"}

# Progresso: (páginas prontas, total de páginas).
Progress = Callable[[int, int], None]

_ENDS_SENTENCE = re.compile(r"[.!?:;…。！？\"”’)\]|]\s*$")


def _get_converter():
    global _converter
    with _lock:
        if _converter is None:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption

            # Em CPU o OCR é a etapa mais cara; PDFs com texto embutido não precisam dele.
            pdf_opts = PdfPipelineOptions()
            pdf_opts.do_ocr = config.DOCLING_OCR
            pdf_opts.do_table_structure = config.DOCLING_TABLES
            _converter = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_opts)}
            )
        return _converter


def to_markdown(path: Path, progress: Progress | None = None) -> str:
    suffix = path.suffix.lower()
    if suffix in PLAIN_TEXT:
        # Texto puro não tem estrutura para o docling extrair; cada linha em branco separa parágrafos.
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        return _pdf_to_markdown(path, progress)
    # DOCX, EPUB, HTML... não têm páginas no docling e convertem em segundos.
    return _get_converter().convert(path).document.export_to_markdown()


def _pdf_to_markdown(path: Path, progress: Progress | None) -> str:
    """Converte o PDF em blocos de páginas para poder informar o progresso.

    O docling não tem callback de progresso, mas aceita page_range. No teste
    local, blocos de 4 páginas não custaram mais tempo que a conversão inteira.
    """
    import pypdfium2

    pdf = pypdfium2.PdfDocument(str(path))
    total = len(pdf)
    pdf.close()
    # Avisa o total antes de carregar o docling: o primeiro import leva vários segundos.
    if progress:
        progress(0, total)
    converter = _get_converter()
    step = config.DOCLING_PAGES_PER_STEP
    markdown = ""
    for start in range(1, total + 1, step):
        end = min(start + step - 1, total)
        part = converter.convert(path, page_range=(start, end)).document.export_to_markdown()
        markdown = join_parts(markdown, part)
        if progress:
            progress(end, total)
    return markdown


def join_parts(head: str, tail: str) -> str:
    """Junta o Markdown de dois blocos de páginas.

    Um parágrafo que atravessa a divisa chega partido em dois; quando o bloco
    anterior termina sem pontuação e o seguinte começa em minúscula, as duas
    metades viram um parágrafo só.
    """
    head, tail = head.rstrip(), tail.lstrip()
    if not head:
        return tail
    if not tail:
        return head
    last_line = head.rsplit("\n", 1)[-1]
    plain = last_line and not last_line.lstrip().startswith(("#", "|", "-", "*", ">", "<!--"))
    if plain and not _ENDS_SENTENCE.search(last_line) and tail[0].islower():
        return f"{head} {tail}"
    return f"{head}\n\n{tail}"


def allowed_extensions() -> set[str]:
    exts = set(config.ALLOWED_EXTENSIONS)
    if not config.DOCLING_OCR:
        # Sem OCR uma imagem vira documento vazio; melhor recusar no upload.
        exts -= {".png", ".jpg", ".jpeg", ".tiff", ".tif"}
    return exts
