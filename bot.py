import os
import sys

os.environ.setdefault("ENVIRONMENT", "prod")

import nonebot

nonebot.init()
nonebot.load_plugins("plugins")
nonebot.run()
