import uuid
import math
import hashlib
import base64
import shutil
from pathlib import Path

from jmcomic import jm_log

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

from plugins.jm._cmd import jm_cmd
from plugins.jm.common import _clear_cooldown, _DL_TMP


async def _upload_via_stream(bot: Bot, group_id: int, file_path: Path, filename: str):
    size = file_path.stat().st_size

    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    digest = sha256.hexdigest()

    stream_id = str(uuid.uuid4())
    chunk_size = 1024 * 1024
    total_chunks = max(math.ceil(size / chunk_size), 1)

    with open(file_path, "rb") as f:
        for i in range(total_chunks):
            chunk = f.read(chunk_size)
            if not chunk:
                break
            await bot.call_api("upload_file_stream", **{
                "stream_id": stream_id,
                "chunk_data": base64.b64encode(chunk).decode(),
                "chunk_index": i,
                "total_chunks": total_chunks,
                "file_size": size,
                "expected_sha256": digest,
                "filename": filename,
                "file_retention": 300_000,
            })

        resp = await bot.call_api("upload_file_stream", **{
            "stream_id": stream_id,
            "is_complete": True,
        })

    file_path_local = resp["data"]["file_path"]
    await bot.call_api("upload_group_file", **{
        "group_id": group_id,
        "file": file_path_local,
        "name": filename,
    })


async def _upload_and_cleanup(bot: Bot, event: GroupMessageEvent, file_path: Path, id_str: str, cooldown_key: str, ext='pdf', fmt_name='PDF'):
    success = False
    try:
        try:
            file_path.stat()
        except FileNotFoundError:
            _clear_cooldown(cooldown_key)
            await jm_cmd.finish(f"❌ {fmt_name} 上传失败（文件已被清理），请重新下载")

        filename = f"JM{id_str}.{ext}"

        # Tier 1 — upload_group_file
        try:
            await bot.call_api(
                "upload_group_file",
                group_id=event.group_id,
                file=str(file_path.resolve()),
                name=filename,
            )
            await jm_cmd.send(f"✅ JM{id_str} 下载完成，{fmt_name} 已发送到群")
            success = True
            return
        except Exception as e:
            jm_log('upload.tier1', f'upload_group_file 失败，降级到流式上传: {e}')

        # Tier 2 — upload_file_stream → upload_group_file
        try:
            await _upload_via_stream(bot, event.group_id, file_path, filename)
            await jm_cmd.send(f"✅ JM{id_str} 下载完成（流式上传），{fmt_name} 已发送到群")
            success = True
            return
        except Exception as e:
            _clear_cooldown(cooldown_key)
            await jm_cmd.finish(f"❌ {fmt_name} 上传失败（已尝试 2 种方式）: {e}")
    finally:
        for prefix in ('A', 'P'):
            d = _DL_TMP / f"{prefix}{id_str}"
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)

        if not success:
            file_path.unlink(missing_ok=True)
