import os
import sys
from pathlib import Path
import time as _time

_t0 = _time.perf_counter()

import nonebot

_t1 = _time.perf_counter()
print(f"[bot.timing] import nonebot: {_t1 - _t0:.2f}s")
sys.stdout.flush()
from nonebot.adapters.onebot.v11 import Adapter as OnebotV11Adapter

_t2 = _time.perf_counter()
print(f"[bot.timing] import adapter:  {_t2 - _t1:.2f}s ({_t2 - _t0:.2f}s total)")
sys.stdout.flush()

sys.path.insert(0, str(Path(__file__).parent / "src"))

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OnebotV11Adapter)

_t3 = _time.perf_counter()
print(f"[bot.timing] nonebot.init:    {_t3 - _t2:.2f}s ({_t3 - _t0:.2f}s total)")
sys.stdout.flush()

nonebot.load_plugins("src/plugins")

_t4 = _time.perf_counter()
print(f"[bot.timing] load_plugins:    {_t4 - _t3:.2f}s ({_t4 - _t0:.2f}s total)")
sys.stdout.flush()

if __name__ == "__main__":
    nonebot.run()
