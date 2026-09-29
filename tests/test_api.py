import time

from fastapi.testclient import TestClient

from app.main import app


def test_upload_read_and_audio():
    with TestClient(app) as client:
        text = "A primeira frase do teste é esta. A segunda frase do teste vem aqui.\n\nOutro parágrafo com texto suficiente."
        res = client.post("/api/documents", files={"file": ("nota.txt", text.encode(), "text/plain")})
        assert res.status_code == 201
        doc_id = res.json()["id"]

        for _ in range(50):
            doc = client.get(f"/api/documents/{doc_id}").json()
            if doc["status"] != "processing":
                break
            time.sleep(0.1)
        assert doc["status"] == "ready", doc
        assert doc["segments"] == 3
        assert doc["duration"] > 0

        res = client.post(f"/api/documents/{doc_id}/prefetch", json={"voice": "grave", "start": 0, "end": 99})
        assert res.json()["end"] == 3

        audio = client.get(f"/api/documents/{doc_id}/segments/0/audio?voice=grave")
        assert audio.status_code == 200
        assert audio.headers["content-type"].startswith("audio/")
        assert len(audio.content) > 1000

        assert client.get(f"/api/documents/{doc_id}/segments/9/audio").status_code == 404
        assert client.post("/api/documents", files={"file": ("x.exe", b"MZ")}).status_code == 415
        assert client.delete(f"/api/documents/{doc_id}").status_code == 204
        assert client.get("/api/documents/..%2F..%2Fetc").status_code == 404
