# Changelog

## [0.2.0] — 2026-07-04

### 修复
- `/jm` 群内重复执行（NapCat 回放绕过 self_id 过滤）：`_unlock_album` 延迟 15s 释放处理锁，`threading.Timer` 覆盖 NapCat 回放窗口
- PDF 图片破碎：`decode: false` → `true`，webp 解码后再生成 PDF
- 过滤 bot 自身消息回吐导致 `/jm` 重复执行（`handler.py` 入口 `self_id` 过滤）
- 处理锁在 handler 重复进入时未防止 NapCat 回放（`album-level lock` + `_try_lock_album`）

### 重构
- `src/__init__.py` 完善包结构
- 移除 handler.py 入口 `_req_id` 诊断日志（根因已确认）

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
