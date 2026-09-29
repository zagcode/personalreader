"""Kokoro-82M via kokoro-onnx (ONNX Runtime, sem torch). Rápido em CPU.

Cada voz fala um idioma: a primeira letra do nome é o idioma e a segunda o
gênero (pf_dora = português, feminina). O texto é convertido em fonemas no
idioma da voz, então a voz precisa ser do idioma do documento.

Fonemas: espeak-ng (embutido no kokoro-onnx) para a maioria dos idiomas. Para
chinês e japonês o espeak não serve (sem tons no chinês; no japonês lê
"Chinese letter" no lugar de cada kanji), então esses usam o misaki. Sem o
misaki do idioma instalado, as vozes dele ficam fora da lista.

Opções (variáveis de ambiente, lidas só quando este motor é o escolhido):
  KOKORO_MODEL          arquivo .onnx (padrão kokoro-v1.0.onnx, fp32; o int8 foi
                        10x mais lento que o fp32 no teste local)
  KOKORO_VOICES         arquivo de vozes (padrão voices-v1.0.bin)
  KOKORO_DIR            pasta dos arquivos (padrão <DATA_DIR>/models/kokoro)
  KOKORO_DOWNLOAD_URL   release de onde baixar os arquivos que faltarem
"""

import logging
import os
import time
import urllib.request
from pathlib import Path

import numpy as np

from ... import config
from ..base import TTSEngine, Voice

log = logging.getLogger(__name__)

MODEL_FILE = os.getenv("KOKORO_MODEL", "kokoro-v1.0.onnx")
VOICES_FILE = os.getenv("KOKORO_VOICES", "voices-v1.0.bin")
MODEL_DIR = Path(os.getenv("KOKORO_DIR", config.DATA_DIR / "models" / "kokoro"))
DOWNLOAD_URL = os.getenv(
    "KOKORO_DOWNLOAD_URL", "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
)

# prefixo -> (código espeak, idioma ISO 639-1, nome no player). A ordem aqui é a ordem no player.
LANGUAGES = {
    "a": ("en-us", "en", "Inglês (EUA)"),
    "b": ("en-gb", "en", "Inglês (Reino Unido)"),
    "p": ("pt-br", "pt", "Português (Brasil)"),
    "e": ("es", "es", "Espanhol"),
    "f": ("fr-fr", "fr", "Francês"),
    "i": ("it", "it", "Italiano"),
    "j": ("ja", "ja", "Japonês"),
    "z": ("cmn", "zh", "Chinês (mandarim)"),
    "h": ("hi", "hi", "Hindi"),
}
GENDERS = {"f": "feminina", "m": "masculina"}
# Idiomas que precisam do misaki para gerar fonemas: prefixo -> (submódulo, classe).
MISAKI = {"z": ("zh", "ZHG2P"), "j": ("ja", "JAG2P")}
# Voz padrão: a de melhor avaliação no VOICES.md do Kokoro.
DEFAULT_VOICE = "af_heart"
DOWNLOAD_ATTEMPTS = 5  # esperas de 2, 4, 8 e 16 s entre as tentativas


def _path(name: str) -> Path:
    path = Path(name)
    return path if path.is_absolute() else MODEL_DIR / path


def _ensure(path: Path) -> Path:
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    url = f"{DOWNLOAD_URL}/{path.name}"
    tmp = path.with_suffix(path.suffix + ".part")
    # Logo depois que o container sobe o DNS às vezes ainda não responde.
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        log.info("baixando %s (tentativa %d)", url, attempt)
        try:
            urllib.request.urlretrieve(url, tmp)
            break
        except OSError as exc:
            if attempt == DOWNLOAD_ATTEMPTS:
                raise RuntimeError(f"não foi possível baixar {url}: {exc}") from exc
            time.sleep(2**attempt)
    tmp.replace(path)
    return path


def _misaki(module: str, class_name: str):
    try:
        mod = __import__(f"misaki.{module}", fromlist=[class_name])
        return getattr(mod, class_name)
    except Exception as exc:  # noqa: BLE001 - dependência opcional
        log.warning("misaki.%s indisponível (%s): vozes desse idioma ficam de fora", module, exc)
        return None


class KokoroEngine(TTSEngine):
    name = "kokoro"

    def __init__(self) -> None:
        self.model = None
        self._g2p = {prefix: cls for prefix, (mod, name) in MISAKI.items() if (cls := _misaki(mod, name))}
        self._g2p_ready: dict = {}
        # O arquivo de vozes é pequeno e é ele que define a lista do player,
        # então é lido já na inicialização, antes do modelo carregar. Se o
        # download falhar aqui, o app sobe mesmo assim e load() tenta de novo
        # (a falha aparece em /api/health em vez de derrubar o processo).
        self._voices: list[Voice] = []
        try:
            self._voices = self._load_voices()
        except Exception:  # noqa: BLE001
            log.exception("vozes do Kokoro indisponíveis na inicialização; nova tentativa ao carregar o modelo")

    def _load_voices(self) -> list[Voice]:
        return self._read_voices(_ensure(_path(VOICES_FILE)), skip=set(MISAKI) - set(self._g2p))

    def load(self) -> None:
        from kokoro_onnx import Kokoro

        if not self._voices:
            self._voices = self._load_voices()
        model_path = _ensure(_path(MODEL_FILE))
        log.info("carregando %s", model_path)
        self.model = Kokoro(str(model_path), str(_path(VOICES_FILE)))
        self._g2p_ready = {prefix: cls() for prefix, cls in self._g2p.items()}

    def voices(self) -> list[Voice]:
        return self._voices

    def cache_id(self) -> str:
        return f"kokoro|{Path(MODEL_FILE).name}|{Path(VOICES_FILE).name}"

    def synthesize(self, text: str, voice: Voice) -> tuple[np.ndarray, int]:
        name = voice.params["voice"]
        g2p = self._g2p_ready.get(name[0])
        if g2p:
            phonemes, _ = g2p(text)
            audio, sr = self.model.create(phonemes, voice=name, is_phonemes=True)
        else:
            audio, sr = self.model.create(text, voice=name, lang=voice.params["lang"])
        return np.asarray(audio, dtype=np.float32), sr

    @staticmethod
    def _read_voices(path: Path, skip: set[str] = frozenset()) -> list[Voice]:
        names = sorted(np.load(path).keys())
        order = list(LANGUAGES)
        voices = []
        for name in names:
            prefix, _, short = name.partition("_")
            if len(prefix) != 2 or prefix[0] not in LANGUAGES or prefix[0] in skip:
                continue
            espeak, iso, group = LANGUAGES[prefix[0]]
            gender = GENDERS.get(prefix[1], "")
            label = short.replace("_", " ").title() + (f" ({gender})" if gender else "")
            voices.append(
                Voice(name, label, languages=(iso,), group=group, params={
                    "voice": name, "lang": espeak, "g2p": "misaki" if prefix[0] in MISAKI else "espeak",
                })
            )
        voices.sort(key=lambda v: (order.index(v.id[0]), v.id != DEFAULT_VOICE, v.id))
        return voices
