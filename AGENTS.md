# AGENTS.md — JMComic-QQ-Bot

## 架构

```
NapCatQQ (QQ协议层) ──WS──→ NoneBot2 (消息路由) ──→ jmcomic (下载引擎)
     │                              │
     └── WebUI (7860)               ├── /jm      → ProgressJmDownloader → Feature.export_pdf/zip/long_img
                                     ├── /jm help  → HELP_TEXT
                                     ├── /jm rank  → month/week/day_ranking
                                     ├── /jm random → month_ranking → random.choice
                                     ├── /jmv      → get_album_detail
                                     ├── /jms      → search_site
                                     ├── /mv       → MissAV 标题搜索 + Sukebei 磁力链
                                      └── 每日 9:00  → APScheduler → month_ranking → 群推送
```

架构翻转：NoneBot2 做 WS 服务器（`:8080`），NapCat 做 WS 客户端连接。

## 关键文件

| 文件 | 作用 |
|---|---|---|
| `bot.py` | NoneBot2 入口，显式注册 `OnebotV11Adapter` |
| `.env` | `DRIVER=~fastapi`, `HOST=0.0.0.0`, `PORT=8080`, `COMMAND_START=["/"]`, `TARGET_GROUPS` |
| `config/onebot11.json` | NapCat WS 客户端 → `ws://127.0.0.1:8080/onebot/v11/ws` |
| `src/plugins/jm/` | `/jm` 命令包 — `handler.py`(路由), `album.py`(本子下载), `photo.py`(单章), `upload.py`(二级上传fallback), `progress.py`(进度推送), `common.py`(公共工具) |
| `src/plugins/mv/` | `/mv` 命令包 — `handler.py`(路由), `_search.py`(MissAV标题), `_torrent.py`(Sukebei磁力) |
| `src/plugins/jm_info.py` | `/jmv` 详情 + `/jms` 搜索 |
| `src/plugins/jm_scheduler.py` | 每日 9:00 随机推荐（APScheduler + `TARGET_GROUPS`） |
| `src/jm_option.py` | jmcomic option 双检锁缓存 |
| `option.yml` | jmcomic 配置（`impl: api`，无 plugin 段，格式由 Feature 传入） |
| `Dockerfile` | 基于 `mlikiowa/napcat-docker` + Python venv + ffmpeg |
| `start.sh` | 容器入口：配置写入 → NapCat 解包 → Xvfb → QQ 后台 → NoneBot 前台 |

## 开发命令

```bash
# 本地测试（需已安装 Python 3.10+）
pip install -r requirements.txt
python bot.py

# 从本地 jmcomic 源码安装（开发时联调）
pip install -e path/to/JMComic-Crawler-Python
```

## 已踩的坑

### Dockerfile
- 基镜像 `mlikiowa/napcat-docker` 有 `ENTRYPOINT ["bash", "entrypoint.sh"]`，必须用 `ENTRYPOINT []` 清掉
- `NapCat.Shell.zip` 构建时未解压，需在 `start.sh` 手动 `unzip`
- `nonebot2` 须安装 `[fastapi]` extras（纯包缺 fastapi）
- `/app/.config/QQ/NapCat/temp` 权限：需 `mkdir + chown napcat:napcat`
- `FFMPEG_PATH` 声明后须 `apt-get install ffmpeg`

### jmcomic 同步 API 阻塞防护
- 所有 jmcomic 调用必须经 `run_in_executor` + `wait_for(timeout)` 在 async 上下文中执行（NoneBot2 是 async event loop）
- 并发控制：全局 `asyncio.Semaphore(1)` 串行化下载
- `wait_for` 超时后底层线程无法取消（Python 线程语义），可能游离。已移除超时重试循环避免并发写
- 进度展示：下载前一次性展示本子详情（`album.py` 直接发送），不再通过下载器回调逐章推送
- `ProgressJmDownloader` 子类化 `JmDownloader`，仅覆盖 `before_photo` 用于检查取消信号（`cancel_event.is_set()` 时跳过该章节），无进度推送逻辑

### jmcomic Feature 机制
- 格式（PDF/ZIP/长图）通过 `Feature.export_*` 作为 `extra` 参数传入，不写在 `option.yml` plugin 段
- `after_album` 下 `photo=None`，`filename_rule` 必须用 `A` 前缀（如 `Aid`）；单章下载用 `Pid`
- 详见 jmcomic 库的 `AGENTS.md`

### jm_scheduler 未复用 option 缓存
- 最初 `jm_scheduler.py` 直接调用 `create_option_by_file(str(OPTION_PATH))`，与 `jm_option.py` 缓存单例不一致
- 修复：改为 `from jm_option import get_option`，与 `src/plugins/jm/` 包共享同一 option 实例

### 部署
- 首次部署需通过 NapCat WebUI 扫码登录 QQ 小号
- HF Spaces 磁盘为临时存储，Space 重启后需重新扫码
- 端口中：7860（HF Spaces 默认 → WebUI）、8080（内部 NoneBot WS 服务器）
- 防休眠：UptimeRobot 每 30 分钟 ping Space URL

## 命令

| 命令 | 说明 | 示例 |
|---|---|---|
| `/jm <ID>` | 下载本子（默认 PDF） | `/jm 438516` |
| `/jm <ID> --zip` | 下载本子并打包 ZIP | `/jm 438516 --zip` |
| `/jm <ID> --longimg` | 下载本子并拼接长图 | `/jm 438516 --longimg` |
| `/jm p<ID>` | 下载单个章节（仅 PDF） | `/jm p350234` |
| `/jm rank [周/月/日]` | 排行榜（默认周榜） | `/jm rank 月` |
| `/jm random` | 随机推荐一本 | `/jm random` |
| `/jm help` | 查看全部命令 | `/jm help` |
| `/jmv <ID>` | 查看本子详情 | `/jmv 438516` |
| `/jms <关键词>` | 搜索本子 | `/jms 无修正` |
| `/mv <番号>` | 搜索番号返回磁力链接 | `/mv SSNI-123` |
| `/mv <番号> --page N` | 翻页 | `/mv SSNI-123 --page 2` |
| 每日早 9:00 | 自动推送随机推荐 | 需 `.env` 配置 `TARGET_GROUPS` |

### 限制与行为
- 每人每群 60 秒冷却（仅下载，rank/random/help 无冷却）
- 下载前一次性展示本子详情（名称/作者/章节/页数/标签），不再发逐章进度
- 下载超时直接结束（无自动重试，避免线程竞态），jmcomic 内部已有 3 次重试
- 30 分钟短时缓存（`/tmp/jm/{id}.ext`），定时每 30 分钟清理过期缓存和残留下载目录（`/tmp/jm_dl/`）
- 下载后自动清理原始图片（`/tmp/jm_dl/A{id}/` 及 `P{id}/`）
- 每次 `/jm` 命令开头自动扫描 `/tmp/jm_dl/`，删除超过 30 分钟的残留目录（替代原 APScheduler 定时清理）


