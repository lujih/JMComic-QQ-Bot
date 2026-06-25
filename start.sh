#!/bin/bash
set -e

LAGRANGE_DIR="/app/lagrange"
LAGRANGE_BIN="$LAGRANGE_DIR/Lagrange.OneBot"
LAGRANGE_CONFIG="$LAGRANGE_DIR/config.json"
QR_FILE="$LAGRANGE_DIR/qr.png"
SIGN_FILE="$LAGRANGE_DIR/keystore.json"

mkdir -p "$LAGRANGE_DIR"

# ---------- 1. download lagrange binary ----------
if [ ! -f "$LAGRANGE_BIN" ]; then
    echo "[start] Downloading Lagrange.OneBot..."
    LAG_TAG=$(curl -sL https://api.github.com/repos/LagrangeDev/Lagrange.Core/releases/latest \
        | grep tag_name | head -1 | cut -d'"' -f4)
    if [ -z "$LAG_TAG" ]; then
        LAG_TAG="v0.4.0"
    fi
    curl -sL "https://github.com/LagrangeDev/Lagrange.Core/releases/download/${LAG_TAG}/Lagrange.OneBot-linux-x64" \
        -o "$LAGRANGE_BIN"
    chmod +x "$LAGRANGE_BIN"
fi

# ---------- 2. generate config if not exists ----------
if [ ! -f "$LAGRANGE_CONFIG" ]; then
    echo "[start] Creating Lagrange config..."
    cat > "$LAGRANGE_CONFIG" << 'LAG_EOF'
{
  "Account": {
    "Uin": 0,
    "Password": ""
  },
  "SignServerUrl": "https://sign.lagrange.onebot.dev/",
  "Implementations": [
    {
      "Type": "ForwardWebSocket",
      "Host": "127.0.0.1",
      "Port": 8082,
      "Suffix": "/ws"
    }
  ]
}
LAG_EOF
fi

# ---------- 3. clean stale qr ----------
rm -f "$QR_FILE"

# ---------- 4. start lagrange background ----------
echo "[start] Starting Lagrange.OneBot..."
cd "$LAGRANGE_DIR"
"$LAGRANGE_BIN" --config "$LAGRANGE_CONFIG" &
LAG_PID=$!
cd /app

# ---------- 5. start health server background ----------
python health.py &
HEALTH_PID=$!

# ---------- 6. wait for lagrange ready then start nonebot ----------
echo "[start] Waiting for Lagrange to be ready..."
for i in $(seq 1 30); do
    if [ -f "$SIGN_FILE" ]; then
        break
    fi
    sleep 2
done
echo "[start] Starting NoneBot2..."
python bot.py

# ---------- 7. cleanup ----------
kill $LAG_PID 2>/dev/null || true
kill $HEALTH_PID 2>/dev/null || true
