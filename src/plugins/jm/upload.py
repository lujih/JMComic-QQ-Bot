import asyncio
import uuid
import math
import hashlib
import base64
import shutil
from pathlib import Path

from jmcomic import jm_log

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

from plugins.jm.cmd import jm_cmd
from plugins.jm.common import _clear_cooldown, _get_dl_tmp


def _calc_sha256(file_path: Path) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


def _encode_chunk(file_path: Path, offset: int, size: int) -> str:
    with open(file_path, "rb") as f:
        f.seek(offset)
        chunk = f.read(size)
    return base64.b64encode(chunk).decode()


async def _upload_via_stream(bot: Bot, group_id: int, file_path: Path, filename: str):
    loop = asyncio.get_running_loop()
    size = file_path.stat().st_size
    digest = await loop.run_in_executor(None, _calc_sha256, file_path)

    stream_id = str(uuid.uuid4())
    chunk_size = 1024 * 1024
    total_chunks = max(math.ceil(size / chunk_size), 1)

    for i in range(total_chunks):
        chunk_b64 = await loop.run_in_executor(
            None, _encode_chunk, file_path, i * chunk_size, chunk_size
        )
        if not chunk_b64:
            break
        await bot.call_api("upload_file_stream", timeout=30, **{
            "stream_id": stream_id,
            "chunk_data": chunk_b64,
            "chunk_index": i,
            "total_chunks": total_chunks,
            "file_size": size,
            "expected_sha256": digest,
            "filename": filename,
            "file_retention": 300_000,
        })

    resp = await bot.call_api("upload_file_stream", timeout=30, **{
        "stream_id": stream_id,
        "is_complete": True,
    })

    file_path_local = resp["data"]["file_path"]
    await bot.call_api("upload_group_file", timeout=120, **{
        "group_id": group_id,
        "file": file_path_local,
        "name": filename,
    })


async def _upload_and_cleanup(bot: Bot, event: GroupMessageEvent, file_path: Path, id_str: str, cooldown_key: str, ext='pdf', fmt_name='PDF', dl_dir: Path | None = None):
    success = False
    try:
        try:
            if not file_path.exists():
                raise FileNotFoundError
        except FileNotFoundError:
            _clear_cooldown(cooldown_key)
            await jm_cmd.finish(f"❌ {fmt_name} 上传失败（文件已被清理），请重新下载")

        filename = f"JM{id_str}.{ext}"

        # Tier 1 — upload_group_file
        try:
            await bot.call_api(
                "upload_group_file", timeout=120,
                group_id=event.group_id,
                file=str(file_path.resolve()),
                name=filename,
            )
            success = True
            return
        except Exception as e:
            jm_log('jm.upload.tier1', 'upload_group_file 失败，降级到流式上传', e)

        # Tier 2 — upload_file_stream → upload_group_file
        try:
            await _upload_via_stream(bot, event.group_id, file_path, filename)
            success = True
            return
        except Exception as e:
            _clear_cooldown(cooldown_key)
            jm_log('jm.upload.tier2', '流式上传失败', e)
            await jm_cmd.finish(f"❌ {fmt_name} 上传失败（已尝试 2 种方式）")
    finally:
        loop = asyncio.get_running_loop()
        d = dl_dir or (_get_dl_tmp() / id_str)
        if d.exists():
            await loop.run_in_executor(None, lambda: shutil.rmtree(d, ignore_errors=True))

        if not success:
            await loop.run_in_executor(None, lambda: file_path.unlink(missing_ok=True))
