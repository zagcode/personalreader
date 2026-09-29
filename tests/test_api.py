import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.tts.queue import DocumentGone, TTSQueue


@pytest.fixture(scope="module")
def client():
    # Um cliente só: o encerramento do app desliga o pool de conversão.
    with TestClient(app) as c:
        yield c


def _upload_ready(client, name: str, text: str) -> dict:
    res = client.post("/api/documents", files={"file": (name, text.encode(), "text/plain")})
    assert res.status_code == 201
    doc_id = res.json()["id"]
    for _ in range(50):
        doc = client.get(f"/api/documents/{doc_id}").json()
        if doc["status"] != "processing":
            break
        time.sleep(0.1)
    assert doc["status"] == "ready", doc
    return doc


def test_upload_read_and_audio(client):
    text = "A primeira frase do teste é esta. A segunda frase do teste vem aqui.\n\nOutro parágrafo com texto suficiente."
    doc = _upload_ready(client, "nota.txt", text)
    doc_id = doc["id"]
    assert doc["segments"] == 3
    assert doc["duration"] > 0

    res = client.post(f"/api/documents/{doc_id}/prefetch", json={"voice": "grave", "start": 0, "end": 99})
    assert res.json()["end"] == 3

    audio = client.get(f"/api/documents/{doc_id}/segments/0/audio?voice=grave")
    assert audio.status_code == 200
    assert audio.headers["content-type"].startswith("audio/")
    assert len(audio.content) > 1000

    assert client.get(f"/api/documents/{doc_id}/segments/9/audio").status_code == 404
    bad = client.post("/api/documents", files={"file": ("x.exe", b"MZ")})
    assert bad.status_code == 415
    # Erros saem como código + parâmetros; a página traduz.
    assert bad.json()["detail"] == {"code": "unsupported_format", "params": {"ext": ".exe"}}
    assert client.delete(f"/api/documents/{doc_id}").status_code == 204
    assert client.get("/api/documents/..%2F..%2Fetc").status_code == 404


def test_deleting_document_removes_its_audio(client):
    doc_id = _upload_ready(client, "a.txt", "Uma frase com texto suficiente para virar um segmento.")["id"]
    assert client.get(f"/api/documents/{doc_id}/segments/0/audio").status_code == 200
    assert len(list((config.DOCS_DIR / doc_id / "audio").iterdir())) == 1

    assert client.delete(f"/api/documents/{doc_id}").status_code == 204
    assert not (config.DOCS_DIR / doc_id).exists()


def test_late_synthesis_does_not_recreate_deleted_document():
    gone = "f" * 32
    with pytest.raises(DocumentGone):
        TTSQueue._write(gone, "chave", np.zeros(2400, dtype=np.float32), 24000)
    assert not (config.DOCS_DIR / gone).exists()
