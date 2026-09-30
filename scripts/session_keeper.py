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


def _is_link(tarinfo):
    """链接类成员：符号链接、硬链接、设备、FIFO、socket。

    restore 以容器 root 跑在 QQ 拉起之前，成员过滤原本只查「绝对路径 / 含 ..」，
    不拦链接：构造一个先放 `x -> /app/bot/start.sh` 符号链接、再放同名普通文件 `x`
    的 tar，tarfile 会先建链接再顺着它写入，落成容器内任意路径的 root 写。
    快照是自己打自己解的（backup 只用 tf.add），本来就不含链接，直接丢弃即可。
    """
    return (tarinfo.issym() or tarinfo.islnk() or tarinfo.ischr()
            or tarinfo.isblk() or tarinfo.isfifo() or tarinfo.isdev())


def _drain_dir(src, dst):
    """把 src 目录下的**内容**（不是 src 本身）挪到 dst，返回挪走的条目名。

    为什么不能用 rename 搬运条目——HF Space 的实测会连撞两种错误：
      1. EBUSY(16) Device or resource busy
         /app/.config/QQ 本身是 mount point（基镜像声明了 VOLUME），
         内核不允许重命名/删除挂载点。
      2. EXDEV(18) Invalid cross-device link
         QQ/ 下还有独立挂载（实测 NapCat 子目录就是一例），它与 QQ.old
         所在的父目录不在同一文件系统，rename 跨不过去。

    早先的实现两处都栽了：先在「rename 整个 qq_dir」撞 EBUSY，改为逐项 rename
    后又在 NapCat 子目录撞 EXDEV，而回滚用的是同一个 rename，跟着一起炸——
    结果是解压成功、校验通过、换入静默失败，会话恢复从来没生效过
    （start.sh 用 `|| true` 调，异常被吞，容器照常 running）。

    修法：改用 shutil.move，它对 EXDEV 会自动回退到「拷贝 + 删源」；
    仍失败（该子项自己也是挂载点、无法删除）就保留原地，让后续解压覆盖它。
    """
    moved = []
    if not os.path.isdir(src):
        return moved
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        try:
            if os.path.isdir(d) and not os.path.islink(d):
                shutil.rmtree(d, ignore_errors=True)
            else:
                os.remove(d)
        except OSError:
            pass
        try:
            shutil.move(s, d)
            moved.append(name)
        except OSError as e:
            # 该子项挪不动（自己也是挂载点、或跨设备且 move 也失败）：
            # 保留原地，后续解压会覆盖同名内容
            log(f"清空旧数据时 {name} 挪动失败(保留原地): {e}")
    return moved


def _move_tree(src, dst):
    """把 tmp 的内容搬进 qq_dir，同样走 shutil.move 以容忍跨设备。"""
    for name in os.listdir(src):
        shutil.move(os.path.join(src, name), os.path.join(dst, name))


def cmd_restore(args):
    snap, qq_dir = args.snapshot, args.qq_dir
    if not os.path.isfile(snap):
        log(f"无会话快照({snap});{describe_mount(os.path.dirname(snap) or '/')},按首次部署处理")
        return 0
    tmp = qq_dir + ".restore_tmp"
    old = qq_dir + ".old"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)
    try:
        os.makedirs(tmp, exist_ok=True)
        with tarfile.open(snap, "r:gz") as tf:
            members = [m for m in tf.getmembers()
                       if not m.name.startswith("/")
                       and ".." not in m.name.split("/")
                       and not _is_link(m)]
            if not members:
                raise ValueError("快照内没有任何可恢复的成员")
            try:
                # Python 3.12+ 的官方加固过滤器：拒绝链接/设备/越权路径。
                # 老版本 fallback 到上面的成员级过滤（已覆盖链接这一类）。
                tf.extractall(tmp, members=members, filter="data")
            except TypeError:
                tf.extractall(tmp, members=members)
    except Exception as e:
        log(f"快照解压失败(可能损坏),放弃恢复: {e}")
        shutil.rmtree(tmp, ignore_errors=True)
        return 1
    if not has_login_data(tmp):
        log("快照中无账号登录数据(nt_qq_*),放弃恢复")
        shutil.rmtree(tmp, ignore_errors=True)
        return 1

    # 先把现有内容挪到 .old，再把 tmp 里的内容搬进 qq_dir。
    # 全程不 rename/删除 qq_dir 本身（它可能是 mount point），且用 shutil.move
    # 而非 os.rename（子项可能跨设备，move 会自动回退到拷贝+删源）。
    try:
        _drain_dir(qq_dir, old)
        os.makedirs(qq_dir, exist_ok=True)
        _move_tree(tmp, qq_dir)
    except Exception as e:
        log(f"恢复换入失败,回滚旧数据: {e}")
        try:
            _drain_dir(qq_dir, tmp + ".failed")
            if os.path.isdir(old):
                _move_tree(old, qq_dir)
        except Exception as re:
            log(f"回滚也失败,QQ 目录可能为空:{re}")
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp + ".failed", ignore_errors=True)
        shutil.rmtree(old, ignore_errors=True)

    if not has_login_data(qq_dir):
        log("恢复后仍无账号登录数据(nt_qq_*),恢复无效")
        return 1
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
