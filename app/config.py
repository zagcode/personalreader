"""Configuração via variáveis de ambiente (ver .env.example)."""

import os
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DOCS_DIR = DATA_DIR / "docs"
AUDIO_DIR = DATA_DIR / "audio"
VOICES_DIR = Path(os.getenv("VOICES_DIR", DATA_DIR / "voices"))
STATIC_DIR = BASE_DIR / "static"

# "voxcpm" em produção; "mock" gera um áudio sintético para desenvolver sem baixar o modelo.
TTS_ENGINE = os.getenv("TTS_ENGINE", "voxcpm")
VOXCPM_MODEL = os.getenv("VOXCPM_MODEL", "openbmb/VoxCPM2")
VOXCPM_DEVICE = os.getenv("VOXCPM_DEVICE", "cpu")
VOXCPM_TIMESTEPS = int(os.getenv("VOXCPM_TIMESTEPS", "10"))
VOXCPM_CFG = float(os.getenv("VOXCPM_CFG", "2.0"))
TORCH_THREADS = int(os.getenv("TORCH_THREADS", "0"))  # 0 = padrão do torch

DOCLING_OCR = _bool("DOCLING_OCR", False)
DOCLING_TABLES = _bool("DOCLING_TABLES", True)

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

for d in (DOCS_DIR, AUDIO_DIR, VOICES_DIR):
    d.mkdir(parents=True, exist_ok=True)
