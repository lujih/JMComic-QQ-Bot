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
            delay=10,
        )
    return _scraper


def _search_missav(query: str):
    url = MISSAV_SEARCH.format(query=quote(query, safe=''))

    try:
        resp = _get_scraper().get(url, timeout=20)
    except Exception:
        return "", ""

    if resp.status_code != 200:
        return "", ""

    try:
        soup = BeautifulSoup(resp.content, 'html.parser')
        cards = soup.select('div.thumbnail')
        if not cards:
            return "", ""

        query_upper = query.upper()
        for card in cards[:10]:
            img = card.select_one('img')
            if img and img.get('alt', ''):
                alt = img['alt'].strip()
                if alt and query_upper in alt.upper():
                    thumbnail = (img.get('data-src', '') or img.get('src', '') or '')
                    return alt, thumbnail

        first = cards[0]
        img = first.select_one('img')
        if img and img.get('alt', ''):
            thumbnail = (img.get('data-src', '') or img.get('src', '') or '')
            return img['alt'].strip(), thumbnail
    except Exception:
        pass

    return "", ""
