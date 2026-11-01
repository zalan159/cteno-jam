# Cteno Jam — one image for the web app and the processing worker.
#   docker compose up -d                 (CPU)
#   docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d   (NVIDIA GPU)
# TORCH_INDEX picks the PyTorch wheel: cpu (default) or cu121.
FROM python:3.12-slim-bookworm

ARG TORCH_INDEX=cpu
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    JAM_DATA_DIR=/data JAM_WEB_DIR=/app/web JAM_DEMO_DIR=/app/demo/songs HF_HOME=/models/hf TORCH_HOME=/models/torch \
    CTENO_SDK_HOME=/data/.cteno-sdk

ARG APT_MIRROR=
RUN if [ -n "$APT_MIRROR" ]; then sed -i "s|deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; fi && apt-get update && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --index-url "https://download.pytorch.org/whl/${TORCH_INDEX}" "torch==2.5.1" "torchaudio==2.5.1"

WORKDIR /app
COPY server/pyproject.toml server/pyproject.toml
COPY server/README.md server/README.md
COPY server/cteno_jam server/cteno_jam
RUN pip install --index-url "${PIP_INDEX_URL}" "./server[process,review]"

COPY web web
COPY demo/songs demo/songs

# Pre-fetch the separation model so the first song does not wait for a 80 MB download.
ARG PREFETCH_MODELS=1
RUN if [ "$PREFETCH_MODELS" = "1" ]; then python -c "from demucs.pretrained import get_model; get_model('htdemucs_6s')"; fi
# Whisper (~480 MB for "small") is only needed when no lyrics are given or found. By default it
# downloads on first use into the jam-models volume; set PREFETCH_WHISPER=small to bake it in.
ARG PREFETCH_WHISPER=
RUN if [ -n "$PREFETCH_WHISPER" ]; then python -c "from faster_whisper import WhisperModel; WhisperModel('$PREFETCH_WHISPER', device='cpu', compute_type='int8')"; fi

VOLUME ["/data", "/models"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fsS http://127.0.0.1:8765/api/info || exit 1
CMD ["cteno-jam"]
