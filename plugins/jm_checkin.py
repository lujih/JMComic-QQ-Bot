import asyncio

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

from plugins.database import do_checkin

__plugin_name__ = "jm_checkin"
__plugin_usage__ = "/sign — 每日签到获取积分"

sign_cmd = on_command("sign", priority=10)


@sign_cmd.handle()
async def handle_sign(bot: Bot, event: GroupMessageEvent):
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, do_checkin, event.user_id, event.group_id)
    await sign_cmd.finish(result['msg'])
