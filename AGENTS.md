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
                                      ├── /mv       → MissAV+JavDB+jav321 三源合并 + Sukebei 磁力链
                                      └── 每日 9:00  → APScheduler → month_ranking → 群推送
```

架构翻转：NoneBot2 做 WS 服务器（`:8080`），NapCat 做 WS 客户端连接。

## 关键文件

| 文件 | 作用 |
|---|---|---|
| `bot.py` | NoneBot2 入口，显式 `load_plugin("plugins.jm"/"plugins.mv"/...)` 加载（**勿用 `load_plugins("src/plugins")`**，见双命名空间坑） |
| `.env` | `DRIVER=~fastapi`, `HOST=0.0.0.0`, `PORT=8080`, `COMMAND_START=["/"]`, `TARGET_GROUPS` |
| `config/onebot11.json` | NapCat WS 客户端 → `ws://127.0.0.1:8080/onebot/v11/ws` |
| `src/plugins/jm/` | `/jm` 命令包 — `cmd.py`(on_command 注册), `handler.py`(路由), `album.py`(本子下载), `photo.py`(单章), `upload.py`(二级上传fallback), `progress.py`(取消信号下载器), `compress.py`(zip 源图压缩 Feature), `common.py`(公共工具+锁/冷却/缓存) |
| `src/plugins/mv/` | `/mv` 命令包 — `cmd.py`(on_command 注册), `handler.py`(路由+磁链聚合), `_search.py`(三源并行 coordinator), `_search_missav.py`(StealthyFetcher), `_search_javdb.py`(StealthyFetcher), `_torrent.py`(Sukebei磁力) |
| `src/plugins/jm_info.py` | `/jmv` 详情（封面图+相关推荐） + `/jms` 搜索 |
| `src/plugins/jm_comment.py` | `/jmc` 评论（`album_pagination`，需 jmcomic ≥2.7.3） |
| `src/plugins/jm_scheduler.py` | 每日 9:00 随机推荐（APScheduler + `TARGET_GROUPS`）+ 每 5 分钟缓存清理 + 每 24 小时 Space 自 ping 防休眠 |
| `.github/workflows/keepalive.yml` | GitHub Actions 每 24 小时 ping HF Space URL 防休眠（与 bot 内自 ping 双保险） |
| `src/jm_option.py` | jmcomic option 双检锁缓存 |
| `option.yml` | jmcomic 配置（`impl: api` + `cache: false` + `proxies: null`，无 plugin 段，格式由 Feature 传入） |
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

### 双命名空间导致 handler 双注册（重复执行的隐藏根因）
- `load_plugins("src/plugins")` 以 CWD 为基准生成模块名 `src.plugins.jm`，而包内 `from plugins.jm.xxx import ...` 绝对导入触发第二个命名空间 `plugins.jm` → `handler.py` 执行两次 → 同一 matcher 上注册两个 handler
- 下载成功路径不 finish，handler#2 完整重跑 → 重复上传（NapCat 回吐只是另一条路径）
- 修复：`bot.py` 显式 `nonebot.load_plugin(f"plugins.{name}")` 循环加载，与包内绝对导入命名空间一致
- 单文件插件（jm_info/jm_comment/jm_scheduler）内的 `from plugins.jm.common import ...` 依赖加载顺序，勿改

### Dockerfile / start.sh
- 基镜像 `mlikiowa/napcat-docker` 有 `ENTRYPOINT ["bash", "entrypoint.sh"]`，必须用 `ENTRYPOINT []` 清掉；镜像固定 `:v4.18.7`，勿改回 `:latest`（上游漂移会破坏构建）
- `NapCat.Shell.zip` 在 Dockerfile 构建时已解压到 `/app/napcat/`，`start.sh` 仅在 `napcat.mjs` 缺失时兜底解压
- Docker 中实际运行的 jmcomic 不是 `requirements.txt` 的版本：`pip install --force-reinstall --no-deps "jmcomic @ git+...@e3c7e40"`（钉 commit，获取 P0 修复且保证可复现；升级 jmcomic 须改 commit 并跑上游 tests）
- StealthyFetcher 需 Chromium：`ENV PLAYWRIGHT_BROWSERS_PATH=/app/.cache/ms-playwright` 后 `pip install "playwright==1.61.0" "patchright==1.61.2" && python -m playwright install chromium && python -m patchright install chromium`（两个 install 都跑：patchright 与 playwright 的 chromium revision 可能不同，共用路径同 revision 幂等；路径必须与运行期一致——gosu napcat 的 HOME=/app，构建期默认 HOME=/root 会错位导致浏览器找不到）
- **浏览器层在 pip 层之前**（只依赖 venv 层）：requirements.txt 变更不触发 Chromium 重下（省 ~2.5min/次）；apt 层一次性装齐 chromium 系统依赖（勿用 `install-deps`，它会再跑一轮 apt 下载 ubuntu 源，HF 构建器访问该源极慢）
- `nonebot2` 须安装 `[fastapi]` extras（纯包缺 fastapi）
- `/app/.config/QQ/NapCat/temp` 权限：需 `mkdir + chown napcat:napcat`
- `FFMPEG_PATH` 声明后须 `apt-get install ffmpeg`
- `start.sh` 用 `set -u` 但**不用** `set -e`（前后台进程并存）；`WEBUI_TOKEN` 默认固定 `jmcomic`（不随机，可被环境变量覆盖，QQ 扫码登录后 NapCat 可能强制改密一次）写入后即 `unset`；`ONEBOT_TOKEN` 先备份到 `ONEBOT_TOKEN_BACKUP` 再 unset，供配置注入使用（NoneBot 适配器读 `ONEBOT_ACCESS_TOKEN`，勿用旧名 `ONEBOT_TOKEN`）；SIGTERM trap 负责优雅关闭；`sync_onebot11_config` 后台循环按账号同步配置
- `ENV TZ=Asia/Shanghai`（否则 cron 按 UTC，每日推荐会在北京 17:00 推送）
- 容器 HEALTHCHECK 探测 `http://127.0.0.1:7860`（NapCat WebUI），不是 8080（NoneBot 无根路由，探测会恒 404）

### jmcomic 同步 API 阻塞防护
- jmcomic 是同步库而 NoneBot2 是 async event loop：同步调用（MV `search_video`、httpx 请求）必须经 `run_sync`（`src/_common.py`，默认 180s）+ `wait_for(timeout)`
- async client 查询（`get_album_detail`/`ranking`/`search_site`/`album_pagination`，`async_impl: async_api`）直接 `await` + `wait_for`，不要再套 `run_sync`
- **下载走 `JmAsyncDownloader`（jmcomic ≥2.7.0），不再用 run_sync 跑同步下载器**：`progress.py` 子类化 `JmAsyncDownloader`（`async def before_photo` 检查 `cancel_event` 设 `photo.skip`），`_download_entity` 里 `async with dler` + `await asyncio.wait_for(_dl(), dl_timeout)`；超时即取消协程，async-with 保证 client/decode 池清理，无孤儿线程
- `JmAsyncDownloader` 继承 `BaseDownloader`，`add_features`/`raise_if_has_exception` 均在基类，Feature 导出经 `_run_in_decode_pool(super().after_album)` 照常触发；`async with dler` 创建独立 async client（不再共享 option 的同步 client）
- MV 搜索并行化：`_search.py` 三站改为 `concurrent.futures.ThreadPoolExecutor(max_workers=3)` 并行执行，每站独立超时互不阻塞
- MV seeders/leechers 取反修复：Sukebei 表 `cols[-3]=seeders`、`cols[-2]=leechers`
- MV 磁链搜索多格式兜底（`mv/handler.py`）：先搜原始（`PRED-485`）再搜去分隔（`pred485`），无短横输入时反推标准格式，三 query 并行（`asyncio.gather`），结果按 BTIH 去重合并
- MV 资源控制：全局 `_mv_search_semaphore = Semaphore(2)` 限制并发 Chromium；三源结果 30min 内存缓存（`_av_info_cache`，翻页只重跑 sukebei 不重跑 Chromium）；每用户 15s 冷却 key `f"{user_id}:mv:{code}"`（仅三源搜索占用，缓存命中翻页不占）；StealthyFetcher fetch 必须传 `retries=1`（默认 3 次会让超时弃置后的孤儿浏览器多活 ~2 分钟）；**勿设 `adaptive=True`**（无效配置，每次 fetch 还会建 sqlite storage 连接写库）
- 并发控制：全局 `asyncio.Semaphore(2)` 控制并发下载数
- `wait_for` 超时后底层线程无法取消（Python 线程语义），可能游离。已移除超时重试循环避免并发写
- 进度展示：下载前一次性展示本子详情（`album.py` 直接发送），不再通过下载器回调逐章推送
- `ProgressJmDownloader` 子类化 `JmDownloader`，仅覆盖 `before_photo` 用于检查取消信号（`cancel_event.is_set()` 时跳过该章节），无进度推送逻辑

### jmcomic Feature 机制
- 格式（PDF/ZIP/长图）通过 `Feature.export_*` 作为 `extra` 参数传入，不写在 `option.yml` plugin 段
- `after_album` 下 `photo=None`，`filename_rule` 必须与缓存命名空间对齐：album 用 `'a{Aid}'`、photo 用 `'p{Pid}'`（f-string 规则，产出 `a{id}.pdf` 与 `_download_entity` 的 out_path 一致；**若只改 out_path 前缀不改 filename_rule，缓存检查与导出文件名不匹配 → 下载链路必坏**，历史 P0 回归教训）
- `option.yml` 的 `dir_rule.rule` 必须含 `Pid`（`Bd_Aid_Pid`）：Bd_Aid 扁平目录下所有章节图片同目录，album 级导出插件会重复收集 N 倍（P0 数据损坏）
- **zip 源图压缩**（`compress.py`）：`CompressZipFeature() + Feature.export_zip(...)` 组合（FeatureChain 按序执行，压缩须在 zip 前）；自适应档位 (60, 50)——实测源图解码质量高（q75 仅 -2%、q60 -13%），JPEG 对 zip 二次压缩收益 ≈ 图片压缩收益
- 详见 jmcomic 库的 `AGENTS.md`（实际无此文件，约束见上游 README）

### jm_scheduler 未复用 option 缓存
- 最初 `jm_scheduler.py` 直接调用 `create_option_by_file(str(OPTION_PATH))`，与 `jm_option.py` 缓存单例不一致
- 修复：改为 `from jm_option import get_option`，与 `src/plugins/jm/` 包共享同一 option 实例

### Option 缓存永不刷新
- `jm_option.py` 的 `get_option()` 在第一次调用时缓存 `option_cache`，此后永不过期
- 修改 `option.yml` 需重启 bot 才能生效
- 未添加刷新接口（`clear_option_cache()`），按需可加

### PDF 图片破碎（`decode: false`）
- 旧 `option.yml` 有 `decode: false`，webp 未解码直接存为 `.jpg`
- img2pdf 插件读文件时当 JPEG 处理但实际内容为 WebP → PDF 内图片破碎
- 修复：`decode: true`，下载时解码 webp → JPEG

### 重复执行（NapCat 上传回吐）
- `upload_group_file` 上传文件后，NapCat 将文件消息回吐为一条新的 `message` 事件
- **self_id 过滤无效**：NapCat 回放消息的 `user_id` 与原始用户**完全相同**（不是 bot 自身 ID），`if event.user_id == int(bot.self_id)` 挡不住
- 第一次尝试（`1fc6130`）加 `self_id` 过滤 → 未解决
- 诊断日志（`1387cc5`）证实回放消息 user_id 冒充原始用户
- Timer 延迟锁（`5ff9271`）：`_unlock_album` 改为 `threading.Timer(15, _delayed_unlock)` → 被 NapCat 回放时间波动突破
- **最终根治**（`message_id` 去重 + 冷却兜底）：
  - `_is_dup_message(event.message_id)`：`_seen_message_ids` 字典记录已处理的 `message_id`，毫秒级丢弃同 ID 重复（NapCat 回放 === 同一 message_id）
  - 15s 冷却 `f"{user_id}:{album_id}"`：不同 ID 的回放（极少见）由冷却兜底
  - 处理锁（`_processing_albums`）仅保护并发安全，`_unlock_album` **立即释放**，不再延迟
  - 移除 `threading.Timer(15, _delayed_unlock)`，避免延迟锁阻塞正常用户

### Album 处理锁
- 三层保护：处理锁 + message_id 去重 + cooldown
- 处理锁 key = `album_id`（不含 user_id）：不同用户并发下载同一本子不互斥
- 冷却 key = `f"{user_id}:{album_id}"`：仅限制同一用户对同一本子的频率
- `_try_lock_album_by_aid` 检查 `_processing_albums` 集合，立即返回 False 忽略重复
- `_unlock_album_by_aid` **立即**释放（无延迟），`try/finally` 保证
- photo 下载使用独立前缀 `p:{photo_id}`，与 album 锁互不干扰

### 动态下载目录
- 新增 `_get_dl_tmp()` 从 option 读取 `dir_rule.base_dir`，替代硬编码 `/tmp/jm_dl/`
- upload.py 同步使用 `_get_dl_tmp()`

### MissAV/JavDB URL 格式
- 禁漫搜索返回的番号是归一化格式（`mdbk00331`），MissAV/JavDB 需要带连字符的格式（`MDBK-331`）
- 修复：`_search_missav.py` / `_search_javdb.py` 中用 regex 还原 `{PREFIX}-{NUM}`

### 部署
- 首次部署需通过 NapCat WebUI 扫码登录 QQ 小号
- HF Spaces 磁盘为临时存储，Space 重启后需重新扫码
- 端口中：7860（HF Spaces 默认 → WebUI）、8080（内部 NoneBot WS 服务器）
- 防休眠：双保险 — GitHub Actions（`.github/workflows/keepalive.yml`，每 24h 一次，推 GitHub main 生效）+ bot 内 `space_keepalive` job（每 24h，`SPACE_URL` 环境变量可覆盖默认 URL）；HF 休眠窗口 48h，两者互备，任一失效 48h 后会休眠
- 休眠后首次 ping 需冷启动（1-2 分钟），keepalive curl 已带 `--retry 3 --retry-delay 20` 兜底

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
| `/jmc <ID> [页码]` | 查看本子评论 | `/jmc 438516 2` |
| `/mv <番号>` | 搜索番号（三源并行: MissAV+JavDB+jav321 + Sukebei 磁力链）返回磁力链接 | `/mv SSNI-123` |
| `/mv <番号> --page N` | 翻页 | `/mv SSNI-123 --page 2` |
| 每日早 9:00 | 自动推送随机推荐 | 需 `.env` 配置 `TARGET_GROUPS` |

### 限制与行为
- 15 秒冷却 key = `f"{user_id}:{album_id}"`；单章 `p{photo_id}`、`rank:{period}`、`random`、`jmc:{album_id}:{page}`、`jmv:{album_id}`、`jms:{关键词}`、`mv:{归一化番号}` 各自独立 key（help 无冷却；jmc 冷却含页码，否则翻页被冷却阻断；mv 冷却仅三源搜索占用，缓存命中翻页不占）
- 缓存文件带命名空间前缀：album=`a{id}.{ext}`、photo=`p{id}.pdf`（`_make_out_path` 由 `cache_prefix` 参数控制，导出侧 `filename_rule` 同步用 `a{Aid}`/`p{Pid}`），避免 photo_id 与 album_id 数字碰撞互串；上传显示名仍为 `JM{id}.{ext}`
- 下载清理目标从实体推导：album 用 `option.dir_rule.decide_album_root_dir(entity)`，photo 用 `option.decide_image_save_dir(entity).parent`（Bd_Aid_Pid 下二者均为 `{base}/{album_id}`），勿再按 entity_id 拼目录
- 部分下载失败（`PartialDownloadFailedException`）：产物已生成则提示缺图并照常上传，不再删除/清冷却
- `_is_cache_valid` 校验 `st_size > 0`（防 0 字节坏 PDF 被缓存命中）；下载失败/超时分支先清 `out_path` + `dl_dir` 再 finish；下载前也清残留 dl_dir（防孤儿线程旧文件被 `download.cache` 误判跳过）
- message_id 去重 TTL 600s（覆盖 300s 下载 + 120s 上传最长窗口）；处理锁冲突时 `finish("正在下载中")` 并清冷却，不再静默丢弃
- `/jm` 参数严格校验：仅接受 `p\d+` / 纯数字 / rank / random / help（`/jmx 438516`、`/jm 123 456` 一律格式提示，防误触发下载）
- 下载前一次性展示本子详情（名称/作者/章节/页数/标签），不再发逐章进度
- 下载超时直接结束（无自动重试，避免竞态），jmcomic 内部已有 3 次重试；async 下载器超时后协程被取消，无残留线程
- 30 分钟短时缓存（`/tmp/jm/{a|p}{id}.ext`），APScheduler 每 5 分钟定时清理过期缓存和残留下载目录（`/tmp/jm_dl/`）
- 清理同时处理目录和文件（不再仅限目录）
- 下载后自动清理原始图片（`/tmp/jm_dl/{id}/`），通过 `finally` 块保证（`rmtree` 已移入 executor，不再阻塞事件循环）

## 代码约定

- 命令注册与路由分离：`cmd.py` 定义 `on_command`（`priority=10`, `rule=is_type(GroupMessageEvent)`），`handler.py` 处理逻辑，`__init__.py` 里 `from . import handler` 完成装载；`bot.py` 用 `nonebot.load_plugin(f"plugins.{name}")` 循环加载（勿用 `load_plugins("src/plugins")`，见双命名空间坑）
- 所有群命令只响应 `GroupMessageEvent`（`is_type` 规则）
- `jm_info.py` / `jm_comment.py` / `jm_scheduler.py` 是单文件插件，直接在文件内 `on_command` / `scheduler.scheduled_job`，无 cmd.py
- 无测试套件、无 linter/CI 配置；验证手段为 `python -m py_compile` + 本地 `python bot.py` 启动


