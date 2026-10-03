"""PicImageSearch 引擎集成：以图搜源的增强源（SauceNAO / IQDB / E-Hentai）。

为什么引入：原 /ss 只有 Ascii2d / SoutuBot / trace.moe / Yandex 四源，
对「番剧截图」「本子封面」这类图的召回不够。PicImageSearch（MIT, github.com/kitUIN/PicImageSearch）
聚合了 16 个引擎，且 SauceNAO / IQDB 的结果自带 `similarity` 相似度分数，
可以据此排序——这是原实现完全缺失的能力。

设计要点：
- 依赖用 try/except 保护。PicImageSearch 是可选增强，缺了不影响原有四源工作
- 每个引擎独立 try，由调用方 `_safe` 统一兜住，单源失败不影响其它源
- 只取有 similarity 的引擎做置信度排序，无分数的（e-hentai）按原顺序附在后面
"""

from typing import Any

from jmcomic import jm_log

# 低于此相似度的结果直接丢弃：SauceNAO 低于 ~55% 基本是「同色调但不同图」的噪音
SIMILARITY_MIN = 55.0
# 每源最多取几条，避免刷屏
MAX_PER_ENGINE = 4

# 引擎名 -> PicImageSearch 类名
_ENGINE_CLASSES = ("SauceNAO", "Iqdb", "EHentai")


def _load_lib():
    """惰性导入 PicImageSearch。未安装时返回 None，调用方降级而非报错。"""
    try:
        import PicImageSearch
        return PicImageSearch
    except ImportError as e:
        jm_log('jm.sauce.pic', 'PicImageSearch 未安装，跳过增强源', e)
        return None


def _sim_of(item: Any) -> float | None:
    """取结果的相似度分数；各引擎字段略有差异，取不到返回 None。"""
    for attr in ("similarity", "similarity_percent"):
        v = getattr(item, attr, None)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _to_dict(item: Any, engine: str) -> dict:
    """把引擎结果压成与原有四源一致的 dict 结构。"""
    return {
        "engine": engine,
        "title": (getattr(item, "title", "") or "").strip(),
        "url": (getattr(item, "url", "") or "").strip(),
        "thumbnail": (getattr(item, "thumbnail", "") or "").strip(),
        "author": (getattr(item, "author", "") or "").strip(),
        "similarity": _sim_of(item),
    }


async def search_enhanced(img_bytes: bytes, probe_url: str = "") -> list[dict]:
    """跑 PicImageSearch 的增强源，返回带 similarity 的结果列表。

    返回项已按 similarity 降序排好；无分数的结果排在后面。
    调用方需要自己用 asyncio.wait_for 包超时——本函数不设全局超时，
    因为各引擎耗时不齐，交给上层统一控制更合适。
    """
    lib = _load_lib()
    if lib is None:
        return []

    Network = lib.Network
    results: list[dict] = []

    async with Network(timeout=25) as _:
        # SauceNAO：动漫/插画/ pixiv 图库的事实标准，similarity 权威
        if hasattr(lib, "SauceNAO"):
            try:
                engine = lib.SauceNAO(api_key=None, numres=MAX_PER_ENGINE, minsim=int(SIMILARITY_MIN))
                resp = await engine.search(img_bytes)
                results += [
                    _to_dict(it, "SauceNAO")
                    for it in (resp or [])[:MAX_PER_ENGINE]
                    if (_sim_of(it) or 0) >= SIMILARITY_MIN
                ]
            except Exception as e:
                jm_log('jm.sauce.pic', 'SauceNAO 查询失败', e)

        # IQDB：danbooru/gelbooru 等番剧图库聚合，对二次元截图召回好
        if hasattr(lib, "Iqdb"):
            try:
                engine = lib.Iqdb()
                resp = await engine.search(img_bytes)
                items = [
                    _to_dict(it, "IQDB")
                    for it in (resp or [])[:MAX_PER_ENGINE]
                    if (_sim_of(it) or 0) >= SIMILARITY_MIN
                ]
                results += items
            except Exception as e:
                jm_log('jm.sauce.pic', 'IQDB 查询失败', e)

        # E-Hentai：本子画廊站，无 similarity 分数，仅补充召回
        if hasattr(lib, "EHentai"):
            try:
                engine = lib.EHentai()
                resp = await engine.search(img_bytes)
                results += [
                    _to_dict(it, "E-Hentai") for it in (resp or [])[:MAX_PER_ENGINE]
                ]
            except Exception as e:
                jm_log('jm.sauce.pic', 'E-Hentai 查询失败', e)

    # 有分数的在前（降序），无分数的按引擎原顺序附后
    scored = [r for r in results if r["similarity"] is not None]
    unscored = [r for r in results if r["similarity"] is None]
    scored.sort(key=lambda r: r["similarity"], reverse=True)
    return scored + unscored