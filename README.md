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
| `/mv <番号>` | 搜索番号并返回磁力链接（MissAV 标题 + Sukebei 做种） |
| `/sign` | 每日签到获取积分（5~99 随机） |
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
| `ONEBOT_TOKEN` | NapCat ↔ NoneBot WS 认证 Token | 留空（不启用认证） |
| `TARGET_GROUPS` | 每日推荐推送的目标群号 | 留空（不推送） |
| `WEBUI_TOKEN` | NapCat WebUI 管理密码 | `jmcomic` |

或在 `.env` 文件中配置后随代码推送。

### 4. QQ 扫码登录（仅首次）

构建完成后，打开 Space URL → 自动进入 **NapCat WebUI 管理界面**：

1. 左侧导航 → **QQ登录** → **QRCode**
2. **用你的 QQ 小号** 扫码
3. 登录后在左侧 **网络配置** 确认 `bot`（WS 客户端）状态为 ✅ **已连接**
4. 已连接即表示机器人就绪

> 登录信息持久化于 `/app/.config/QQ`。Space 48 小时内重启自动恢复，无需重复扫码。
> 若 Space 因 48h 无活动被回收，需重新扫码。

### 5. 验证

在 QQ 群发送以下命令测试：

```
/jm help    → 应返回命令列表
/jm 438516  → 下载示例本子（首次下载约 1-3 分钟）
```

### 防休眠

HF Spaces 免费版 48h 无活动会休眠，可选：

- **升级实例**：CPU 升级（$7.2/月）→ 始终在线
- **监控 Ping**：使用 [UptimeRobot](https://uptimerobot.com) 每 30 分钟 ping `https://你的用户名-jmcomic-qq-bot.hf.space`
- **内部保活**：每次 `/jm` 命令自动清理过期残留，也有助于保持活跃

## 命令参考

### 下载

| 命令 | 说明 | 示例 |
|---|---|---|
| `/jm <ID>` | 下载本子，默认 PDF 格式 | `/jm 438516` |
| `/jm <ID> --zip` | 下载并打包为 ZIP | `/jm 438516 --zip` |
| `/jm <ID> --longimg` | 下载并拼接为长图 | `/jm 438516 --longimg` |
| `/jm p<ID>` | 下载单个章节（仅 PDF） | `/jm p350234` |

### 查询

| 命令 | 说明 | 示例 |
|---|---|---|
| `/jmv <ID>` | 查看本子详情 | `/jmv 438516` |
| `/jms <关键词>` | 搜索本子 | `/jms 无修正` |
| `/mv <番号>` | 搜索番号并返回磁力链接 | `/mv SSNI-123` |
| `/mv <番号> --page N` | 翻页 | `/mv SSNI-123 --page 2` |

### 推荐

| 命令 | 说明 | 示例 |
|---|---|---|
| `/jm rank [周/月/日]` | 排行榜（默认周榜） | `/jm rank 月` |
| `/jm random` | 随机推荐一本 | `/jm random` |
| 每日 9:00 自动推送 | 随机推荐到群 | 需配置 `TARGET_GROUPS` |

### 积分

| 命令 | 说明 | 示例 |
|---|---|---|
| `/sign` | 每日签到获取积分 | `/sign` |

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
| `ONEBOT_TOKEN` | WS 连接认证 Token |
| `TARGET_GROUPS` | 每日推荐推送群号，逗号分隔 |

### `option.yml`（jmcomic 下载配置）

```yaml
dir_rule:
  base_dir: /tmp/jm_dl/
  rule: Bd_Aid

client:
  impl: api             # 必须用 api（移动端 API），HF 海外节点无法访问 HTML 页面
  retry_times: 3
  postman:
    meta_data:
      timeout: 30

download:
  image:
    suffix: .jpg
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
                                     ├── /mv      → MissAV 搜索 + Sukebei 磁力链
                                     ├── /sign    → do_checkin（签到积分）
                                     ├── database → 配额检查 + 积分扣减
                                     └── 每日 9:00 → 自动推荐
```

- **NapCatQQ**: NTQQ 官方协议实现，负责 QQ 消息收发，提供 WebUI 管理界面
- **NoneBot2**: 异步消息路由框架，处理命令分发
- **jmcomic**: 禁漫天堂下载引擎，同步库，通过 `run_in_executor` 适配异步

端口映射：
- `7860` — HF Spaces 默认端口 → NapCat WebUI
- `8080` — 内部 WS 服务器（NoneBot2 ↔ NapCat）

## 故障排查

| 现象 | 可能原因 | 解决 |
|---|---|---|
| Space 构建失败 | Docker build 超时 / OOM | 重试构建，检查 Builder Logs |
| 打开 Space 看不到 WebUI | 容器未就绪 / Python 未启动 | 等 2 分钟刷新，检查 Container Logs |
| WebUI 的 WS 客户端「未连接」 | ONEBOT_TOKEN 不匹配 | 确认 `.env` 与 `config/onebot11.json` token 一致 |
| QQ 扫码后闪退 | 账号风控 / NTQQ 兼容性 | 换一个小号，或更新 napcat-docker 镜像版本 |
| `/jm` 命令返回超时 | 禁漫API 请求超时 | HF 海外节点正常，无需代理；若持续可重试 |
| `/jm` 返回「文件未找到」 | 生成阶段错误 | 检查 Container Logs 中 jmcomic 报错 |
| 每日 9:00 未推送 | `TARGET_GROUPS` 未配置 | 添加群号到环境变量 |

## 文件结构

```
JMComic-QQ-Bot/
├── bot.py                 # NoneBot2 启动入口
├── config/
│   └── onebot11.json      # NapCat WS 客户端配置
├── plugins/
│   ├── __init__.py
│   ├── _option.py         # jmcomic option 双检锁缓存
│   ├── jm/                # /jm 命令包（handler / album / photo / upload / progress / common）
│   ├── mv/                # /mv 命令包（handler / missav 搜索 / sukebei 磁力）
│   ├── jm_info.py         # 查询命令（/jmv /jms）
│   ├── jm_scheduler.py    # 定时推荐
│   ├── database.py        # SQLite 数据库层（签到/积分/配置）
│   └── jm_checkin.py      # /sign 签到命令
├── option.yml             # jmcomic 下载配置
├── requirements.txt       # Python 依赖
├── Dockerfile             # HF Spaces Docker 构建
├── start.sh               # 容器启动入口
├── .env                   # 环境变量（已 gitignore）
├── LICENSE
└── README.md
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
