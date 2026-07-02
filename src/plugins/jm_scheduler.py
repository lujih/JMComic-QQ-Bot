import os
import asyncio
import random

from nonebot import require, get_bot

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

from jmcomic import jm_log
from jm_option import get_option

__plugin_name__ = "jm_scheduler"
__plugin_usage__ = "每日早 9 点推送随机推荐"


def _parse_target_groups() -> list[int]:
    raw = os.getenv("TARGET_GROUPS", "").strip()
    if not raw:
        return []
    return [int(g.strip()) for g in raw.split(",") if g.strip().isdigit()]


@scheduler.scheduled_job("cron", hour="9", minute="0", id="daily_recommend")
async def daily_recommend():
    groups = _parse_target_groups()
    if not groups:
        jm_log("scheduler.info", "每日推荐：跳过推送（TARGET_GROUPS 未配置）")
        return

    try:
        option = get_option()
        async with option.new_jm_async_client() as cl:
            page = await asyncio.wait_for(cl.month_ranking(1), timeout=30)
        results = list(page)
        if not results:
            jm_log("scheduler.info", "每日推荐：排行榜为空")
            return
        aid, title = random.choice(results)
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



