import os
import sys
from pathlib import Path

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OnebotV11Adapter

sys.path.insert(0, str(Path(__file__).parent / "src"))

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OnebotV11Adapter)
# 显式按模块名加载，避免 load_plugins("src/plugins") 生成 src.plugins.jm 命名空间，
# 与插件内部 from plugins.jm.xxx 绝对导入形成双命名空间、handler 双注册
for plugin_name in ("jm", "mv", "jm_info", "jm_comment", "jm_scheduler"):
    nonebot.load_plugin(f"plugins.{plugin_name}")

if __name__ == "__main__":
    nonebot.run()
