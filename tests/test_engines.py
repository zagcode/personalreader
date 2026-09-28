import numpy as np
import pytest

from app.tts.base import TTSEngine, Voice
from app.tts.engines import create_engine
from app.tts.engines.mock import MockEngine
from app.tts.queue import cache_key


def test_registry_by_name_and_by_path():
    assert isinstance(create_engine("mock"), MockEngine)
    assert isinstance(create_engine("app.tts.engines.mock:MockEngine"), MockEngine)


def test_unknown_engine_is_rejected():
    with pytest.raises(ValueError):
        create_engine("nao-existe")
    with pytest.raises(TypeError):
        create_engine("pathlib:Path")  # classe que não é um TTSEngine


def test_mock_honours_contract():
    engine = create_engine("mock")
    voices = engine.voices()
    assert voices and all(isinstance(v, Voice) for v in voices)
    assert engine.get_voice("nao-existe") == voices[0]
    wav, sr = engine.synthesize("Uma frase curta.", voices[0])
    assert wav.dtype == np.float32 and wav.ndim == 1 and sr > 0
    assert np.abs(wav).max() <= 1.0


class _Fixed(TTSEngine):
    name = "fixo"

    def __init__(self, cache: str = "fixo"):
        self._cache = cache

    def voices(self):
        return [Voice("a", "A")]

    def synthesize(self, text, voice):
        return np.zeros(10, dtype=np.float32), 16000

    def cache_id(self):
        return self._cache


def test_cache_key_changes_with_engine_voice_params_and_text():
    voice = Voice("a", "A", params={"seed": 1})
    base = cache_key(_Fixed(), voice, "texto")
    assert base == cache_key(_Fixed(), Voice("a", "A", params={"seed": 1}), "texto")
    assert base != cache_key(_Fixed("outro-modelo"), voice, "texto")
    assert base != cache_key(_Fixed(), Voice("a", "A", params={"seed": 2}), "texto")
    assert base != cache_key(_Fixed(), voice, "outro texto")


def test_kokoro_voices_are_grouped_by_language(tmp_path, monkeypatch):
    import numpy as np

    from app.tts.engines import kokoro

    voices_file = tmp_path / "voices.bin"
    np.savez(voices_file, pm_alex=np.zeros(1), af_heart=np.zeros(1), af_bella=np.zeros(1), xx_bad=np.zeros(1))
    voices = kokoro.KokoroEngine._read_voices(voices_file.with_suffix(".bin.npz"))
    assert [v.id for v in voices] == ["af_heart", "af_bella", "pm_alex"]
    alex = voices[-1]
    assert alex.group == "Português (Brasil)" and alex.languages == ("pt",)
    assert alex.params == {"voice": "pm_alex", "lang": "pt-br", "g2p": "espeak"}
    assert alex.label == "Alex (masculina)"
