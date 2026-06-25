import os
import time
import re
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.rule import to_me

import jmcomic
from jmcomic import create_option_by_file

__plugin_name__ = "jm_download"
__plugin_usage__ = "/jm <album_id> — 下载本子并转为 PDF 发送到群"

jm_cmd = on_command("jm", priority=10)

COOLDOWN_SECONDS = 60
_last_use: dict[str, float] = {}


def _check_cooldown(key: str) -> int:
    now = time.time()
    last = _last_use.get(key, 0)
    remaining = COOLDOWN_SECONDS - (now - last)
    if remaining > 0:
        return int(remaining)
    _last_use[key] = now
    return 0


OPTION_PATH = Path(__file__).parent.parent / "option.yml"


@jm_cmd.handle()
async def handle_jm(bot: Bot, event: GroupMessageEvent):
    text = event.get_plaintext().strip()
    match = re.search(r"\d+", text)
    if not match:
        await jm_cmd.finish("格式: /jm <本子ID>\n例如: /jm 438516")

    album_id = match.group()
    cooldown_key = f"{event.group_id}:{event.user_id}"

    remaining = _check_cooldown(cooldown_key)
    if remaining:
        await jm_cmd.finish(f"操作太频繁，请 {remaining} 秒后再试")

    await jm_cmd.send(f"⏳ 正在下载 JM{album_id} 并生成 PDF……")

    pdf_path = Path(f"/tmp/jm/{album_id}.pdf")
    if pdf_path.exists():
        pdf_path.unlink()

    try:
        option = create_option_by_file(str(OPTION_PATH))
        jmcomic.download_album(album_id, option)
    except Exception as e:
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish(f"❌ 下载失败: {type(e).__name__}: {e}")

    if not pdf_path.exists():
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish("❌ PDF 生成失败，文件未找到")

    file_size = pdf_path.stat().st_size
    if file_size > 100 * 1024 * 1024:
        pdf_path.unlink()
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish("❌ PDF 超过 100MB，无法发送到群")

    try:
        await bot.call_api(
            "upload_group_file",
            group_id=event.group_id,
            file=str(pdf_path.resolve()),
            name=f"JM{album_id}.pdf",
        )
        await jm_cmd.send(f"✅ JM{album_id} 下载完成，PDF 已发送到群")
    except Exception as e:
        await jm_cmd.send(f"PDF 文件已生成但发送失败: {e}\n可联系管理员手动获取")
    finally:
        pdf_path.unlink(missing_ok=True)
        dl_dir = Path(f"/tmp/jm_dl/{album_id}")
        if dl_dir.exists():
            import shutil
            shutil.rmtree(dl_dir, ignore_errors=True)
