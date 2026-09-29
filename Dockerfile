FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/data/hf \
    DATA_DIR=/data/app

# libgl/libglib: opencv usado pelo docling em PDFs.
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Torch de CPU primeiro (o docling usa), para o pip não puxar a build CUDA como dependência.
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt ./
RUN pip install -r requirements.txt

# Modelos do docling (layout e tabelas) dentro da imagem: a conversão não depende
# da internet na hora do upload. Com DOCLING_OCR=true o modelo de OCR ainda é
# baixado na primeira conversão.
ENV DOCLING_ARTIFACTS_PATH=/opt/docling-models
RUN docling-tools models download -o "$DOCLING_ARTIFACTS_PATH" layout tableformer

COPY app ./app
COPY static ./static

EXPOSE 8000
VOLUME ["/data"]

# Um worker só: a fila de síntese e o modelo vivem no processo.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
