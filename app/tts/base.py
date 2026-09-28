"""Contrato dos motores de voz.

O resto do app (fila, cache, API, player) só conhece esta interface. Para trocar
o modelo, implemente um TTSEngine novo e aponte TTS_ENGINE para ele; nada fora
de app/tts/engines/ precisa mudar.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Voice:
    id: str
    label: str
    # Códigos ISO 639-1 que a voz fala. Vazio = qualquer idioma (o modelo detecta pelo texto).
    languages: tuple[str, ...] = ()
    # Parâmetros próprios do motor (descrição de estilo, semente, arquivo de referência...).
    # Entram na chave do cache: mudar um deles gera áudio novo.
    params: dict = field(default_factory=dict)


class TTSEngine(ABC):
    #: identificador curto, usado em logs e em /api/health
    name: str = "engine"

    def load(self) -> None:
        """Carrega o modelo. Roda uma vez, na thread do worker, antes da primeira síntese."""

    @abstractmethod
    def voices(self) -> list[Voice]:
        """Vozes oferecidas no player. A primeira é a padrão."""

    @abstractmethod
    def synthesize(self, text: str, voice: Voice) -> tuple[np.ndarray, int]:
        """Gera o áudio de uma frase: (onda mono float32 em [-1, 1], sample rate)."""

    def cache_id(self) -> str:
        """Tudo que muda o áudio além do texto e da voz (modelo, precisão, passos...).

        O cache em disco é indexado por isto; mudar o valor invalida o áudio antigo.
        """
        return self.name

    def get_voice(self, voice_id: str) -> Voice:
        voices = self.voices()
        return next((v for v in voices if v.id == voice_id), voices[0])
