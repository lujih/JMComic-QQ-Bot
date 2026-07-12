# Changelog

## [Unreleased]

### 修复
- MV 封面下载：`resp.close()` 在 `resp.content` 前调用 → 改读后关
- MV 搜索超时链断裂：外层 30s 内层 45s → 三站并行 + 独立超时 + 120s 兜底
- MV Sukebei seeders/leechers 取反（`cols[-2]` 拿到 leechers）
- Docker 基镜像 `:latest` → `v4.18.7` 固定版本
- Docker scrapling 全浏览器安装 → 仅 chromium
- `start.sh` trap 补充 INT/QUIT/HUP；ONEBOT_TOKEN 写入后 unset
- `pyproject.toml` build-backend 私有模块 → 公开 API
- Docker HEALTHCHECK 30s → 120s
- Sukebei 无短横输入反推标准格式（`pred485`→`PRED-485`）

### 架构
- MV 搜索三站串行 → 并行（`concurrent.futures.ThreadPoolExecutor`）
- `network_idle=True` → `False`（避免等待广告/长轮询超时）
- `_cleanup_stale_dirs` 改为同时清理文件+目录，而非仅目录
- album/photo 处理锁分离命名空间（`p:` 前缀）

### 安全
- WEBUI_TOKEN 日志截断 → 用户需要又恢复完整打印（HF Spaces 环境仅 Space 所有者可见）
- ONEBOT_TOKEN 写入配置后 `unset`

## [0.2.0] — 2026-07-04

### 修复
- `/jm` 群内重复执行（NapCat 回放绕过 self_id 过滤）：`message_id` 去重 + 15s 冷却兜底，移除 `threading.Timer` 延迟锁
- PDF 图片破碎：`decode: false` → `true`，webp 解码后再生成 PDF
- 处理锁在 handler 重复进入时未防止 NapCat 回放（`album-level lock` + `_try_lock_album`）

### 重构
- `src/__init__.py` 完善包结构
- 移除 handler.py 入口 `_req_id` 诊断日志（根因已确认）
- `Semaphore(3)` → `(2)`，`ThreadPoolExecutor(8)` → `(4)`（适配 2 vCPU）
- `_cleanup_stale_dirs` 从请求前调用 → APScheduler 每 5 分钟定时
- `is_cache_valid` 移到 `_semaphore` 外（缓存命中不阻塞并发下载）

## [0.1.0] — 2026-07-04

### 新增
- 基础 `/jm` 下载命令（PDF/ZIP/长图）
- `/jmv` 查看详情 + `/jms` 搜索本子
- `/mv` 番号搜索（MissAV + JavDB + jav321 三源合并，Sukebei 磁力链）
- 每日 9:00 APScheduler 自动推荐推送
- Album-level processing lock 防重复执行
- 双级上传（`upload_group_file` → `upload_file_stream` fallback）
- `ProgressJmDownloader` 子类化支持取消信号

### 修复
- PDF 图片破碎：`decode: false` → `true`，webp 解码后再生成 PDF
- `/jm` 群内重复执行：NapCat 上传回吐被 bot 自身消息过滤
- MissAV/JavDB URL 404：归一化番号还原带连字符格式
- date/duration 字段串扰：`following-sibling::text()` → `text()[1]`
- 封面图三斜杠：`urljoin` 基地址修复
- `_DL_TMP` 硬编码 → 动态读取 option 的 `dir_rule.base_dir`
- Rank/random 异常路径 missing `_clear_cooldown`
- `album.oname` 可能的 None 值保护

### 重构
- BS4 → scrapling（StealthyFetcher 过 CF）
- MV 搜索拆分为三源 coordinator 模式
- 冷却从 per-user 改为 per-album（15s）
- 磁链全源合并（MissAV+JavDB+jav321+Sukebei，BTIH 去重，死種过滤）
- `src/__init__.py` 完善包结构

### 依赖
- nonebot2 `<2.5.0` 上限
- Pillow `>=10.4.0`
- httpx `>=0.28.0`
