"""VoxCPM2 (OpenBMB): 30 idiomas detectados pelo texto, voice design e clonagem.

Opções (variáveis de ambiente, lidas só quando este motor é o escolhido):
  VOXCPM_MODEL       id no Hugging Face ou pasta local (padrão openbmb/VoxCPM2)
  VOXCPM_DEVICE      cpu | cuda | mps | auto
  VOXCPM_DTYPE       auto | float32 | bfloat16
  VOXCPM_TIMESTEPS   passos de difusão (padrão 10; menos = mais rápido)
  VOXCPM_CFG         guidance (padrão 2.0)
  TORCH_THREADS      núcleos do torch (0 = todos)
"""

import json
import logging
import os
import threading
from pathlib import Path

import numpy as np

from ... import config
from ..base import TTSEngine, Voice

log = logging.getLogger(__name__)

MODEL = os.getenv("VOXCPM_MODEL", "openbmb/VoxCPM2")
DEVICE = os.getenv("VOXCPM_DEVICE", "cpu")
# auto = float32 em CPU (mais rápido sem bf16 no hardware, porém ~10 GB de RAM)
DTYPE = os.getenv("VOXCPM_DTYPE", "auto")
TIMESTEPS = int(os.getenv("VOXCPM_TIMESTEPS", "10"))
CFG = float(os.getenv("VOXCPM_CFG", "2.0"))
TORCH_THREADS = int(os.getenv("TORCH_THREADS", "0"))


def _preset(voice_id: str, label: str, style: str, seed: int) -> Voice:
    return Voice(voice_id, label, params={"style": style, "seed": seed})


# Voice design: a descrição entre parênteses no início do texto define a voz.
PRESETS = [
    _preset("natural", "Natural", "", 7),
    _preset(
        "professora",
        "Clara e pausada",
        "A clear, calm female voice speaking slowly and articulating every word, like a patient language teacher",
        11,
    ),
    _preset("narrador", "Narrador grave", "A deep, warm male voice, steady unhurried pace, like an audiobook narrator", 23),
    _preset("conversa", "Conversa natural", "A young, friendly voice at a natural conversational pace", 31),
]


class VoxCPMEngine(TTSEngine):
    name = "voxcpm"

    def __init__(self) -> None:
        self.model = None
        self.sample_rate = 48000
        self.dtype = DTYPE
        self._anchor_lock = threading.Lock()

    # ------------------------------------------------------------ contrato

    def load(self) -> None:
        import torch
        from voxcpm import VoxCPM

        if TORCH_THREADS > 0:
            torch.set_num_threads(TORCH_THREADS)
        model_path = self._model_path()
        log.info("carregando %s em %s (%s)", model_path, DEVICE, self.dtype)
        # optimize=False: o torch.compile do VoxCPM usa CUDA graphs ("reduce-overhead"),
        # que em CPU só atrasa a primeira síntese sem ganho.
        self.model = VoxCPM.from_pretrained(
            model_path,
            load_denoiser=False,
            optimize=DEVICE != "cpu",
            device=DEVICE,
        )
        self.sample_rate = self.model.tts_model.sample_rate

    def voices(self) -> list[Voice]:
        """Presets + clones: data/voices/<nome>.wav (e <nome>.txt com a transcrição, se houver)."""
        voices = list(PRESETS)
        for wav in sorted(config.VOICES_DIR.glob("*.wav")):
            if wav.stem.startswith("_"):
                continue
            transcript = wav.with_suffix(".txt")
            voices.append(
                Voice(
                    f"clone-{wav.stem}",
                    wav.stem.replace("-", " ").replace("_", " ").title(),
                    params={
                        "reference_wav": str(wav),
                        "reference_text": transcript.read_text(encoding="utf-8").strip() if transcript.exists() else "",
                        "seed": 7,
                    },
                )
            )
        return voices

    def cache_id(self) -> str:
        return f"voxcpm|{MODEL}|{self._resolved_dtype()}|{TIMESTEPS}|{CFG}"

    def synthesize(self, text: str, voice: Voice) -> tuple[np.ndarray, int]:
        import torch

        p = voice.params
        kwargs = {"cfg_value": CFG, "inference_timesteps": TIMESTEPS}
        # O parâmetro seed= só existe no VoxCPM do GitHub; a versão do PyPI não aceita.
        torch.manual_seed(p.get("seed", 7))
        anchor = self._anchor_path(voice)
        if p.get("reference_wav"):
            kwargs["reference_wav_path"] = p["reference_wav"]
            if p.get("reference_text"):
                kwargs["prompt_wav_path"] = p["reference_wav"]
                kwargs["prompt_text"] = p["reference_text"]
        elif anchor and anchor.exists():
            # Voz desenhada por descrição varia de timbre entre frases; a primeira
            # frase gerada vira referência fixa para as seguintes.
            kwargs["reference_wav_path"] = str(anchor)

        style = p.get("style")
        wav = self.model.generate(text=f"({style}){text}" if style else text, **kwargs)

        if anchor and not anchor.exists():
            self._save_anchor(anchor, wav)
        return wav.astype(np.float32), self.sample_rate

    # ------------------------------------------------------------ detalhes

    def _resolved_dtype(self) -> str:
        if DTYPE != "auto":
            return DTYPE
        return "float32" if DEVICE == "cpu" else "bfloat16"

    def _model_path(self) -> str:
        """Pasta do modelo com o dtype pedido em VOXCPM_DTYPE.

        O VoxCPM2 vem configurado em bfloat16. Em CPU sem instruções bf16
        (AMX / AVX-512 BF16) essas contas são emuladas: no teste local, float32
        gerou o áudio 3,6× mais rápido, ao custo do dobro de RAM (~10 GB).
        O dtype só é lido do config.json, então montamos uma cópia da pasta com
        hardlinks para os pesos e o config alterado.
        """
        from huggingface_hub import snapshot_download

        source = Path(MODEL)
        if not source.is_dir():
            source = Path(snapshot_download(MODEL))
        cfg = json.loads((source / "config.json").read_text(encoding="utf-8"))
        dtype = self.dtype = self._resolved_dtype()
        if cfg.get("dtype") == dtype:
            return str(source)

        target = config.DATA_DIR / "models" / f"{source.name}-{dtype}"
        target.mkdir(parents=True, exist_ok=True)
        for f in source.iterdir():
            dest = target / f.name
            if f.name == "config.json" or dest.exists():
                continue
            try:
                os.link(f.resolve(), dest)
            except OSError:
                os.symlink(f.resolve(), dest)
        cfg["dtype"] = dtype
        (target / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        return str(target)

    def _anchor_path(self, voice: Voice) -> Path | None:
        if voice.params.get("reference_wav") or not voice.params.get("style"):
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
