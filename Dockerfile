FROM python:3.11-slim

# true = inclui o VoxCPM2 (TTS_ENGINE=voxcpm); a imagem padrão só tem o Kokoro.
ARG WITH_VOXCPM=false

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/data/hf \
    DATA_DIR=/data/app

# libgl/libglib: opencv usado pelo docling em PDFs; ffmpeg: torchcodec do VoxCPM.
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && if [ "$WITH_VOXCPM" = "true" ]; then apt-get install -y --no-install-recommends ffmpeg; fi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Torch de CPU primeiro (o docling usa), para o pip não puxar a build CUDA como dependência.
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt requirements-voxcpm.txt ./
RUN pip install -r requirements.txt \
    && if [ "$WITH_VOXCPM" = "true" ]; then \
        pip install torchaudio --index-url https://download.pytorch.org/whl/cpu \
        && pip install -r requirements-voxcpm.txt; \
    fi

COPY app ./app
COPY static ./static

EXPOSE 8000
VOLUME ["/data"]

# Um worker só: a fila de síntese e o modelo vivem no processo.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
