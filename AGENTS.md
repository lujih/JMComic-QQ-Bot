# AGENTS.md — jmcomic-qq-bot

## 架构

```
NapCatQQ (QQ协议层) ──WS──→ NoneBot2 (消息路由) ──→ jmcomic (下载引擎)
     │                              │
     └── WebUI (7860)               ├── /jm      → ProgressJmDownloader → img2pdf/zip/longimg
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
| `plugins/jm_download.py` | 全部 `/jm` 子命令 + `ProgressJmDownloader` + 进度推送 + 超时重试 |
| `plugins/jm_info.py` | `/jmv` 详情 + `/jms` 搜索 |
| `plugins/jm_scheduler.py` | 每日 9:00 随机推荐（APScheduler + `TARGET_GROUPS`） |
| `option.yml` | jmcomic 配置（`impl: api`、img2pdf 插件 `after_album`） |
| `Dockerfile` | 基于 `mlikiowa/napcat-docker:v4.18.7` + Python venv |
| `start.sh` | 容器入口：反检测 → Xvfb → QQ 后台 → NoneBot 前台 |
| `health.py` | 备用状态页（NapCat WebUI 为主） |

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

### jmcomic 同步 API 阻塞防护
- 所有 jmcomic 调用必须经 `run_in_executor` + `wait_for(timeout)` 在 async 上下文中执行（NoneBot2 是 async event loop）
- 并发控制：全局 `asyncio.Semaphore(1)` 串行化下载
- 回调进度：`asyncio.run_coroutine_threadsafe` 从 sync 线程发消息
- `ProgressJmDownloader` 子类化 `JmDownloader`，覆盖 `before_photo`/`after_photo`/`after_album` 钩子实现分段推送

### jmcomic 插件
- `option.yml` 中 `plugin:` 自动转为 `plugins:`（兼容旧版）
- `after_album` 下 `photo=None`，**`filename_rule` 必须用 `A` 前缀**（如 `Aid`），用默认 `Pid` 会 `getattr(None, 'id')` 崩溃
- 插件异常默认被 `safe: True` 静默吞掉，怀疑插件不生效时加 `safe: false`
- `impl: api`（移动端 API），HF 海外节点无法访问 HTML 客户端
- 详见 jmcomic 库的 `AGENTS.md` → `path/to/JMComic-Crawler-Python\AGENTS.md`

### 部署
- 首次部署需通过 NapCat WebUI 扫码登录 QQ 小号
- 登录 session 持久化，Space 不超 48h 回收则后续自动登录
- 端口中：7860（HF Spaces 默认 → WebUI）、8080（内部 NoneBot WS 服务器）
- 防休眠：UptimeRobot 每 30 分钟 ping Space URL

## 命令

| 命令 | 说明 | 示例 |
|---|---|---|
| `/jm <ID>` | 下载本子并发送 PDF | `/jm 438516` |
| `/jm p<ID>` | 下载单个章节 | `/jm p350234` |
| `/jm rank [周/月/日]` | 排行榜（默认周榜） | `/jm rank 月` |
| `/jm random` | 随机推荐一本 | `/jm random` |
| `/jm help` | 查看全部命令 | `/jm help` |
| `/jmv <ID>` | 查看本子详情 | `/jmv 438516` |
| `/jms <关键词>` | 搜索本子 | `/jms 无修正` |
| 每日早 9:00 | 自动推送随机推荐 | 需 `.env` 配置 `TARGET_GROUPS` |

### 限制与行为
- 每人每群 60 秒冷却（仅下载，rank/random/help 无冷却）
- 进度推送按 10% 阈值节流（≤5 章全报，大本子只报第 1/10%/每 10%/最后一章）
- 超时自动重试 1 次（3s 间隔），仅限 `asyncio.TimeoutError`
- PDF 超 100MB 跳过群上传
- 下载后自动清理原始图片（`dir_rule: Bd_Aid → /tmp/jm_dl/A{id}/`）

## 关联仓库

- jmcomic 库源码：`path/to/JMComic-Crawler-Python`
