import re

import httpx
from bs4 import BeautifulSoup
from jmcomic import jm_log

JAV321_BASE = "https://www.jav321.com"
_TIMEOUT = 20


def _headers():
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,zh-CN;q=0.9,en;q=0.8",
    }


def search_video(query: str) -> dict:
    """Search video info from jav321.com

    Returns dict with keys: title, cover, date, actresses, studio, favorites
    Returns empty dict if not found.
    """
    code = _normalize_code(query)
    url = f"{JAV321_BASE}/video/{code}"

    html = _fetch_page(url)
    if html is None:
        html = _search_page(query)

    if html is None:
        return {}

    try:
        soup = BeautifulSoup(html, 'html.parser')
        return _parse_page(soup)
    except Exception as e:
        jm_log('mv.search', f'jav321 parse failed: {e}')
        return {}


def _fetch_page(url: str) -> str | None:
    try:
        resp = httpx.get(url, headers=_headers(), timeout=_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        jm_log('mv.search', f'jav321 request failed: {e}')
        return None
    except Exception as e:
        jm_log('mv.search', f'jav321 request failed: {e}')
        return None


def _search_page(query: str) -> str | None:
    url = f"{JAV321_BASE}/search"
    try:
        resp = httpx.post(url, data={'sn': query.strip()}, headers=_headers(), timeout=_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        jm_log('mv.search', f'jav321 search failed: {e}')
        return None


def _normalize_code(query: str) -> str:
    code = query.strip().lower()
    code = code.replace('-', '').replace('_', '')

    m = re.match(r'^(.+?)(\d+)$', code)
    if m:
        prefix, num = m.group(1), m.group(2)
        num = num.zfill(5)
        return prefix + num

    return code


def _parse_page(soup: BeautifulSoup) -> dict:
    heading = soup.select_one('.panel-heading h3')
    if not heading:
        return {}

    title = _extract_title(heading)
    if not title:
        return {}

    info = {'title': title}

    cover = _extract_cover(soup)
    if cover:
        info['cover'] = cover

    info_panel = soup.select_one('.panel-body .col-md-9')
    if not info_panel:
        return info

    for b in info_panel.find_all('b'):
        label = b.get_text(strip=True)
        if label in ('メーカー', 'Maker', 'Studio', '發行商'):
            a = b.find_next('a')
            if a:
                info['studio'] = a.get_text(strip=True)
        elif label in ('収録時間', '播放時間', '播放時長', '時長', 'Play time'):
            if b.next_sibling:
                text = str(b.next_sibling).strip().lstrip(': \t')
                info['duration'] = text
        elif label in ('配信開始日', '發售日', '發行日期', '發行日', 'Release Date'):
            if b.next_sibling:
                text = str(b.next_sibling).strip().lstrip(': \t')
                if re.search(r'\d{4}', text):
                    info['date'] = text
        elif label in ('お気に入り登録数', '收藏', '評分', '讚', '贊', 'Likes', 'Favorites'):
            if b.next_sibling:
                text = str(b.next_sibling).strip().lstrip(': \t')
                m = re.search(r'\d+', text)
                if m:
                    info['favorites'] = m.group()

    actresses = []
    for a in info_panel.select('a[href^="/star/"]'):
        name = a.get_text(strip=True)
        if name and name not in actresses:
            actresses.append(name)
    if actresses:
        info['actresses'] = actresses

    return info


def _extract_title(heading) -> str:
    small = heading.find('small')
    if small:
        small.extract()
    return heading.get_text(strip=True)


def _extract_cover(soup) -> str:
    poster = soup.select_one('div.col-md-3 div.col-md-12 img')
    if poster and poster.get('src'):
        src = poster['src'].strip()
        if src:
            return src if src.startswith('http') else f'https:{src}'

    thumb = soup.select_one('.panel-body .col-md-3 img')
    if thumb and thumb.get('src'):
        src = thumb['src'].strip()
        if src:
            return src if src.startswith('http') else f'https:{src}'

    return ''
