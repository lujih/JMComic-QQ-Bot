from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.rule import is_type

jm_cmd = on_command("jm", priority=10, rule=is_type(GroupMessageEvent))
