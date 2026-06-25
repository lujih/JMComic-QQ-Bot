#!/bin/bash
set -e

# 0. Convenience symlinks for the base image layout
NAPCAT_DIR=/app/napcat
NAPCAT_CONFIG=$NAPCAT_DIR/config
mkdir -p "$NAPCAT_CONFIG"

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
    rm -rf /tmp/NapCat.Shell
fi

if [ ! -f "$NAPCAT_CONFIG/napcat.json" ]; then
    echo "[start] Copying default NapCat configs..."
    unzip -q /app/NapCat.Shell.zip -d /tmp/NapCat.Shell
    cp -rf /tmp/NapCat.Shell/config/* "$NAPCAT_CONFIG/"
    rm -rf /tmp/NapCat.Shell
fi

# 3. Write NapCat OneBot config — WS client → our NoneBot2
echo "[start] Writing NapCat OneBot config..."
cp /app/bot/config/onebot11.json "$NAPCAT_CONFIG/onebot11.json"
# 注入 OneBot token（非空时替换）
if [ -n "${ONEBOT_TOKEN}" ]; then
    sed -i "s/\${ONEBOT_TOKEN}/${ONEBOT_TOKEN}/g" "$NAPCAT_CONFIG/onebot11.json"
fi
chown -R napcat:napcat "$NAPCAT_DIR" 2>/dev/null || true

# 3a. Ensure NapCat temp dir exists and is writable by napcat user
mkdir -p /app/.config/QQ/NapCat/temp
chown -R napcat:napcat /app/.config/QQ 2>/dev/null || true

# 4. Anti-detection (from upstream napcat-docker entrypoint)
rm -rf "/tmp/.X1-lock"
rm -f "/.dockerenv" "/.dockerinit" "/run/.containerenv" "/run/systemd/container"
rm -f "/dev/.dockerenv" "/run/systemd/container"

HNAME=$(hostname)
if [[ "$HNAME" == *docker* || "$HNAME" == *container* || "$HNAME" == *lxc* ]] \
   || [[ "$HNAME" =~ ^[a-f0-9]{12,}$ ]]; then
    hostname localhost
    echo localhost > /etc/hostname
fi

mkdir -p /tmp/fake_cgroup
FAKE=/tmp/fake_cgroup

for f in /proc/self/cgroup /proc/1/cgroup; do
    [ -f "$f" ] || continue
    n=$(echo "$f" | tr '/' '_')
    sed 's|/docker/|/system.slice/|g; s|/lxc/|/system.slice/|g; s|/kubepods/|/system.slice/|g; s|/containerd/|/system.slice/|g; s|/buildkit/|/system.slice/|g' \
        "$f" > "$FAKE/$n"
    mount --bind "$FAKE/$n" "$f" 2>/dev/null || true
done

# Hide Docker socket
[ -S /var/run/docker.sock ] && mv /var/run/docker.sock /var/run/.docker.sock.hidden 2>/dev/null || true

# Mask mountinfo
for f in /proc/self/mountinfo /proc/1/mountinfo; do
    [ -f "$f" ] || continue
    n=$(echo "$f" | tr '/' '_')
    sed '/docker/d; /containerd/d; /\.dockerenv/d' "$f" > "$FAKE/$n"
    mount --bind "$FAKE/$n" "$f" 2>/dev/null || true
done

if [ -f /proc/1/cmdline ]; then
    printf '/sbin/init\0' > "$FAKE/cmdline_1"
    mount --bind "$FAKE/cmdline_1" /proc/1/cmdline 2>/dev/null || true
fi

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
                # 注入 OneBot token（非空时替换）
                if [ -n "${ONEBOT_TOKEN}" ]; then
                    sed -i "s/\${ONEBOT_TOKEN}/${ONEBOT_TOKEN}/g" "$target"
                fi
                chown napcat:napcat "$target" 2>/dev/null || true
                echo "[start] Synced onebot11 config for account $qq"
            fi
        done
    done
}
sync_onebot11_config &

# 6. Start Xvfb (virtual display)
echo "[start] Starting Xvfb..."
Xvfb :1 -screen 0 1080x760x16 +extension GLX +render > /dev/null 2>&1 &
sleep 1
export DISPLAY=:1

# 7. Start QQ + NapCat in background
echo "[start] Starting QQ + NapCat..."
cd "$NAPCAT_DIR"
if [ -n "${ACCOUNT}" ]; then
    gosu napcat /opt/QQ/qq --no-sandbox -q "$ACCOUNT" &
else
    gosu napcat /opt/QQ/qq --no-sandbox &
fi
QQ_PID=$!
cd /app/bot

# 8. Wait for NapCat WebUI to be ready
echo "[start] Waiting for NapCat WebUI on port 7860..."
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:7860 > /dev/null 2>&1; then
        echo "[start] NapCat WebUI ready"
        break
    fi
    sleep 2
done

# 9. Start NoneBot2 (foreground — keeps container alive)
echo "[start] Starting NoneBot2..."
python bot.py

# 10. Cleanup on exit
echo "[start] NoneBot2 exited, stopping..."
kill $QQ_PID 2>/dev/null || true
