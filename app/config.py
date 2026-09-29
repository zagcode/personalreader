"""Configuração via variáveis de ambiente (ver .env.example)."""

import os
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DOCS_DIR = DATA_DIR / "docs"
AUDIO_DIR = DATA_DIR / "audio"
STATIC_DIR = BASE_DIR / "static"

# Nome registrado em app/tts/engines/__init__.py ("kokoro", "mock") ou "pacote.modulo:Classe".
# As opções de cada motor ficam no módulo dele (ex.: KOKORO_* em app/tts/engines/kokoro.py).
TTS_ENGINE = os.getenv("TTS_ENGINE", "kokoro")

DOCLING_OCR = _bool("DOCLING_OCR", False)
DOCLING_TABLES = _bool("DOCLING_TABLES", True)
# PDFs são convertidos neste tanto de páginas por vez, para a página mostrar o progresso.
DOCLING_PAGES_PER_STEP = max(1, int(os.getenv("DOCLING_PAGES_PER_STEP", "4")))

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
MAX_SEGMENT_CHARS = int(os.getenv("MAX_SEGMENT_CHARS", "280"))
# Quantas frases à frente o servidor aceita gerar a partir da posição pedida.
MAX_PREFETCH = int(os.getenv("MAX_PREFETCH", "6"))
AUDIO_FORMAT = os.getenv("AUDIO_FORMAT", "mp3")  # mp3 | wav

# Se definido, exige HTTP Basic (usuário qualquer, esta senha).
APP_PASSWORD = os.getenv("APP_PASSWORD", "")

ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".md", ".txt",
    ".epub", ".odt", ".png", ".jpg", ".jpeg", ".tiff", ".tif",
}

for d in (DOCS_DIR, AUDIO_DIR):
    d.mkdir(parents=True, exist_ok=True)
