---
title: JMComic QQ Bot
sdk: docker
pinned: false
---

# JMComic QQ Bot

> 🤖 基于 NapCatQQ + NoneBot2 + jmcomic 的 QQ 群漫画下载机器人

群内发送 `/jm <本子ID>` 即可自动下载并转为 PDF/ZIP/长图发送到群。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 功能特性

| 功能 | 说明 |
|---|---|
| `/jm <ID>` | 下载本子并发送 PDF（默认） |
| `/jm <ID> --zip` / `--longimg` | 切换为 ZIP / 长图格式 |
| `/jm p<ID>` | 下载单章（PDF） |
| `/jm rank [周/月/日]` | 查看排行榜 |
| `/jm random` | 随机推荐本子 |
| `/jmv <ID>` | 查看本子详情 |
| `/jms <关键词>` | 搜索本子 |
| `/jmc <ID> [页码]` | 查看本子评论（每页最多 8 条） |
| `/mv <番号>` | 搜索番号返回磁力链接（MissAV+JavDB+jav321 三源合并 + Sukebei 磁力链） |
| 每日 9:00 自动推送 | 随机推荐到已配置群 |

## 快速部署

### 前置条件

- [Hugging Face](https://huggingface.co) 账号
- 一个 **QQ 小号**（用于扫码登录，推荐新注册的号）
- [Git](https://git-scm.com)

### 1. 创建 HF Space

1. 登录 huggingface.co → 右上角头像 → **New Space**
2. 填写参数：

   | 字段 | 值 |
   |---|---|
   | Space Name | `jmcomic-qq-bot` |
   | License | MIT |
   | Space SDK | **Docker** |
   | Hardware | CPU free |

3. 点击 **Create Space**

### 2. 推送代码

```bash
# 克隆 HF Space 仓库（创建后页面会显示此命令）
git clone https://huggingface.co/spaces/你的用户名/jmcomic-qq-bot
cd jmcomic-qq-bot

# 从本仓库复制代码（或在 HF Space 页面直接 Fork 本仓库）
cp -r /path/to/JMComic-QQ-Bot/* .

git add -A
git commit -m "init: jmcomic qq bot"
git push
```

推送后进入 Space → **Builder Logs** 查看构建进度（约 **3-5 分钟**）。构建依赖 [mlikiowa/napcat-docker](https://github.com/NapNeko/NapCatQQ) 基镜像，首次可能较慢。

### 3. 配置环境变量

在 Space → **Settings** → **Repository Secrets** 添加：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DRIVER` | nonebot2 驱动，**必填**，填 `~fastapi` | 留空（会导致启动崩溃） |
| `ONEBOT_ACCESS_TOKEN` | NapCat ↔ NoneBot WS 认证 Token | 留空（不启用认证） |
| `TARGET_GROUPS` | 每日推荐推送的目标群号 | 留空（不推送） |
| `WEBUI_TOKEN` | NapCat WebUI 管理密码 | **启动时随机生成 24 位**，见启动日志 |
| `ACCOUNT` | 指定 QQ 账号自动登录（可选） | 留空（手动扫码） |
| `SPACE_URL` | 防休眠自 ping 的 Space URL（可选，默认由 HF `SPACE_HOST` 推导） | 自动推导 |

> 环境变量请通过 **HF Settings → Variables** 配置（Docker 构建上下文会排除 `.env`，README 中随代码推送的方式不可用）。
>
> ⚠️ **`DRIVER` 必填**：`.env` 被 `.dockerignore` 排除、不会进镜像，容器里缺它时 nonebot2 会在启动第一步读 stdin 询问驱动并崩掉，表现为「Space 反复重启、日志里没有业务错误」。
>
> ⚠️ **`WEBUI_TOKEN` 默认随机生成**，并在启动日志里打印一次（HF Space 日志仅所有者可见）。首次扫码登录需要去 Container Logs 搜 `[start] NapCat WebUI token:` 复制。想用固定口令就显式设置该变量，同时把 Space 设为 private。

### 4. QQ 扫码登录（仅首次）

构建完成后，打开 Space URL → 自动进入 **NapCat WebUI 管理界面**：

1. 在 **Container Logs** 里搜 `[start] NapCat WebUI token:` 复制管理密码
2. 左侧导航 → **QQ登录** → **QRCode**
3. **用你的 QQ 小号** 扫码
4. 登录后在左侧 **网络配置** 确认 `bot`（WS 客户端）状态为 ✅ **已连接**
5. 已连接即表示机器人就绪

> **关于重启后是否需要重扫**：HF Spaces 磁盘是临时存储，但本项目已实现 QQ 会话快照持久化——在 Space Settings 挂载一个**私有** Storage Bucket 到 `/data`（read-write）并配置 `ACCOUNT` 后，容器重启会自动从快照恢复会话并快登，无需重新扫码。
> **未挂载 bucket** 时该机制静默跳过，行为退回「每次重启都要重新扫码」。
> 快照里包含 QQ 登录凭证，**bucket 必须是私有的**。即使挂了 bucket，腾讯风控强制验证时仍可能需要人工扫码，这属预期边界。

### 5. 验证

在 QQ 群发送以下命令测试：

```
/jm help    → 应返回命令列表
/jm 438516  → 下载示例本子（首次下载约 1-3 分钟）
```

### 防休眠

HF Spaces 免费版 48h 无活动会休眠，本项目已内置双保险保活：

- **GitHub Actions**：`.github/workflows/keepalive.yml` 每 24 小时 ping 一次 Space URL（需将 workflow 推送到 GitHub 仓库）
- **bot 内自 ping**：`jm_scheduler.py` 每 24 小时请求一次 Space 公网入口（`SPACE_URL` 环境变量可覆盖，默认 `https://你的用户名-jmcomic-qq-bot.hf.space`），随 bot 自动运行，无需外部服务
- **UptimeRobot（可选）**：每 30 分钟 ping `https://你的用户名-jmcomic-qq-bot.hf.space`

## 命令参考

### 下载

| 命令 | 说明 | 示例 |
|---|---|---|
| `/jm <ID>` | 下载本子，默认 PDF 格式 | `/jm 438516` |
| `/jm <ID> --zip` | 下载并打包为 ZIP（自动压缩源图，体积约省 10-20%） | `/jm 438516 --zip` |
| `/jm <ID> --longimg` | 下载并拼接为长图 | `/jm 438516 --longimg` |
| `/jm p<ID>` | 下载单个章节（仅 PDF） | `/jm p350234` |

### 查询

| 命令 | 说明 | 示例 |
|---|---|---|
| `/jmv <ID>` | 查看本子详情（含封面图 + 相关推荐） | `/jmv 438516` |
| `/jms <关键词>` | 搜索本子 | `/jms 无修正` |
| `/jmc <ID> [页码]` | 查看本子评论 | `/jmc 438516` `/jmc 438516 2` |
| `/mv <番号>` | 搜索番号并返回磁力链接 | `/mv SSNI-123` |
| `/mv <番号> --page N` | 翻页 | `/mv SSNI-123 --page 2` |

### 推荐

| 命令 | 说明 | 示例 |
|---|---|---|
| `/jm rank [周/月/日]` | 排行榜（默认周榜） | `/jm rank 月` |
| `/jm random` | 随机推荐一本 | `/jm random` |
| 每日 9:00 自动推送 | 随机推荐到群 | 需配置 `TARGET_GROUPS` |

### 帮助

| 命令 | 说明 |
|---|---|
| `/jm help` | 查看全部命令 |

## 配置说明

### `.env`（NoneBot2 + 机器人）

| 变量 | 说明 |
|---|---|
| `DRIVER` | NoneBot2 驱动（必须 `~fastapi`） |
| `HOST` / `PORT` | WS 服务器监听地址 |
| `COMMAND_START` | 命令前缀（默认 `["/"]`） |
| `ONEBOT_ACCESS_TOKEN` | WS 连接认证 Token |
| `TARGET_GROUPS` | 每日推荐推送群号，逗号分隔（留空则不推送） |

### `option.yml`（jmcomic 下载配置）

```yaml
dir_rule:
  base_dir: /tmp/jm_dl/
  rule: Bd_Aid_Pid       # 每章节独立目录（Bd_Aid 扁平目录会导致多章节导出内容重复）

client:
  impl: api             # 必须用 api（移动端 API），HF 海外节点无法访问 HTML 页面
  async_impl: async_api
  cache: false          # 关闭 jmcomic 内存缓存（bot 已有 30 分钟文件缓存层）
  retry_times: 3
  proxies: null         # 显式禁用系统代理
  postman:
    meta_data:
      timeout: 30

download:
  cache: true           # 图片下载缓存（防重下）
  threading:
    image: 2
  image:
    suffix: .jpg
    decode: true       # webp → JPEG 解码（必须 true，否则 PDF 图片破碎）
```

> 格式配置（PDF/ZIP/长图）通过代码传入 `Feature.export_*`，不写在 option.yml 的 plugin 段。

### 文件格式切换

使用 `--zip` 或 `--longimg` 参数切换输出格式：

```
/jm 438516          # PDF（默认）
/jm 438516 --zip    # ZIP 压缩包
/jm 438516 --longimg # 拼接长图
```

## 架构

```
NapCatQQ (QQ协议层) ──WS──→ NoneBot2 (消息路由) ──→ jmcomic (下载引擎)
     │                              │
     └── WebUI (7860)               ├── /jm      → 下载 + 格式导出
                                     ├── /jmv/jms → 查询
                                      ├── /mv      → MissAV+JavDB+jav321 三源合并 + Sukebei 磁力链
                                      └── 每日 9:00 → 自动推荐
```

- **NapCatQQ**: NTQQ 官方协议实现，负责 QQ 消息收发，提供 WebUI 管理界面
- **NoneBot2**: 异步消息路由框架，处理命令分发
- **jmcomic**: 禁漫天堂下载引擎。**元数据查询走原生 async client**（`async_impl: async_api`）直接 `await`；**下载走原生 `JmAsyncDownloader` 异步下载器**；`run_in_executor`（`src/_common.py`）现在只剩 `/mv` 的 Scrapling 同步搜索在用

端口映射：
- `7860` — HF Spaces 默认端口 → NapCat WebUI
- `8080` — 内部 WS 服务器（NoneBot2 ↔ NapCat）

## 故障排查

| 现象 | 可能原因 | 解决 |
|---|---|---|
| Space 构建失败 | Docker build 超时 / OOM | 重试构建，检查 Builder Logs |
| 打开 Space 看不到 WebUI | 容器未就绪 / Python 未启动 | 等 2 分钟刷新，检查 Container Logs |
| WebUI 的 WS 客户端「未连接」 | ONEBOT_ACCESS_TOKEN 不匹配 | 确认 HF Variables 里的 `ONEBOT_ACCESS_TOKEN` 已设置，且与 NapCat WebUI 网络配置里的 access token 一致（容器内没有 `.env`，改本地文件无效） |
| QQ 扫码后闪退 | 账号风控 / NTQQ 兼容性 | 换一个小号，或更新 napcat-docker 镜像版本 |
| `/jm` 命令返回超时 | 禁漫API 请求超时 | HF 海外节点正常，无需代理；若持续可重试 |
| `/jm` 返回「文件未找到」 | 生成阶段错误 | 检查 Container Logs 中 jmcomic 报错 |
| Space 反复重启，日志无业务错误 | `DRIVER` 未配置 | HF Variables 里加 `DRIVER=~fastapi`，见上文步骤 3 |
| `/jm` 群内重复下载两次 | NapCat 上传完成回放假消息（同 message_id） | 已修复（message_id 去重 + 冷却兜底），pull 最新代码 |
| 每日 9:00 未推送 | `TARGET_GROUPS` 未配置 | 添加群号到环境变量 |

## 文件结构

```
JMComic-QQ-Bot/
├── bot.py                 # NoneBot2 启动入口
├── config/
│   └── onebot11.json      # NapCat WS 客户端配置
├── option.yml             # jmcomic 下载配置
├── requirements.txt       # Python 依赖
├── Dockerfile             # HF Spaces Docker 构建
├── start.sh               # 容器启动入口
├── .env                   # 环境变量（已 gitignore，仅本地开发用）
├── .env.example           # 环境变量模板
├── pyproject.toml         # 项目配置
├── LICENSE
├── README.md              # 本文件
├── AGENTS.md              # AI 助手上下文（架构/坑/编码规范）
├── CHANGELOG.md           # 变更日志
├── CONTRIBUTING.md        # 贡献指南
├── SECURITY.md            # 安全策略（可选）
├── .gitignore
├── .dockerignore
├── scripts/
│   └── session_keeper.py  # QQ 会话快照 restore/backup/watch（仅标准库）
├── src/
│   ├── _common.py        # run_sync 共享函数
│   ├── jm_option.py      # jmcomic option 双检锁缓存
│   └── plugins/
│       ├── __init__.py
│       ├── jm_info.py    # 查询命令（/jmv /jms）
│       ├── jm_comment.py # 评论命令（/jmc）
│       ├── jm_sauce.py   # 以图搜源（/ss）
│       ├── jm_scheduler.py # 定时推荐 + 缓存清理 + 自 ping
│       ├── jm/           # /jm 命令包
│       │   ├── __init__.py
│       │   ├── cmd.py
│       │   ├── handler.py
│       │   ├── album.py
│       │   ├── photo.py
│       │   ├── upload.py
│       │   ├── progress.py
│       │   ├── compress.py  # zip 源图压缩 Feature（自定义 Feature 示例）
│       │   └── common.py
│       └── mv/           # /mv 命令包
│           ├── __init__.py
│           ├── cmd.py
│           ├── handler.py
│           ├── _search.py
│           ├── _search_missav.py
│           ├── _search_javdb.py
│           └── _torrent.py
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── feature_request.md
│   ├── workflows/
│   │   └── keepalive.yml   # 每 24h ping Space URL 防休眠
│   └── PULL_REQUEST_TEMPLATE.md
└── .codegraph/            # 代码图谱索引（AI 开发辅助）
```

## 开发指南

```bash
# 安装依赖
pip install -r requirements.txt

# 启动（需已安装 napcat 或 mock 环境）
python bot.py
```

### 本地调试

1. 安装 [NapCatQQ](https://github.com/NapNeko/NapCatQQ) 或使用已有的 QQ 客户端
2. 配置 WS 客户端指向 `ws://127.0.0.1:8080/onebot/v11/ws`
3. 启动 bot.py
4. 可选：从本地 jmcomic 源码安装以联调

```bash
pip install -e path/to/JMComic-Crawler-Python
```

## 依赖

- [NapCatQQ](https://github.com/NapNeko/NapCatQQ) — NTQQ 协议实现
- [NoneBot2](https://nonebot.dev) — 异步消息框架
- [jmcomic](https://github.com/hect0x7/JMComic-Crawler-Python) — 禁漫天堂下载引擎
- 基镜像 [mlikiowa/napcat-docker](https://github.com/NapNeko/NapCatQQ) — Docker 运行环境封装

## 许可证

[MIT](LICENSE)
