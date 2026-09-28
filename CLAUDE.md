# personalreader

Leitor TTS para treino de audição. FastAPI + docling (conversão para Markdown) + VoxCPM2 (TTS em CPU). Frontend é HTML/CSS/JS puro em `static/`, sem build.

- `app/segmenter.py`: Markdown → blocos → frases (unidade de síntese). Tem testes em `tests/test_segmenter.py`.
- `app/tts/queue.py`: fila com **um** worker e prioridade (frase tocando > pré-carga). Não paralelizar: em CPU só piora.
- `app/tts/engines.py`: `VoxCPMEngine` (produção) e `MockEngine` (dev, `TTS_ENGINE=mock`).
- `static/app.js`: player; pausas de confirmação calculadas em `computeUnits`/`chunkEndFor`.
- Rodar local: `TTS_ENGINE=mock .venv/Scripts/python -m uvicorn app.main:app --reload`; testes: `.venv/Scripts/python -m pytest`.
- Deploy: Docker (`docker compose up -d --build`) atrás do Traefik da VPS (labels no `docker-compose.yml`, variáveis `TRAEFIK_*` no `.env`). A rota de áudio segura a resposta até a síntese terminar; não pôr timeout curto no proxy.
- UI: seguir o sistema visual existente (Literata no texto, Atkinson Hyperlegible Next na UI, marca-texto amarelo como único destaque).
