"""Registro dos motores de voz.

TTS_ENGINE aceita um nome deste registro ou o caminho de qualquer classe que
implemente app.tts.base.TTSEngine, no formato "pacote.modulo:Classe".
O import é feito só do motor escolhido, então as dependências dos outros
(torch, voxcpm...) não precisam estar instaladas.
"""

import importlib

from ..base import TTSEngine

ENGINES = {
    "mock": "app.tts.engines.mock:MockEngine",
    "voxcpm": "app.tts.engines.voxcpm:VoxCPMEngine",
}


def create_engine(spec: str) -> TTSEngine:
    target = ENGINES.get(spec, spec)
    if ":" not in target:
        raise ValueError(
            f"TTS_ENGINE desconhecido: {spec!r}. Use {', '.join(ENGINES)} ou 'pacote.modulo:Classe'."
        )
    module_name, class_name = target.split(":", 1)
    engine = getattr(importlib.import_module(module_name), class_name)()
    if not isinstance(engine, TTSEngine):
        raise TypeError(f"{target} não herda de app.tts.base.TTSEngine")
    return engine
