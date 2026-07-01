from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.rule import is_type

mv_cmd = on_command("mv", priority=10, rule=is_type(GroupMessageEvent))
