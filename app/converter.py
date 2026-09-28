"""Conversão de arquivos para Markdown com docling (padrão único para qualquer formato)."""

import logging
import threading
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

_converter = None
_lock = threading.Lock()

PLAIN_TEXT = {".txt"}


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


def to_markdown(path: Path) -> str:
    if path.suffix.lower() in PLAIN_TEXT:
        # Texto puro não tem estrutura para o docling extrair; cada linha em branco separa parágrafos.
        return path.read_text(encoding="utf-8", errors="replace")
    result = _get_converter().convert(path)
    return result.document.export_to_markdown()


def allowed_extensions() -> set[str]:
    exts = set(config.ALLOWED_EXTENSIONS)
    if not config.DOCLING_OCR:
        # Sem OCR uma imagem vira documento vazio; melhor recusar no upload.
        exts -= {".png", ".jpg", ".jpeg", ".tiff", ".tif"}
    return exts
