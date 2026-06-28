import uuid
import math
import hashlib
import base64
import asyncio
import shutil
from pathlib import Path

import httpx
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

from plugins.jm._cmd import jm_cmd
from plugins.jm.common import _last_use, _DL_TMP

_TRANSIT_BASE = "https://transit2.cszxorx.dpdns.org"


async def _upload_to_transit2(file_path: Path, filename: str) -> str:
    loop = asyncio.get_running_loop()

    def _sync():
        size = file_path.stat().st_size

        resp = httpx.post(
            f"{_TRANSIT_BASE}/api/upload",
            json={"filename": filename, "size": size, "mimeType": "application/octet-stream"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        file_id = data["fileId"]
        upload_key = data["uploadKey"]
        chunk_urls = data.get("chunkUrls")

        if chunk_urls is None:
            upload_url = data["uploadUrl"]
            with open(file_path, "rb") as f:
                r = httpx.put(upload_url, content=f, timeout=300)
            r.raise_for_status()
        else:
            upload_id = data["uploadId"]
            chunk_size = data["chunkSize"]
            parts = []

            with open(file_path, "rb") as f:
                for i, url in enumerate(chunk_urls):
                    part_number = i + 1
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    r = httpx.put(url, content=chunk, timeout=120)
                    r.raise_for_status()
                    parts.append({"PartNumber": part_number, "ETag": r.headers.get("ETag")})

            r = httpx.post(
                f"{_TRANSIT_BASE}/api/upload/{file_id}/chunks/complete",
                json={"uploadId": upload_id, "uploadKey": upload_key, "parts": parts},
                timeout=30,
            )
            r.raise_for_status()

        return file_id

    return await asyncio.wait_for(
        loop.run_in_executor(None, _sync),
        timeout=600,
    )


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
            st = file_path.stat()
        except FileNotFoundError:
            _last_use.pop(cooldown_key, None)
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
        except Exception:
            pass

        # Tier 2 — upload_file_stream → upload_group_file
        try:
            await _upload_via_stream(bot, event.group_id, file_path, filename)
            await jm_cmd.send(f"✅ JM{id_str} 下载完成（流式上传），{fmt_name} 已发送到群")
            success = True
            return
        except Exception:
            pass

        # Tier 3 — Transit2 下载链接
        try:
            file_id = await _upload_to_transit2(file_path, filename)
            await jm_cmd.send(
                f"📎 JM{id_str} 文件较大({st.st_size / 1048576:.1f}MB)，已上传至中转站\n"
                f"🔗 {_TRANSIT_BASE}/file/{file_id}\n"
                f"⏰ 24小时自动删除"
            )
            success = True
            return
        except Exception as e:
            _last_use.pop(cooldown_key, None)
            await jm_cmd.finish(f"❌ {fmt_name} 上传失败（已尝试 3 种方式）: {e}")
    finally:
        for prefix in ('A', 'P'):
            d = _DL_TMP / f"{prefix}{id_str}"
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)

        if not success:
            file_path.unlink(missing_ok=True)
