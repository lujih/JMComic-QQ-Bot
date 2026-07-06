import os
import sys
from pathlib import Path

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OnebotV11Adapter

sys.path.insert(0, str(Path(__file__).parent / "src"))

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OnebotV11Adapter)
nonebot.load_plugins("src/plugins")

if __name__ == "__main__":
    nonebot.run()
