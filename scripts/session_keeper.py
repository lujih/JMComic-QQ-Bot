#!/usr/bin/env python3
"""QQ 登录会话持久化 + 掉线自愈(配合 HF Storage Buckets 使用)。

子命令:
  restore  容器启动早期、拉起 QQ 前,从快照恢复 /app/.config/QQ 登录数据
  backup   登录数据有变化时打包快照到挂载卷(由 start.sh 循环调用,单次执行)
  watch    前台常驻:轮询 NapCat WebUI 登录状态,掉线时自动快速登录

快照只做存取,Q 工作目录始终在本地磁盘 —— 避免 SQLite(nt_qq.db)直接跑在
对象存储 FUSE 挂载上。仅依赖标准库。
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import time
import urllib.request

EXCLUDE_DIRS = {"log", "logs", "cache", "Cache", "CodeCache", "GPUCache", "Crashpad", "temp", "tmp",
                "nt_data"}


def log(msg):
    print(f"[session] {msg}", flush=True)


def describe_mount(mount_dir):
    """区分「未配置 Volume Mount」「已挂载但为空」「不可读」三种状态,便于排查 bucket 空问题。"""
    if not os.path.exists(mount_dir):
        return "挂载点不存在(未配置 Volume Mount)"
    if not os.path.isdir(mount_dir):
        return "挂载点不是目录"
    try:
        n = len(os.listdir(mount_dir))
    except OSError as e:
        return f"挂载点不可读: {e}"
    if n == 0:
        return "已挂载但为空"
    return f"挂载正常({n} 个条目)"


def has_login_data(qq_dir):
    """判定 qq_dir 是否含 NTQQ 登录数据。

    真实布局(NapCat 源码 + Issue #886 实测):账号级数据在 nt_qq_<hash>/ 目录
    (内含 nt_qq/nt_db/ 数据库),仅登录过才会出现;裸 nt_qq/(全局配置)QQ 启动
    即创建,不能作为登录证据。nt_qq.db 文件判据仅作历史兜底。
    """
    if not os.path.isdir(qq_dir):
        return False
    try:
        for entry in os.scandir(qq_dir):
            if entry.is_dir() and entry.name.startswith("nt_qq_"):
                return True
    except OSError:
        return False
    if os.path.isfile(os.path.join(qq_dir, "nt_qq.db")):
        return True
    for entry in os.scandir(qq_dir):
        if entry.is_dir() and os.path.isfile(os.path.join(entry.path, "nt_qq.db")):
            return True
    return False


def _tar_filter(tarinfo):
    parts = tarinfo.name.split("/")
    if any(p in EXCLUDE_DIRS for p in parts):
        return None
    return tarinfo


def cmd_restore(args):
    snap, qq_dir = args.snapshot, args.qq_dir
    if not os.path.isfile(snap):
        log(f"无会话快照({snap});{describe_mount(os.path.dirname(snap) or '/')},按首次部署处理")
        return 0
    tmp = qq_dir + ".restore_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        with tarfile.open(snap, "r:gz") as tf:
            members = [m for m in tf.getmembers()
                       if not m.name.startswith("/") and ".." not in m.name.split("/")]
            tf.extractall(tmp, members=members)
    except Exception as e:
        log(f"快照解压失败(可能损坏),放弃恢复: {e}")
        shutil.rmtree(tmp, ignore_errors=True)
        return 1
    if not has_login_data(tmp):
        log("快照中无账号登录数据(nt_qq_*),放弃恢复")
        shutil.rmtree(tmp, ignore_errors=True)
        return 1
    old = qq_dir + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.isdir(qq_dir):
        os.rename(qq_dir, old)
    os.rename(tmp, qq_dir)
    shutil.rmtree(old, ignore_errors=True)
    log("已从快照恢复 QQ 登录数据,NapCat 可尝试快速登录")
    return 0


def _changed_since(qq_dir, base_mtime):
    for root, dirs, files in os.walk(qq_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            p = os.path.join(root, f)
            try:
                if os.path.getmtime(p) > base_mtime:
                    return True
            except OSError:
                continue
    return False


def cmd_backup(args):
    snap, qq_dir = args.snapshot, args.qq_dir
    if not os.path.isdir(os.path.dirname(snap)):
        log(f"快照挂载不可用({snap}):{describe_mount(os.path.dirname(snap))},跳过备份")
        return 0
    if not has_login_data(qq_dir):
        return 0
    base_mtime = os.path.getmtime(snap) if os.path.isfile(snap) else -1.0
    if base_mtime > 0 and not _changed_since(qq_dir, base_mtime):
        return 0
    tmp = snap + ".tmp"
    try:
        with tarfile.open(tmp, "w:gz") as tf:
            tf.add(qq_dir, arcname=".", filter=_tar_filter)
        os.replace(tmp, snap)
        log(f"已备份会话快照({os.path.getsize(snap) // 1024} KB)")
    except Exception as e:
        log(f"备份失败: {e}")
        try:
            os.remove(tmp)
        except OSError:
            pass
    return 0


def _read_webui_token(config_path):
    try:
        with open(config_path, encoding="utf-8") as f:
            return json.load(f).get("token", "")
    except Exception:
        return ""


def _credential(base, token):
    h = hashlib.sha256((token + ".napcat").encode()).hexdigest()
    req = urllib.request.Request(
        base + "/api/auth/login",
        data=json.dumps({"hash": h}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        body = json.load(r)
    cred = (body.get("data") or {}).get("Credential")
    if not cred:
        raise RuntimeError(f"WebUI login failed: {body}")
    return cred


def _api_post(base, cred, path, payload=None):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload or {}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + cred,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def cmd_watch(args):
    account = args.account or ""
    if not account:
        log("未配置 ACCOUNT 环境变量,登录 watchdog 不启用")
        return 0
    token = _read_webui_token(args.config)
    if not token:
        log(f"无法读取 WebUI token({args.config}),登录 watchdog 不启用")
        return 0
    base = args.webui.rstrip("/")
    log(f"登录 watchdog 启动(interval={args.interval}s, grace={args.grace}s)")
    grace_until = time.time() + args.grace
    fail_streak = 0
    attempts = 0
    while True:
        time.sleep(args.interval)
        try:
            cred = _credential(base, token)
            body = _api_post(base, cred, "/api/QQLogin/CheckLoginStatus")
            status = body.get("data") or {}
        except Exception as e:
            log(f"WebUI 尚未就绪或查询失败,本轮跳过: {e}")
            continue
        if status.get("isLogin"):
            if fail_streak or attempts:
                log("QQ 在线,watchdog 恢复监控")
            fail_streak = 0
            attempts = 0
            continue
        if time.time() < grace_until:
            continue
        fail_streak += 1
        if fail_streak < args.threshold:
            log(f"QQ 未登录({fail_streak}/{args.threshold}),继续观察")
            continue
        if attempts >= args.max_attempts:
            log(f"⚠️ 快速登录已连续尝试 {attempts} 次仍未上线,疑似触发风控需要人工验证,"
                f"请打开 WebUI 扫码:{base}(扫码成功后新会话会自动进入备份)")
            return 1
        if attempts == 0 and not has_login_data(args.qq_dir):
            log(f"本地无账号登录数据(nt_qq_* 缺失于 {args.qq_dir}),快速登录不可用,"
                f"请打开 WebUI 扫码:{base}(扫码成功后新会话会自动进入备份)")
            return 1
        attempts += 1
        try:
            _api_post(base, cred, "/api/QQLogin/SetQuickLogin", {"uin": account})
            log(f"检测到掉线,已发起快速登录(account={account},第 {attempts}/{args.max_attempts} 次)")
        except Exception as e:
            log(f"快速登录请求失败: {e}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("restore")
    p.add_argument("--qq-dir", required=True)
    p.add_argument("--snapshot", required=True)
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("backup")
    p.add_argument("--qq-dir", required=True)
    p.add_argument("--snapshot", required=True)
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("watch")
    p.add_argument("--webui", default="http://127.0.0.1:7860")
    p.add_argument("--config", default="/app/napcat/config/webui.json")
    p.add_argument("--qq-dir", default="/app/.config/QQ")
    p.add_argument("--account", default=os.getenv("ACCOUNT", ""))
    p.add_argument("--interval", type=int, default=120)
    p.add_argument("--grace", type=int, default=300)
    p.add_argument("--threshold", type=int, default=2)
    p.add_argument("--max-attempts", type=int, default=12)
    p.set_defaults(func=cmd_watch)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
