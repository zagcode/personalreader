"""Vozes disponíveis: presets de "voice design" do VoxCPM2 e clones de data/voices/*.wav."""

from dataclasses import dataclass
from pathlib import Path

from .. import config


@dataclass(frozen=True)
class Voice:
    id: str
    label: str
    style: str = ""  # descrição em linguagem natural (voice design / controle de estilo)
    seed: int = 42
    reference_wav: Path | None = None
    reference_text: str = ""


PRESETS = [
    Voice("natural", "Natural", "", seed=7),
    Voice(
        "professora",
        "Clara e pausada",
        "A clear, calm female voice speaking slowly and articulating every word, like a patient language teacher",
        seed=11,
    ),
    Voice(
        "narrador",
        "Narrador grave",
        "A deep, warm male voice, steady unhurried pace, like an audiobook narrator",
        seed=23,
    ),
    Voice(
        "conversa",
        "Conversa natural",
        "A young, friendly voice at a natural conversational pace",
        seed=31,
    ),
]


def list_voices() -> list[Voice]:
    voices = list(PRESETS)
    for wav in sorted(config.VOICES_DIR.glob("*.wav")):
        if wav.stem.startswith("_"):
            continue
        transcript = wav.with_suffix(".txt")
        voices.append(
            Voice(
                id=f"clone-{wav.stem}",
                label=wav.stem.replace("-", " ").replace("_", " ").title(),
                reference_wav=wav,
                reference_text=transcript.read_text(encoding="utf-8").strip() if transcript.exists() else "",
            )
        )
    return voices


def get_voice(voice_id: str) -> Voice:
    for v in list_voices():
        if v.id == voice_id:
            return v
    return PRESETS[0]
