import os
import re
from urllib.parse import quote

from bs4 import BeautifulSoup
from curl_cffi import requests
from jmcomic import jm_log

MISSAV_BASE = os.getenv("MISSAV_BASE_URL", "https://missav.ai")
MISSAV_SEARCH = f"{MISSAV_BASE}/search/{{query}}"
JAVDB_SEARCH = "https://javdb.com/search?q={query}&f=all"
_IMPERSONATE = "chrome124"


def _request(url, timeout=20, headers=None):
    with requests.Session() as session:
        return session.get(url, impersonate=_IMPERSONATE, timeout=timeout, headers=headers)


def _extract_card_link(card, img):
    link = card.select_one('a') or img.find_parent('a')
    if link and link.get('href'):
        href = link['href']
        if href.startswith('http') or href.startswith('//'):
            return href
        return f'https://missav.ai{href}'
    return ''


def _search_missav(query: str):
    url = MISSAV_SEARCH.format(query=quote(query, safe=''))

    try:
        resp = _request(url)
    except Exception as e:
        jm_log('mv.search', f'MissAV search request failed: {e}')
        return "", "", ""

    if resp.status_code != 200:
        jm_log('mv.search', f'MissAV search returned {resp.status_code}')
        return "", "", ""

    try:
        soup = BeautifulSoup(resp.content, 'html.parser')
        cards = soup.select('div.thumbnail')
        if not cards:
            return "", "", ""

        query_upper = query.upper()
        for card in cards[:10]:
            img = card.select_one('img')
            if img and img.get('alt', ''):
                alt = img['alt'].strip()
                if alt and query_upper in alt.upper():
                    thumbnail = (img.get('data-src', '') or img.get('src', '') or '')
                    detail_url = _extract_card_link(card, img)
                    return alt, thumbnail, detail_url

        first = cards[0]
        img = first.select_one('img')
        if img and img.get('alt', ''):
            thumbnail = (img.get('data-src', '') or img.get('src', '') or '')
            detail_url = _extract_card_link(first, img)
            return img['alt'].strip(), thumbnail, detail_url
    except Exception as e:
        jm_log('mv.search', f'MissAV search parse failed: {e}')

    return "", "", ""


def _fetch_av_detail(detail_url: str) -> dict:
    if not detail_url:
        return {}

    try:
        resp = _request(detail_url)
    except Exception as e:
        jm_log('mv.detail', f'MissAV detail request failed: {e}')
        return {}

    if resp.status_code != 200:
        jm_log('mv.detail', f'MissAV detail returned {resp.status_code}')
        return {}

    try:
        soup = BeautifulSoup(resp.content, 'html.parser')
        info = {}
        page_text = soup.get_text()

        h1 = soup.select_one('h1')
        if h1:
            info['title'] = h1.get_text(strip=True)

        meta_img = soup.select_one('meta[property="og:image"]')
        if meta_img and meta_img.get('content'):
            info['cover'] = meta_img['content']

        date_patterns = [
            r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})',
            r'發售日[：:]\s*(\S+)',
            r'發行日期[：:]\s*(\S+)',
            r'Release Date[：:]\s*(\S+)',
        ]
        for p in date_patterns:
            m = re.search(p, page_text)
            if m:
                info['date'] = m.group(1)
                break

        dur_patterns = [
            r'(\d+)\s*分鐘',
            r'時長[：:]\s*(\S+)',
            r'Duration[：:]\s*(\S+)',
        ]
        for p in dur_patterns:
            m = re.search(p, page_text)
            if m:
                info['duration'] = m.group(1)
                break

        m = re.search(r'(\d+)\s*min', page_text, re.I)
        if 'duration' not in info and m:
            info['duration'] = m.group(1) + ' min'

        studio_patterns = [
            r'製作商[：:]\s*(.+?)(?:\n|$)',
            r'Studio[：:]\s*(.+?)(?:\n|$)',
        ]
        for p in studio_patterns:
            m = re.search(p, page_text)
            if m:
                info['studio'] = m.group(1).strip()
                break

        actresses = []
        for a in soup.find_all('a'):
            href = a.get('href', '')
            if '/actress/' in href or '/actor/' in href:
                name = a.get_text(strip=True)
                if name and name not in actresses:
                    actresses.append(name)

        if not actresses:
            pats = [
                r'女优[：:]\s*(.+)',
                r'出演[：:]\s*(.+)',
                r'Actress[：:]\s*(.+)',
            ]
            for p in pats:
                m = re.search(p, page_text)
                if m:
                    names = re.split(r'[,，、/\s]+', m.group(1).strip())
                    names = [n.strip() for n in names if n.strip()]
                    if names:
                        actresses = names
                        break

        if actresses:
            info['actresses'] = actresses

        return info
    except Exception as e:
        jm_log('mv.detail', f'MissAV detail parse failed: {e}')
        return {}


def _search_javdb(query: str) -> dict:
    url = JAVDB_SEARCH.format(query=quote(query))

    _headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/125.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    }

    try:
        resp = _request(url, headers=_headers)
    except Exception as e:
        jm_log('mv.javdb', f'JavDB search request failed: {e}')
        return {}

    if resp.status_code != 200:
        jm_log('mv.javdb', f'JavDB search returned {resp.status_code}')
        return {}

    try:
        soup = BeautifulSoup(resp.content, 'html.parser')
        info = {}

        cards = soup.select('.movie-list .item, .grid .item, .card')
        if not cards:
            jm_log('mv.javdb', f'JavDB search found no cards for {query}')
            return {}

        first = cards[0]
        link = first.select_one('a[href*="/v/"]')
        if link and link.get('href'):
            href = link['href']
            detail_path = href if href.startswith('http') else f'https://javdb.com{href}'

            img = first.select_one('img')
            if img:
                info['cover'] = img.get('src') or img.get('data-src') or ''

            title_el = first.select_one('.title, .video-title, a[href*="/v/"]')
            if title_el:
                info['title'] = title_el.get_text(strip=True)

            meta_text = first.get_text()
            m = re.search(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})', meta_text)
            if m:
                info['date'] = m.group(1)
            m = re.search(r'(\d+)\s*min', meta_text, re.I)
            if m:
                info['duration'] = m.group(1) + ' min'

            try:
                det_resp = _request(detail_path, headers=_headers)
                if det_resp.status_code == 200:
                    det = BeautifulSoup(det_resp.content, 'html.parser')
                    det_text = det.get_text()

                    actresses = []
                    for a in det.select('.cast a, .actors a, a[href*="/actors/"]'):
                        name = a.get_text(strip=True)
                        if name and name not in actresses:
                            actresses.append(name)
                    if actresses:
                        info['actresses'] = actresses

                    og_img = det.select_one('meta[property="og:image"]')
                    if og_img and og_img.get('content'):
                        info['cover'] = og_img['content']

                    og_title = det.select_one('meta[property="og:title"]')
                    if og_title and og_title.get('content'):
                        info['title'] = og_title['content'].strip()

                    if 'date' not in info or not info['date']:
                        m = re.search(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})', det_text)
                        if m:
                            info['date'] = m.group(1)
                    if 'duration' not in info or not info['duration']:
                        m = re.search(r'(\d+)\s*minutes?', det_text, re.I)
                        if m:
                            info['duration'] = m.group(1) + ' min'
                    m = re.search(r'Studio[：:]\s*(.+?)(?:\n|$)', det_text)
                    if m:
                        info['studio'] = m.group(1).strip()
            except Exception as e:
                jm_log('mv.javdb', f'JavDB detail page request failed: {e}')

        if 'actresses' not in info or not info.get('actresses'):
            card_text = first.get_text()
            m = re.search(r'(?:演員|女优|Actress)[：:]\s*(.+?)(?:\n|$)', card_text)
            if m:
                names = re.split(r'[,，、/\s]+', m.group(1).strip())
                names = [n.strip() for n in names if n.strip()]
                if names:
                    info['actresses'] = names

        if info:
            jm_log('mv.javdb', f'JavDB found data for {query}')
        return info
    except Exception as e:
        jm_log('mv.javdb', f'JavDB search parse failed: {e}')
        return {}
