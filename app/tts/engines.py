"""Motores de síntese. Todos expõem synthesize(text, voice) -> (wav float32, sample_rate)."""

import logging
import sys
import threading
from pathlib import Path

import numpy as np

from .. import config
from .voices import Voice

log = logging.getLogger(__name__)


class MockEngine:
    """Gera tons curtos (um por palavra) com duração proporcional ao texto.

    Serve para desenvolver a interface sem baixar os ~5 GB do VoxCPM2.
    """

    name = "mock"
    sample_rate = 24000

    def load(self) -> None:
        pass

    def synthesize(self, text: str, voice: Voice) -> tuple[np.ndarray, int]:
        sr = self.sample_rate
        chunks = []
        base = 180 + (hash(voice.id) % 5) * 30
        for n, word in enumerate(text.split()):
            dur = 0.08 + 0.055 * len(word)
            t = np.arange(int(sr * dur)) / sr
            freq = base * (1 + 0.15 * ((n * 7) % 4))
            env = np.sin(np.pi * t / dur) ** 2
            chunks.append(0.18 * env * np.sin(2 * np.pi * freq * t))
            chunks.append(np.zeros(int(sr * 0.06)))
        chunks.append(np.zeros(int(sr * 0.25)))
        return np.concatenate(chunks).astype(np.float32), sr


class VoxCPMEngine:
    name = "voxcpm"

    def __init__(self) -> None:
        self.model = None
        self.sample_rate = 48000
        self._anchor_lock = threading.Lock()

    def load(self) -> None:
        import torch
        from voxcpm import VoxCPM

        if config.TORCH_THREADS > 0:
            torch.set_num_threads(config.TORCH_THREADS)
        log.info("carregando %s em %s", config.VOXCPM_MODEL, config.VOXCPM_DEVICE)
        # optimize=False: o torch.compile do VoxCPM usa CUDA graphs ("reduce-overhead"),
        # que em CPU só atrasa a primeira síntese sem ganho.
        self.model = VoxCPM.from_pretrained(
            config.VOXCPM_MODEL,
            load_denoiser=False,
            optimize=config.VOXCPM_DEVICE != "cpu",
            device=config.VOXCPM_DEVICE,
        )
        self.sample_rate = self.model.tts_model.sample_rate

    def synthesize(self, text: str, voice: Voice) -> tuple[np.ndarray, int]:
        kwargs = {
            "cfg_value": config.VOXCPM_CFG,
            "inference_timesteps": config.VOXCPM_TIMESTEPS,
            "seed": voice.seed,
        }
        anchor = self._anchor_path(voice)
        if voice.reference_wav:
            kwargs["reference_wav_path"] = str(voice.reference_wav)
            if voice.reference_text:
                kwargs["prompt_wav_path"] = str(voice.reference_wav)
                kwargs["prompt_text"] = voice.reference_text
        elif anchor and anchor.exists():
            # Voz desenhada por descrição varia de timbre entre frases; a primeira
            # frase gerada vira referência fixa para as seguintes.
            kwargs["reference_wav_path"] = str(anchor)

        prompt = f"({voice.style}){text}" if voice.style else text
        wav = self.model.generate(text=prompt, **kwargs)

        if anchor and not anchor.exists():
            self._save_anchor(anchor, wav)
        return wav.astype(np.float32), self.sample_rate

    def _anchor_path(self, voice: Voice) -> Path | None:
        if voice.reference_wav or not voice.style:
            return None
        return config.VOICES_DIR / f"_anchor_{voice.id}.wav"

    def _save_anchor(self, path: Path, wav: np.ndarray) -> None:
        import soundfile as sf

        # Uma referência curta basta; frases longas demais só pesam no prompt.
        clip = wav[: self.sample_rate * 12]
        if len(clip) < self.sample_rate * 2:
            return
        with self._anchor_lock:
            if not path.exists():
                sf.write(path, clip, self.sample_rate)


def create_engine():
    if config.TTS_ENGINE == "mock":
        return MockEngine()
    if config.TTS_ENGINE == "voxcpm":
        return VoxCPMEngine()
    print(f"TTS_ENGINE desconhecido: {config.TTS_ENGINE}", file=sys.stderr)
    raise SystemExit(1)
