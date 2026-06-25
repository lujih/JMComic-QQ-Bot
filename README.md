# JMComic QQ Bot — Hugging Face Spaces 部署

> 对接 QQ 机器人，群内发送 `/jm <本子ID>` 即可下载并转为 PDF 发送到群。

## 文件结构

```
qq-bot/
├── bot.py              # NoneBot2 启动入口
├── health.py           # 7860 健康状态页（含 QR 码扫码登录）
├── plugins/
│   ├── __init__.py
│   └── jm_download.py # /jm 命令插件
├── option.yml          # jmcomic 下载配置（API 客户端 + img2pdf 插件）
├── requirements.txt    # Python 依赖
├── .env                # NoneBot2 环境变量
├── Dockerfile          # HF Spaces 构建
├── start.sh            # 容器入口（Lagrange + health + bot）
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
# 克隆你的 HF Space（在 Space 页面复制 git URL）
git clone https://huggingface.co/spaces/<你的用户名>/jmcomic-qq-bot
cd jmcomic-qq-bot

# 复制 qq-bot/ 下的所有文件到空间根目录
cp -r /path/to/JMComic-Crawler-Python/qq-bot/* .
cp /path/to/JMComic-Crawler-Python/qq-bot/.dockerignore .

# 提交推送
git add -A
git commit -m "init: jmcomic qq bot"
git push
```

### 3. 扫码登录

1. 推送后 HF 会自动构建（约 2-3 分钟）
2. 构建完成后，打开 Space 页面
3. 页面会自动显示二维码
4. **用你的 QQ 小号扫码登录**
5. 登录成功后页面显示 ✅ 已登录

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

1. 升级到 **CPU - 1 vCPU**（$0.01/h ≈ $7.2/月）→ 始终在线，不限制图片大小
2. 或用 [UptimeRobot](https://uptimerobot.com) 每 30 分钟 ping `https://<你的用户名>-jmcomic-qq-bot.hf.space`

## 命令说明

| 命令 | 说明 | 示例 |
|---|---|---|
| `/jm <ID>` | 下载本子并发送 PDF | `/jm 438516` |
| `/jm help` | 显示帮助 | `/jm help` |

## 注意事项

- 必须使用 `impl: api`（移动端 API），HF 海外节点无法访问 HTML 客户端
- 单文件超过 100MB 会自动跳过（QQ 群文件上限）
- 每人每群有 60 秒冷却，防止滥用
- PDF 发送后自动清理临时文件
