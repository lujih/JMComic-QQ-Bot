#!/bin/bash
set -e

GCQ_DIR="/app/go-cqhttp"
GCQ_BIN="$GCQ_DIR/go-cqhttp"
GCQ_CONFIG="$GCQ_DIR/config.yml"
QR_FILE="$GCQ_DIR/qrcode.png"
SESSION_FILE="$GCQ_DIR/session.token"

mkdir -p "$GCQ_DIR"

# ---------- 1. download go-cqhttp ----------
if [ ! -f "$GCQ_BIN" ]; then
    echo "[start] Downloading go-cqhttp..."
    curl -sL "https://github.com/Mrs4s/go-cqhttp/releases/download/v1.2.0/go-cqhttp_linux_amd64.tar.gz" \
        -o /tmp/gcq.tar.gz
    tar -xzf /tmp/gcq.tar.gz -C "$GCQ_DIR"
    rm /tmp/gcq.tar.gz
    chmod +x "$GCQ_BIN" 2>/dev/null || true
fi

# ---------- 2. generate config if not exists ----------
if [ ! -f "$GCQ_CONFIG" ]; then
    echo "[start] Creating go-cqhttp config..."
    cat > "$GCQ_CONFIG" << 'GCQ_EOF'
account:
  uin: 0
  password: ''
  protocol: 1
  encrypt: false
  status: 0
  max-relogin-times: 0
  relogin-delay: 3

heartbeat:
  interval: 5

message:
  post-format: array
  report-self-message: false

output:
  log-level: info
  log-force-new: true
  log-colorful: false

servers:
  - ws:
      host: 127.0.0.1
      port: 8082
GCQ_EOF
fi

# ---------- 3. start go-cqhttp background ----------
echo "[start] Starting go-cqhttp..."
cd "$GCQ_DIR"
"$GCQ_BIN" -c config.yml &
GCQ_PID=$!
cd /app

# ---------- 4. start health server ----------
python health.py &
HEALTH_PID=$!

# ---------- 5. wait for ready ----------
echo "[start] Waiting for go-cqhttp..."
for i in $(seq 1 30); do
    if [ -f "$SESSION_FILE" ]; then
        echo "[start] go-cqhttp ready"
        break
    fi
    sleep 2
done

echo "[start] Starting NoneBot2..."
python bot.py

kill $GCQ_PID 2>/dev/null || true
kill $HEALTH_PID 2>/dev/null || true
