import os
import time
import asyncio
import random
from pathlib import Path

from nonebot import require, get_bot

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

from jmcomic import create_option_by_file, jm_log

__plugin_name__ = "jm_scheduler"
__plugin_usage__ = "每日早 9 点推送随机推荐"

OPTION_PATH = Path(__file__).parent.parent / "option.yml"


def _parse_target_groups() -> list[int]:
    raw = os.getenv("TARGET_GROUPS", "").strip()
    if not raw:
        return []
    return [int(g.strip()) for g in raw.split(",") if g.strip().isdigit()]


def _fetch_recommendation():
    option = create_option_by_file(str(OPTION_PATH))
    client = option.build_jm_client()
    page = client.month_ranking(1)
    results = list(page)
    if not results:
        return None
    aid, title = random.choice(results)
    return aid, title


@scheduler.scheduled_job("cron", hour="9", minute="0", id="daily_recommend")
async def daily_recommend():
    groups = _parse_target_groups()
    if not groups:
        return

    loop = asyncio.get_running_loop()

    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _fetch_recommendation),
            timeout=30,
        )
        if result is None:
            jm_log("scheduler.info", "每日推荐：排行榜为空")
            return
        aid, title = result
    except asyncio.TimeoutError:
        jm_log("scheduler.error", "每日推荐：获取排行榜超时")
        return
    except Exception as e:
        jm_log("scheduler.error", f"每日推荐：获取失败 — {e}")
        return

    text = f"🎲 今日推荐\nJM{aid} {title}\n发送 /jm {aid} 下载"

    try:
        bot = get_bot()
    except ValueError:
        jm_log("scheduler.error", "每日推荐：Bot 未连接")
        return
    except Exception as e:
        jm_log("scheduler.error", f"每日推荐：获取 Bot 失败 — {e}")
        return

    for gid in groups:
        try:
            await bot.send_msg(message_type="group", group_id=gid, message=text)
        except Exception as e:
            jm_log("scheduler.error", f"每日推荐：发送到群 {gid} 失败 — {e}")


@scheduler.scheduled_job("cron", hour="*", minute="30", id="cleanup_cache")
async def cleanup_cache():
    cache_dir = Path("/tmp/jm/")
    if not cache_dir.exists():
        return

    now = time.time()
    removed = 0
    for f in cache_dir.iterdir():
        if f.is_file() and now - f.stat().st_mtime > 1800:
            f.unlink(missing_ok=True)
            removed += 1

    if removed > 0:
        jm_log("scheduler.info", f"缓存清理：已删除 {removed} 个过期文件")
