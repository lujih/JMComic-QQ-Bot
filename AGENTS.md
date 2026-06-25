# AGENTS.md — jmcomic-qq-bot

## 架构

```
NapCatQQ (QQ协议层) ──WS──→ NoneBot2 (消息路由) ──→ jmcomic (下载引擎)
     │                              │
     └── WebUI (7860)               └── /jm 命令 → download_album → img2pdf → upload_group_file
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
| `.env` | `DRIVER=~fastapi`, `HOST=0.0.0.0`, `PORT=8080`, `COMMAND_START=["/"]` |
| `config/onebot11.json` | NapCat WS 客户端 → `ws://127.0.0.1:8080/onebot/v11/ws` |
| `plugins/jm_download.py` | `/jm <album_id>` 命令处理 |
| `option.yml` | jmcomic 配置（`impl: api`、img2pdf 插件） |
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

限制：每人每群 60 秒冷却，PDF 超 100MB 跳过，发送后自动清理。

## 关联仓库

- jmcomic 库源码：`path/to/JMComic-Crawler-Python`
