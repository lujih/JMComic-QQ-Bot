#!/bin/bash
set -e

GCQ_DIR="/app/go-cqhttp"
GCQ_BIN="$GCQ_DIR/go-cqhttp"
GCQ_CONFIG="$GCQ_DIR/config.yml"
GCQ_DEVICE="$GCQ_DIR/device.json"
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

# ---------- 2. generate config ----------
if [ ! -f "$GCQ_CONFIG" ]; then
    echo "[start] Creating go-cqhttp config..."
    cat > "$GCQ_CONFIG" << 'GCQ_EOF'
account:
  uin: 0
  password: ''
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

# ---------- 3. ensure device.json uses protocol 1 (Android Phone, supports QR) ----------
if [ ! -f "$GCQ_DEVICE" ]; then
    echo "[start] Generating device.json with protocol 1..."
    # run briefly to auto-generate device.json, then kill it
    cd "$GCQ_DIR"
    timeout 10 "$GCQ_BIN" -c config.yml 2>/dev/null || true
    cd /app
fi

if [ -f "$GCQ_DEVICE" ]; then
    python -c "
import json
p = '$GCQ_DEVICE'
d = json.loads(open(p).read())
changed = False
if d.get('protocol') != 1:
    d['protocol'] = 1
    changed = True
if changed:
    json.dump(d, open(p, 'w'), indent=2)
    print('[start] device.json: protocol set to 1 (Android Phone)')
else:
    print('[start] device.json: protocol already 1')
"
fi

# ---------- 4. start go-cqhttp background ----------
echo "[start] Starting go-cqhttp..."
cd "$GCQ_DIR"
"$GCQ_BIN" -c config.yml &
GCQ_PID=$!
cd /app

# ---------- 5. start health server ----------
python health.py &
HEALTH_PID=$!

# ---------- 6. wait for ready ----------
echo "[start] Waiting for go-cqhttp..."
for i in $(seq 1 60); do
    if [ -f "$SESSION_FILE" ]; then
        echo "[start] go-cqhttp ready"
        break
    fi
    if [ -f "$QR_FILE" ]; then
        : # QR generated, keep waiting for session
    fi
    sleep 2
done

echo "[start] Starting NoneBot2..."
python bot.py

kill $GCQ_PID 2>/dev/null || true
kill $HEALTH_PID 2>/dev/null || true
