import os

os.environ.setdefault("ENVIRONMENT", "prod")

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OnebotV11Adapter

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OnebotV11Adapter)
nonebot.load_plugins("plugins")
nonebot.run()
