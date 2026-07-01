#!/bin/bash
set -e

# 0. Convenience symlinks for the base image layout
NAPCAT_DIR=/app/napcat
NAPCAT_CONFIG=$NAPCAT_DIR/config
mkdir -p "$NAPCAT_CONFIG"

# 0a. Generate random WebUI token if not set
if [ -z "${WEBUI_TOKEN}" ]; then
    WEBUI_TOKEN=$(openssl rand -hex 16)
    echo "[start] Generated random WebUI token: ${WEBUI_TOKEN}"
fi

# 1. Write NapCat WebUI config — port 7860 for HF Spaces
echo "[start] Writing NapCat WebUI config (port 7860)..."
cat > "$NAPCAT_CONFIG/webui.json" << EOF
{
    "host": "0.0.0.0",
    "port": 7860,
    "token": "${WEBUI_TOKEN:-jmcomic}",
    "loginRate": 3
}
EOF

# 2. Unpack NapCat Shell (if not yet done — base image skips this at build)
if [ ! -f "$NAPCAT_DIR/napcat.mjs" ]; then
    echo "[start] Unpacking NapCat.Shell.zip..."
    unzip -q /app/NapCat.Shell.zip -d /tmp/NapCat.Shell
    cp -rf /tmp/NapCat.Shell/* "$NAPCAT_DIR/"
    # Copy default configs for missing ones
    if [ ! -f "$NAPCAT_CONFIG/napcat.json" ] && [ -d "/tmp/NapCat.Shell/config" ]; then
        cp -rf /tmp/NapCat.Shell/config/* "$NAPCAT_CONFIG/"
    fi
    rm -rf /tmp/NapCat.Shell
fi

# 3. Write NapCat OneBot config — WS client → our NoneBot2
echo "[start] Writing NapCat OneBot config..."
cp /app/bot/config/onebot11.json "$NAPCAT_CONFIG/onebot11.json"
# 注入 OneBot token（空值时替换为空字符串，避免残留占位符）
python3 -c "
import os, sys
path = '$NAPCAT_CONFIG/onebot11.json'
data = open(path).read()
data = data.replace('\${ONEBOT_TOKEN}', os.environ.get('ONEBOT_TOKEN', ''))
open(path, 'w').write(data)
"
chown -R napcat:napcat "$NAPCAT_DIR" 2>/dev/null || true

# 3a. Ensure temp dirs exist and are writable by napcat user
mkdir -p /app/.config/QQ/NapCat/temp
mkdir -p /app/.cache
chown -R napcat:napcat /app/.config/QQ /app/.cache 2>/dev/null || true

# 4. Anti-detection (from upstream napcat-docker entrypoint)
# 在 HF Spaces 非特权容器中 mount --bind 不可用，跳过反检测相关操作
rm -rf "/tmp/.X1-lock"
rm -f "/.dockerenv" "/.dockerinit" "/run/.containerenv" "/run/systemd/container"
rm -f "/dev/.dockerenv" "/run/systemd/container"

# 5. Background: monitor QQ login and sync onebot11 config per account
sync_onebot11_config() {
    while true; do
        sleep 10
        for d in /app/.config/QQ/*/; do
            [ -d "$d" ] || continue
            [ -f "${d}nt_qq.db" ] || continue
            qq=$(basename "$d")
            target="$NAPCAT_CONFIG/onebot11_${qq}.json"
            if [ ! -f "$target" ]; then
                cp /app/bot/config/onebot11.json "$target"
                # 注入 OneBot token（空值时替换为空字符串，避免残留占位符）
                python3 -c "
import os
path = '$target'
data = open(path).read()
data = data.replace('\${ONEBOT_TOKEN}', os.environ.get('ONEBOT_TOKEN', ''))
open(path, 'w').write(data)
"
                chown napcat:napcat "$target" 2>/dev/null || true
                echo "[start] Synced onebot11 config for account $qq"
            fi
        done
    done
}
sync_onebot11_config &

# 6. Start Xvfb (virtual display)
echo "[start] Starting Xvfb..."
Xvfb :1 -screen 0 1280x768x16 +extension GLX +render > /dev/null 2>&1 &
sleep 1
export DISPLAY=:1

# 7. Start QQ + NapCat in background (auto-restart on crash)
echo "[start] Starting QQ + NapCat..."
cd "$NAPCAT_DIR"
start_qq() {
    while true; do
        if [ -n "${ACCOUNT}" ]; then
            gosu napcat /opt/QQ/qq --no-sandbox -q "$ACCOUNT" &
        else
            gosu napcat /opt/QQ/qq --no-sandbox &
        fi
        pid=$!
        echo $pid > /tmp/qq.pid
        wait $pid || true
        echo "[start] QQ/NapCat exited, restarting in 10s..."
        sleep 10
    done
}
start_qq &
cd /app/bot

# 8. Wait for NapCat WebUI to be ready
echo "[start] Waiting for NapCat WebUI on port 7860..."
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:7860 > /dev/null 2>&1; then
        echo "" && echo "[start] NapCat WebUI ready"
        break
    fi
    printf "."
    sleep 2
done
if ! curl -sf http://127.0.0.1:7860 > /dev/null 2>&1; then
    echo " [start] NapCat WebUI not ready after 60s, continuing..."
fi

# 9. Start NoneBot2 (foreground — keeps container alive)
echo "[start] Starting NoneBot2..."
export PYTHONUNBUFFERED=1
python bot.py

# 10. Cleanup on exit
echo "[start] NoneBot2 exited, stopping..."
if [ -f /tmp/qq.pid ]; then
    kill $(cat /tmp/qq.pid) 2>/dev/null || true
fi
