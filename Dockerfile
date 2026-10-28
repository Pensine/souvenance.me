# Souvenance / Pensine — one image for the API, the MCP server and the cycles.
# Built by `docker compose build`; settings through arguments:
#   EXTRAS          pyproject extras (default: api,embeddings)
#   TRANSCRIPTION   none | faster-whisper (default, no torch) | whisperx
#   WITH_CLAUDE_CLI 1 = installs the Claude CLI (claude-cli backend), 0 = no
FROM python:3.12-slim-trixie

ARG EXTRAS="api,embeddings"
ARG TRANSCRIPTION="faster-whisper"
ARG WITH_CLAUDE_CLI=1

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    PENSINE_DATA_DIR=/data \
    HF_HOME=/data/cache/huggingface

# ffmpeg: audio and video; postgresql-client (17, like the database): backup;
# rsync: media copy; tzdata: the cycles' time follows TZ
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg postgresql-client rsync curl ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY deploy/docker/requirements.py /tmp/requirements.py
# CPU build of torch (dedicated index) when a component requires it: avoids
# GBs of useless CUDA, and keeps torch/torchaudio from the same index (WhisperX)
RUN python /tmp/requirements.py "$EXTRAS" "$TRANSCRIPTION" > /tmp/requirements.txt \
 && if echo "$EXTRAS" | grep -qE 'embeddings|local' || [ "$TRANSCRIPTION" = whisperx ]; then \
      pip install --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.8.*" "torchaudio==2.8.*"; \
    fi \
 && pip install -r /tmp/requirements.txt

RUN useradd --create-home --uid 1000 souvenance \
 && mkdir -p /data && chown souvenance:souvenance /data
USER souvenance
ENV PATH=/home/souvenance/.local/bin:$PATH
# Claude CLI (subscription): official installer. Without network or without
# need, the image still builds; the other backends are enough.
RUN if [ "$WITH_CLAUDE_CLI" = 1 ]; then \
      curl -fsSL https://claude.ai/install.sh | bash \
      || echo "WARNING: Claude CLI not installed (claude-cli backend unavailable)"; \
    fi

COPY --chown=souvenance:souvenance . /app

VOLUME ["/data"]
EXPOSE 8300 8400
CMD ["python", "-m", "pensine.mcp_server"]
