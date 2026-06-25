#!/bin/bash
set -e

LAGRANGE_DIR="/app/lagrange"
LAGRANGE_CONFIG="$LAGRANGE_DIR/appsettings.json"
QR_FILE="$LAGRANGE_DIR/qr.png"
SIGN_FILE="$LAGRANGE_DIR/keystore.json"

mkdir -p "$LAGRANGE_DIR"

# ---------- 1. download lagrange binary ----------
python download_lagrange.py

LAGRANGE_BIN=$(find "$LAGRANGE_DIR" -name "Lagrange.OneBot" -type f | head -1)
if [ -z "$LAGRANGE_BIN" ]; then
    echo "[start] Lagrange.OneBot binary not found!"
    exit 1
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
export DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1
cd "$LAGRANGE_DIR"
"$LAGRANGE_BIN" &
LAG_PID=$!
cd /app

# ---------- 5. start health server background ----------
python health.py &
HEALTH_PID=$!

# ---------- 6. wait for lagrange ready then start nonebot ----------
echo "[start] Waiting for Lagrange to be ready..."
for i in $(seq 1 30); do
    if [ -f "$SIGN_FILE" ]; then
        echo "[start] Lagrange ready (keystore found)"
        break
    fi
    if [ -f "$QR_FILE" ]; then
        echo "[start] QR code generated, waiting for scan..."
    fi
    sleep 2
done

echo "[start] Starting NoneBot2..."
python bot.py

# ---------- 7. cleanup ----------
kill $LAG_PID 2>/dev/null || true
kill $HEALTH_PID 2>/dev/null || true
