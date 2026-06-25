---
title: JMComic QQ Bot
emoji: 🤖
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
---

# JMComic QQ Bot — Hugging Face Spaces 部署

> 对接 QQ 机器人，群内发送 `/jm <本子ID>` 即可下载并转为 PDF 发送到群。

基于 [NapCatQQ](https://github.com/NapNeko/NapCatQQ) + [NoneBot2](https://nonebot.dev) + [jmcomic](https://github.com/hect0x7/JMComic-Crawler-Python)。

## 文件结构

```
qq-bot/
├── bot.py              # NoneBot2 启动入口
├── health.py           # 7860 健康状态页（备用）
├── config/
│   └── onebot11.json   # NapCat WS 客户端配置 → 连接 NoneBot2
├── plugins/
│   ├── __init__.py
│   └── jm_download.py # /jm 命令插件
├── option.yml          # jmcomic 下载配置（API 客户端 + img2pdf 插件）
├── requirements.txt    # Python 依赖
├── .env                # NoneBot2 环境变量
├── Dockerfile          # HF Spaces 构建（基于 mlikiowa/napcat-docker）
├── start.sh            # 容器入口：反检测 → Xvfb → QQ后台 → NoneBot前台
└── README.md
```

## 部署步骤

### 1. 创建 HF Space

1. 登录 [huggingface.co](https://huggingface.co)
2. 点击右上角头像 → **New Space**
3. 填写：
   - **Space Name**: `jmcomic-qq-bot`
   - **License**: MIT
   - **Space SDK**: **Docker**
4. 点击 **Create Space**

### 2. 上传代码

```bash
git clone https://huggingface.co/spaces/<你的用户名>/jmcomic-qq-bot
cd jmcomic-qq-bot
cp -r /path/to/JMComic-Crawler-Python/qq-bot/* .
git add -A
git commit -m "init: jmcomic qq bot"
git push
```

### 3. WebUI 扫码登录（仅首次）

推送后 HF 会自动构建（约 3-5 分钟）。

构建完成后，打开 Space 页面 → 自动进入 **NapCat WebUI 管理界面**：

1. 点击左侧 **QQ登录** → **QRCode**
2. **用你的 QQ 小号扫码登录**
3. 登录后在 WebUI → **网络配置** 确认 `bot`（WS 客户端）状态为 **已连接**

> 首次登录后 session 持久化，除非 Space 休眠超过 48h 被回收，否则后续重启自动登录。

### 4. 使用

在任意 QQ 群发送：

```
/jm 438516
```

机器人会：
1. 下载该本子的所有图片
2. 自动合并为 PDF
3. 发送 PDF 文件到群

### 防休眠

HF Spaces 免费版 48 小时无活动会休眠。推荐：

- 升级到 **CPU - 1 vCPU**（$0.01/h ≈ $7.2/月）→ 始终在线
- 或用 [UptimeRobot](https://uptimerobot.com) 每 30 分钟 ping `https://<你的用户名>-jmcomic-qq-bot.hf.space`

## 命令说明

| 命令 | 说明 | 示例 |
|---|---|---|
| `/jm <ID>` | 下载本子并发送 PDF | `/jm 438516` |
| `/jm help` | 显示帮助 | `/jm help` |

## 注意事项

- 必须使用 `impl: api`（移动端 API），HF 海外节点无法访问 HTML 客户端
- 单文件超过 100MB 自动跳过（QQ 群文件上限）
- 每人每群 60 秒冷却
- PDF 发送后自动清理
- WebUI Token: `jmcomic`
