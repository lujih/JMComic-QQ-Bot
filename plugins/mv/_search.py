import re
from urllib.parse import quote

import cloudscraper
from bs4 import BeautifulSoup

MISSAV_SEARCH = "https://missav.ai/search/{query}"

_scraper = None


def _get_scraper():
    global _scraper
    if _scraper is None:
        _scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
            delay=5,
        )
    return _scraper


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
        resp = _get_scraper().get(url, timeout=20)
    except Exception:
        return "", "", ""

    if resp.status_code != 200:
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
    except Exception:
        pass

    return "", "", ""


def _fetch_av_detail(detail_url: str) -> dict:
    if not detail_url:
        return {}

    try:
        resp = _get_scraper().get(detail_url, timeout=20)
    except Exception:
        return {}

    if resp.status_code != 200:
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
    except Exception:
        return {}
