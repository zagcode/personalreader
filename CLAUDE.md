# personalreader

Leitor TTS para treino de audição. FastAPI + docling (conversão para Markdown) + Kokoro via kokoro-onnx (TTS em CPU). Frontend é HTML/CSS/JS puro em `static/`, sem build.

- `app/segmenter.py`: Markdown → blocos → frases (unidade de síntese). Tem testes em `tests/test_segmenter.py`.
- `app/tts/queue.py`: fila com **um** worker e prioridade (frase tocando > pré-carga). Não paralelizar: em CPU só piora.
- `app/tts/base.py`: contrato `TTSEngine`/`Voice`. Fila, cache, API e player só conhecem isso; nada fora de `app/tts/engines/` pode importar um motor específico.
- `app/tts/engines/`: um módulo por motor (`kokoro.py` em produção, `mock.py` para testes e dev), cada um com suas vozes e opções de ambiente (prefixo próprio). Registro em `engines/__init__.py`; `TTS_ENGINE` aceita nome ou `modulo:Classe`.
- Kokoro: a voz define o idioma dos fonemas (espeak; chinês via misaki). Japonês fica oculto sem `misaki[ja]`. Modelo fp32 é o padrão: o int8 foi 10x mais lento em CPU.
- `static/app.js`: player; pausas de confirmação calculadas em `computeUnits`/`chunkEndFor`.
- Rodar local: `TTS_ENGINE=mock .venv/Scripts/python -m uvicorn app.main:app --reload`; testes: `.venv/Scripts/python -m pytest`.
- Deploy: Docker (`docker compose up -d --build`) atrás do Traefik da VPS (labels no `docker-compose.yml`, variáveis `TRAEFIK_*` no `.env`). A rota de áudio segura a resposta até a síntese terminar; não pôr timeout curto no proxy.
- UI: seguir o sistema visual existente (Literata no texto, Atkinson Hyperlegible Next na UI, marca-texto amarelo como único destaque).
