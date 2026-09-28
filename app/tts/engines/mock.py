import numpy as np

from ..base import TTSEngine, Voice


class MockEngine(TTSEngine):
    """Gera tons curtos (um por palavra) com duração proporcional ao texto.

    Serve para desenvolver a interface sem baixar nenhum modelo.
    """

    name = "mock"
    sample_rate = 24000

    def voices(self) -> list[Voice]:
        return [
            Voice("grave", "Tom grave", params={"base": 150}),
            Voice("agudo", "Tom agudo", params={"base": 260}),
        ]

    def synthesize(self, text: str, voice: Voice) -> tuple[np.ndarray, int]:
        sr = self.sample_rate
        base = voice.params.get("base", 200)
        chunks = []
        for n, word in enumerate(text.split()):
            dur = 0.08 + 0.055 * len(word)
            t = np.arange(int(sr * dur)) / sr
            freq = base * (1 + 0.15 * ((n * 7) % 4))
            env = np.sin(np.pi * t / dur) ** 2
            chunks.append(0.18 * env * np.sin(2 * np.pi * freq * t))
            chunks.append(np.zeros(int(sr * 0.06)))
        chunks.append(np.zeros(int(sr * 0.25)))
        return np.concatenate(chunks).astype(np.float32), sr
