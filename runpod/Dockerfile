FROM ubuntu:24.04

# System deps: ffmpeg for audio resampling, ca-certificates for HTTPS
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python for the RunPod handler + huggingface_hub for model download
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --break-system-packages runpod huggingface_hub

# Download Qwen3-TTS Rust binaries (CPU build, ~138MB)
# Latest release: https://github.com/second-state/qwen3_tts_rs/releases
ARG QWEN3_VERSION=v0.2.2
RUN curl -fsSL \
    "https://github.com/second-state/qwen3_tts_rs/releases/download/${QWEN3_VERSION}/qwen3-tts-linux-x86_64.zip" \
    -o /tmp/qwen3.zip && \
    apt-get update && apt-get install -y --no-install-recommends unzip && \
    unzip -q /tmp/qwen3.zip -d /tmp/qwen3_extract && \
    mkdir -p /app/bin && \
    QWEN_DIR=/tmp/qwen3_extract/qwen3-tts-linux-x86_64 && \
    cp "$QWEN_DIR/tts" "$QWEN_DIR/voice_clone" "$QWEN_DIR/api_server" /app/bin/ && \
    cp -r "$QWEN_DIR/libtorch" /app/libtorch && \
    rm -rf /tmp/qwen3.zip /tmp/qwen3_extract && \
    apt-get remove -y unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Download Qwen3-TTS 0.6B models from HuggingFace (~4.8GB total)
RUN mkdir -p /models && \
    python3 -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-TTS-12Hz-0.6B-Base', local_dir='/models/Qwen3-TTS-12Hz-0.6B-Base', local_dir_use_symlinks=False)" && \
    python3 -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice', local_dir='/models/Qwen3-TTS-12Hz-0.6B-CustomVoice', local_dir_use_symlinks=False)"

# Copy handler
COPY runpod/handler.py /app/handler.py

WORKDIR /app

# RunPod serverless expects the handler module
ENV PYTHONUNBUFFERED=1

CMD ["python3", "-u", "handler.py"]
