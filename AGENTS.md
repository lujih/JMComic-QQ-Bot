# AGENTS.md — jmcomic-qq-bot

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
                                     └── 每日 9:00  → APScheduler → month_ranking → 群推送
```

架构翻转：NoneBot2 做 WS 服务器（`:8080`），NapCat 做 WS 客户端连接。

## HF Space

- **Space**: `https://huggingface.co/spaces/your-username/jmcomic-qq-bot`
- **本地仓库**: `path/to/jmcomic-qq-bot`
- **SDK**: Docker
- **登录方式**: 推送 → 自动构建 → 打开 Space → NapCat WebUI 扫码

## 关键文件

| 文件 | 作用 |
|---|---|
| `bot.py` | NoneBot2 入口，显式注册 `OnebotV11Adapter` |
| `.env` | `DRIVER=~fastapi`, `HOST=0.0.0.0`, `PORT=8080`, `COMMAND_START=["/"]`, `TARGET_GROUPS` |
| `config/onebot11.json` | NapCat WS 客户端 → `ws://127.0.0.1:8080/onebot/v11/ws` |
| `plugins/jm_download.py` | 全部 `/jm` 子命令 + `ProgressJmDownloader` 进度推送 + 格式切换 |
| `plugins/jm_info.py` | `/jmv` 详情 + `/jms` 搜索 |
| `plugins/jm_scheduler.py` | 每日 9:00 随机推荐（APScheduler + `TARGET_GROUPS`）+ 每 30 分钟缓存清理 |
| `option.yml` | jmcomic 配置（`impl: api`，无 plugin 段，格式由 Feature 传入） |
| `Dockerfile` | 基于 `mlikiowa/napcat-docker:v4.18.7` + Python venv + ffmpeg |
| `start.sh` | 容器入口：反检测 → Xvfb → QQ 后台 → NoneBot 前台 |

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
- 回调进度：`asyncio.run_coroutine_threadsafe` 从 sync 线程发消息
- `ProgressJmDownloader` 子类化 `JmDownloader`，覆盖 `before_photo`/`after_photo`/`after_album` 钩子实现分段推送

### jmcomic Feature 机制
- 格式（PDF/ZIP/长图）通过 `Feature.export_*` 作为 `extra` 参数传入，不写在 `option.yml` plugin 段
- `after_album` 下 `photo=None`，`filename_rule` 必须用 `A` 前缀（如 `Aid`）；单章下载用 `Pid`
- 详见 jmcomic 库的 `AGENTS.md` → `path/to/JMComic-Crawler-Python\AGENTS.md`

### 部署
- 首次部署需通过 NapCat WebUI 扫码登录 QQ 小号
- 登录 session 持久化，Space 不超 48h 回收则后续自动登录
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
| 每日早 9:00 | 自动推送随机推荐 | 需 `.env` 配置 `TARGET_GROUPS` |

### 限制与行为
- 每人每群 60 秒冷却（仅下载，rank/random/help 无冷却）
- 进度推送按 10% 阈值节流（≤5 章全报，大本子只报第 1/10%/每 10%/最后一章）
- 下载超时直接结束（无自动重试，避免线程竞态），jmcomic 内部已有 3 次重试
- PDF 超 100MB 跳过群上传，私聊通知用户（建议 `--zip` 压缩）
- 群文件上传失败自动重试 1 次→仍失败则私聊 fallback
- 30 分钟短时缓存（`/tmp/jm/{id}.ext`），定时每 30 分钟清理过期缓存
- 下载后自动清理原始图片（`dir_rule: Bd_Aid → /tmp/jm_dl/A{id}/` 及 `P{id}/`）

## 关联仓库

- jmcomic 库源码：`path/to/JMComic-Crawler-Python`
