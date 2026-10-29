#!/usr/bin/env bash
# Run as root in the dedicated SpeakLab Ubuntu/WSL2 distribution.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
test "$(id -u)" = 0 || { echo 'Run as root in the dedicated distribution.' >&2; exit 1; }
test -f /opt/speaklab/backend/requirements.lock || { echo 'Extract the application at /opt/speaklab first.' >&2; exit 1; }
apt-get update -qq
apt-get install -y --no-install-recommends python3-venv python3-pip libsndfile1 build-essential cmake pkg-config libopenblas-dev curl ca-certificates zstd git ffmpeg
id speaklab >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/speaklab --shell /usr/sbin/nologin speaklab
id ollama >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/ollama --shell /usr/sbin/nologin ollama
install -d -o speaklab -g speaklab /var/lib/speaklab /var/lib/speaklab/recordings
install -d -o ollama -g ollama /var/lib/ollama/models
install -d /var/cache/speaklab /var/lib/speaklab-models
python3 -m venv /opt/speaklab/.venv
/opt/speaklab/.venv/bin/pip install --disable-pip-version-check -r /opt/speaklab/backend/requirements.lock
/opt/speaklab/.venv/bin/pip install --disable-pip-version-check --no-deps -e /opt/speaklab/backend
if ! command -v ollama >/dev/null; then
  curl --fail --location --retry 3 --silent --show-error https://ollama.com/download/ollama-linux-amd64.tar.zst -o /var/cache/speaklab/ollama-linux-amd64.tar.zst
  tar --zstd -xf /var/cache/speaklab/ollama-linux-amd64.tar.zst -C /usr/local
fi
if ! test -d /opt/whisper.cpp/.git; then
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git /opt/whisper.cpp
fi
cmake -S /opt/whisper.cpp -B /opt/whisper.cpp/build -DCMAKE_BUILD_TYPE=Release -DWHISPER_BUILD_SERVER=ON -DGGML_CUDA=OFF -DGGML_BLAS=ON -DGGML_BLAS_VENDOR=OpenBLAS
cmake --build /opt/whisper.cpp/build --config Release -j 4
if ! test -s /var/lib/speaklab-models/ggml-small.en.bin; then
  bash /opt/whisper.cpp/models/download-ggml-model.sh small.en /var/lib/speaklab-models
fi
if ! test -f /opt/speaklab/.env; then
  server_name="${SPEAKLAB_SERVER_NAME:-$(hostname)}"
  cat > /opt/speaklab/.env <<ENV
SPEAKLAB_DATA_DIR=/var/lib/speaklab
SPEAKLAB_OLLAMA_URL=http://127.0.0.1:11434
SPEAKLAB_OLLAMA_MODEL=qwen3.5:9b-q4_K_M
SPEAKLAB_OLLAMA_CONTEXT=8192
SPEAKLAB_OLLAMA_MAX_OUTPUT=2048
SPEAKLAB_WHISPER_URL=http://127.0.0.1:8080
SPEAKLAB_MODEL_TIMEOUT=240
SPEAKLAB_SERVE_FRONTEND=true
SPEAKLAB_SERVER_NAME=${server_name}
ENV
fi
cat > /etc/systemd/system/speaklab-ollama.service <<'UNIT'
[Unit]
Description=SpeakLab local Ollama model server
After=network-online.target
[Service]
User=ollama
Group=ollama
ExecStart=/usr/local/bin/ollama serve
Environment=OLLAMA_HOST=127.0.0.1:11434
Environment=OLLAMA_MODELS=/var/lib/ollama/models
Environment=OLLAMA_NO_CLOUD=1
Environment=OLLAMA_NUM_PARALLEL=1
Environment=OLLAMA_MAX_LOADED_MODELS=1
Environment=OLLAMA_CONTEXT_LENGTH=8192
Environment=OLLAMA_FLASH_ATTENTION=1
Environment=OLLAMA_KV_CACHE_TYPE=q8_0
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/speaklab-whisper.service <<'UNIT'
[Unit]
Description=SpeakLab local Whisper transcription
After=network.target
[Service]
User=speaklab
Group=speaklab
ExecStart=/opt/whisper.cpp/build/bin/whisper-server -m /var/lib/speaklab-models/ggml-small.en.bin --host 127.0.0.1 --port 8080 -t 4
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/speaklab.service <<'UNIT'
[Unit]
Description=SpeakLab application
After=network.target speaklab-ollama.service speaklab-whisper.service
[Service]
User=speaklab
Group=speaklab
WorkingDirectory=/opt/speaklab
ExecStart=/opt/speaklab/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5
UMask=0077
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now speaklab-ollama speaklab-whisper speaklab
for attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null; then break; fi
  sleep 1
done
ollama pull qwen3.5:9b-q4_K_M
systemctl --no-pager --full status speaklab speaklab-ollama speaklab-whisper
curl -fsS http://127.0.0.1:8765/api/health
