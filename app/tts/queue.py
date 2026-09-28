"""Fila de síntese com um único worker.

Em CPU, rodar duas sínteses em paralelo só divide os núcleos e atrasa as duas.
Por isso há um worker só, com prioridade: a frase que o player está esperando
(PRIORITY_NOW) passa na frente das frases pré-carregadas (PRIORITY_AHEAD).
"""

import hashlib
import heapq
import itertools
import logging
import threading
import time
from concurrent.futures import CancelledError, Future
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

from .. import config
from .voices import Voice

log = logging.getLogger(__name__)

PRIORITY_NOW = 0
PRIORITY_AHEAD = 10


def _pick_format() -> str:
    if config.AUDIO_FORMAT == "mp3" and "MP3" in sf.available_formats():
        return "mp3"
    return "wav"


AUDIO_EXT = _pick_format()
AUDIO_MIME = {"mp3": "audio/mpeg", "wav": "audio/wav"}[AUDIO_EXT]


def cache_key(engine_name: str, voice: Voice, text: str) -> str:
    raw = "|".join([engine_name, config.VOXCPM_MODEL, voice.id, voice.style, str(voice.seed), text])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def audio_path(key: str) -> Path:
    return config.AUDIO_DIR / key[:2] / f"{key}.{AUDIO_EXT}"


@dataclass
class Job:
    key: str
    text: str
    voice: Voice
    doc_id: str
    priority: int
    future: Future = field(default_factory=Future)
    running: bool = False


class TTSQueue:
    def __init__(self, engine) -> None:
        self.engine = engine
        self._heap: list[tuple[int, int, str]] = []
        self._jobs: dict[str, Job] = {}
        self._seq = itertools.count()
        self._cond = threading.Condition()
        self._thread: threading.Thread | None = None
        self.ready = False
        self.load_error: str | None = None
        # Segundos de processamento por segundo de áudio (real-time factor), média móvel.
        self.rtf: float | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="tts-worker", daemon=True)
        self._thread.start()

    def submit(self, text: str, voice: Voice, doc_id: str, priority: int) -> tuple[str, Future]:
        key = cache_key(self.engine.name, voice, text)
        if audio_path(key).exists():
            done: Future = Future()
            done.set_result(audio_path(key))
            return key, done

        with self._cond:
            job = self._jobs.get(key)
            if job is None:
                job = Job(key, text, voice, doc_id, priority)
                self._jobs[key] = job
                heapq.heappush(self._heap, (priority, next(self._seq), key))
                self._cond.notify()
            elif priority < job.priority and not job.running:
                job.priority = priority
                heapq.heappush(self._heap, (priority, next(self._seq), key))
                self._cond.notify()
            return key, job.future

    def cancel_doc(self, doc_id: str, keep: set[str] | None = None) -> int:
        """Descarta frases pendentes de um documento (ex.: o usuário pulou para outro trecho)."""
        keep = keep or set()
        dropped = 0
        with self._cond:
            for key, job in list(self._jobs.items()):
                if job.doc_id == doc_id and not job.running and key not in keep:
                    del self._jobs[key]
                    job.future.cancel()
                    dropped += 1
        return dropped

    def status(self) -> dict:
        with self._cond:
            running = next((j for j in self._jobs.values() if j.running), None)
            return {
                "engine": self.engine.name,
                "ready": self.ready,
                "error": self.load_error,
                "pending": sum(1 for j in self._jobs.values() if not j.running),
                "busy": running is not None,
                "rtf": round(self.rtf, 2) if self.rtf else None,
            }

    def _next_job(self) -> Job:
        with self._cond:
            while True:
                while self._heap:
                    priority, _, key = heapq.heappop(self._heap)
                    job = self._jobs.get(key)
                    # Entradas obsoletas: job cancelado ou re-enfileirado com outra prioridade.
                    if job and not job.running and job.priority == priority:
                        job.running = True
                        return job
                self._cond.wait()

    def _run(self) -> None:
        try:
            self.engine.load()
            self.ready = True
            log.info("motor TTS %s pronto", self.engine.name)
        except Exception as exc:  # noqa: BLE001 - reportado em /api/health
            log.exception("falha ao carregar o motor TTS")
            self.load_error = f"{type(exc).__name__}: {exc}"
            return

        while True:
            job = self._next_job()
            try:
                started = time.perf_counter()
                wav, sr = self.engine.synthesize(job.text, job.voice)
                elapsed = time.perf_counter() - started
                path = self._write(job.key, wav, sr)
                duration = max(len(wav) / sr, 0.1)
                rtf = elapsed / duration
                self.rtf = rtf if self.rtf is None else 0.7 * self.rtf + 0.3 * rtf
                log.info("frase sintetizada: %.1fs de áudio em %.1fs (%d chars)", duration, elapsed, len(job.text))
                job.future.set_result(path)
            except Exception as exc:  # noqa: BLE001 - devolvido ao cliente
                log.exception("falha na síntese")
                if not job.future.cancelled():
                    job.future.set_exception(exc)
            finally:
                with self._cond:
                    self._jobs.pop(job.key, None)

    @staticmethod
    def _write(key: str, wav: np.ndarray, sr: int) -> Path:
        path = audio_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        wav = np.clip(wav, -1.0, 1.0)
        if AUDIO_EXT == "mp3":
            sf.write(tmp, wav, sr, format="MP3")
        else:
            sf.write(tmp, wav, sr, format="WAV", subtype="PCM_16")
        tmp.replace(path)
        return path


__all__ = ["TTSQueue", "PRIORITY_NOW", "PRIORITY_AHEAD", "AUDIO_MIME", "CancelledError"]
