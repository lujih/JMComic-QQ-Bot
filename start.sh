#!/bin/bash
# 不使用 set -e：后台进程和循环并存时意外退出风险高，显式错误处理
set -u

# 优雅关闭：收到 SIGTERM 后先停前台进程，再清理后台任务
trap 'echo "[start] Caught signal, shutting down..."; kill $(jobs -p) 2>/dev/null; exit 0' TERM INT QUIT HUP

# 0. Convenience symlinks for the base image layout
NAPCAT_DIR=/app/napcat
NAPCAT_CONFIG=$NAPCAT_DIR/config
mkdir -p "$NAPCAT_CONFIG"

# 0a. WebUI token：环境变量 > /data 里已存的 > 新随机生成。
# 为什么要随机：WebUI 绑 0.0.0.0:7860，HF Spaces 默认把 public 端口直出，而 token 是
# 管理 API 的唯一鉴权闸门，写死的公开常量等于把 QQ 账号管理权对全网公开。
# 为什么存到 /data：每次重启都换新 token 会让「要进 WebUI 就得先去翻日志」，旧 token
# 立刻作废，实测中这是个很烦的运维退化。存在桶里既跨重启稳定，又不等于任何公开常量。
WEBUI_TOKEN_FILE=/data/webui_token
WEBUI_TOKEN="${WEBUI_TOKEN:-}"
if [ -z "$WEBUI_TOKEN" ] && [ -s "$WEBUI_TOKEN_FILE" ]; then
    WEBUI_TOKEN="$(cat "$WEBUI_TOKEN_FILE")"
    echo "[start] Reusing WebUI token from $WEBUI_TOKEN_FILE"
fi
if [ -z "$WEBUI_TOKEN" ]; then
    WEBUI_TOKEN="$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 24)"
    echo "[start] Generated a new WebUI token"
    # 存盘失败（未挂 bucket）不影响启动，只是下次重启会换新 token
    { echo "$WEBUI_TOKEN" > "$WEBUI_TOKEN_FILE"; } 2>/dev/null \
        || echo "[start] WARNING: cannot persist WebUI token to $WEBUI_TOKEN_FILE (bucket not mounted?)" >&2
fi

# 1. Write NapCat WebUI config — port 7860 for HF Spaces
# autoLoginAccount 是 NapCat ≥4.18.15 的原生自动登录配置项（commit 31c45bf）。
# 上游 resolveAutoLoginAccount(env ACCOUNT, 配置项, lastLoginAccount) 取第一个非空，
# 所以写它等价于把 ACCOUNT 变量透传给 WebUI 后端；留空则回退到 NapCat 自己记住的
# lastLoginAccount（它会在扫码登录成功后自行写入本文件）。
# 注意：本文件每次启动都会被覆写，lastLoginAccount 因此在跨容器场景下必然为空——
# 要免扫码必须靠 ACCOUNT 变量。
echo "[start] Writing NapCat WebUI config (port 7860)..."
cat > "$NAPCAT_CONFIG/webui.json" << EOF
{
    "host": "0.0.0.0",
    "port": 7860,
    "token": "${WEBUI_TOKEN}",
    "loginRate": 3,
    "autoLoginAccount": "${ACCOUNT:-}"
}
EOF
# 打印一次；HF Space 日志仅所有者可见，扫码登录时需要它
echo "[start] NapCat WebUI token: ${WEBUI_TOKEN}"
# Token 已写入配置文件，从环境变量中移除，减少子进程暴露面
# ONEBOT 侧：NoneBot 适配器读 ONEBOT_ACCESS_TOKEN，NapCat 配置注入同一值；先备份再 unset
unset WEBUI_TOKEN
unset WEBUI_TOKEN_FILE
ONEBOT_TOKEN_BACKUP="${ONEBOT_ACCESS_TOKEN:-${ONEBOT_TOKEN:-}}"
unset ONEBOT_TOKEN
unset ONEBOT_ACCESS_TOKEN
export ONEBOT_TOKEN_BACKUP

# 2. NapCat Shell 已在 Dockerfile 构建时解压，如有缺失则运行时补充
if [ ! -f "$NAPCAT_DIR/napcat.mjs" ]; then
    echo "[start] NapCat Shell not found at build time, unpacking now..."
    unzip -q /app/NapCat.Shell.zip -d /tmp/NapCat.Shell 2>/dev/null && \
        cp -rf /tmp/NapCat.Shell/* "$NAPCAT_DIR/" && \
        rm -rf /tmp/NapCat.Shell || echo "[start] WARNING: failed to unpack NapCat.Shell.zip"
fi

# 3. Write NapCat OneBot config — WS client → our NoneBot2
echo "[start] Writing NapCat OneBot config..."
cp /app/bot/config/onebot11.json "$NAPCAT_CONFIG/onebot11.json" || { echo "[start] FATAL: failed to copy onebot11.json"; exit 1; }
# 注入 OneBot token（使用 json.dumps 安全写入，避免 token 含特殊字符破坏 JSON）
python3 -c "
import os, json
path = '$NAPCAT_CONFIG/onebot11.json'
with open(path, 'r') as f:
    data = json.load(f)
data['network']['websocketClients'][0]['token'] = os.environ.get('ONEBOT_TOKEN_BACKUP', '')
with open(path, 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
"
chown -R napcat:napcat "$NAPCAT_DIR" 2>/dev/null || { echo "[start] WARNING: chown for napcat user failed" >&2; }

# 3a. Ensure temp dirs exist and are writable by napcat user
mkdir -p /app/.config/QQ/NapCat/temp
mkdir -p /app/.cache
chown -R napcat:napcat /app/.config/QQ /app/.cache 2>/dev/null || { echo "[start] WARNING: chown for /app/.config/QQ or /app/.cache failed" >&2; }

# 4. Anti-detection (from upstream napcat-docker entrypoint)
# 在 HF Spaces 非特权容器中 mount --bind 不可用，跳过反检测相关操作
rm -rf "/tmp/.X1-lock"
rm -f "/.dockerenv" "/.dockerinit" "/run/.containerenv" "/run/systemd/container"
rm -f "/dev/.dockerenv" "/run/systemd/container"

# 5. Background: monitor QQ login and sync onebot11 config per account
sync_onebot11_config() {
    while true; do
        sleep 30
        for d in /app/.config/QQ/*/; do
            [ -d "$d" ] || continue
            [ -f "${d}nt_qq.db" ] || continue
            qq=$(basename "$d")
            target="$NAPCAT_CONFIG/onebot11_${qq}.json"
            if [ ! -f "$target" ]; then
                cp /app/bot/config/onebot11.json "$target"
                # 注入 OneBot token
                python3 -c "
import os, json
path = '$target'
with open(path, 'r') as f:
    data = json.load(f)
data['network']['websocketClients'][0]['token'] = os.environ.get('ONEBOT_TOKEN_BACKUP', '')
with open(path, 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
"
                chown napcat:napcat "$target" 2>/dev/null || { echo "[start] WARNING: chown for onebot11 config failed" >&2; }
                echo "[start] Synced onebot11 config for account $qq"
            fi
        done
    done
}
sync_onebot11_config &

# 6. Start Xvfb (virtual display)
echo "[start] Starting Xvfb..."
Xvfb :1 -screen 0 1280x768x16 +extension GLX +render > /dev/null 2>&1 &
for i in 1 2 3 4 5; do
    if pgrep -x Xvfb > /dev/null 2>&1; then
        break
    fi
    sleep 1
done
if ! pgrep -x Xvfb > /dev/null 2>&1; then
    echo "[start] WARNING: Xvfb may not have started"
fi
export DISPLAY=:1

# 7. Start QQ + NapCat in background (auto-restart on crash)
echo "[start] Starting QQ + NapCat..."
mkdir -p /app/logs
cd "$NAPCAT_DIR"
start_qq() {
    crash_count=0
    while true; do
        if [ -n "${ACCOUNT:-}" ]; then
            gosu napcat /opt/QQ/qq --no-sandbox -q "$ACCOUNT" > /app/logs/qq.log 2>&1 &
        else
            gosu napcat /opt/QQ/qq --no-sandbox > /app/logs/qq.log 2>&1 &
        fi
        pid=$!
        echo $pid > /tmp/qq.pid
        wait $pid || true
        crash_count=$((crash_count + 1))
        echo "[start] QQ/NapCat exited (crash #$crash_count), restarting in 10s..."
        tail -n 20 /app/logs/qq.log 2>/dev/null || true
        if [ "$crash_count" -ge 5 ]; then
            echo "[start] WARNING: QQ 连续崩溃 $crash_count 次，请检查日志 /app/logs/qq.log"
        fi
        sleep 10
    done
}
start_qq &
cd /app/bot

# 8. Start NoneBot2 (foreground — keeps container alive)
echo "[start] Starting NoneBot2..."
export PYTHONUNBUFFERED=1
# NoneBot onebot 适配器读取 ONEBOT_ACCESS_TOKEN 校验 WS 连接；仅 bot 进程恢复（NapCat/QQ 不暴露）
export ONEBOT_ACCESS_TOKEN="$ONEBOT_TOKEN_BACKUP"
gosu napcat python bot.py

# 10. Cleanup on exit
echo "[start] NoneBot2 exited, stopping..."
kill $(jobs -p) 2>/dev/null || true
if [ -f /tmp/qq.pid ]; then
    kill $(cat /tmp/qq.pid) 2>/dev/null || true
fi
