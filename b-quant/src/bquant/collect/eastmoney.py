"""Eastmoney public-endpoint collectors (bond board snapshot with ratings).

Endpoint: datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_BOND_CB_LIST
No key required; politely rate-limited. Requests only.
"""
import time
import requests

BASE = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
           'Referer': 'https://data.eastmoney.com/'}

def cb_board_snapshot(page_size: int = 500, max_pages: int = 10, sleep: float = 1.0) -> list[dict]:
    """Fetch the convertible-bond board snapshot (code, name, rating, premium, scale, ...)."""
    rows: list[dict] = []
    for page in range(1, max_pages + 1):
        params = {'reportName': 'RPT_BOND_CB_LIST', 'columns': 'ALL', 'pageSize': page_size,
                  'pageNumber': page, 'sortColumns': 'SECURITY_CODE', 'sortTypes': '1',
                  'source': 'WEB', 'client': 'WEB'}
        resp = requests.get(BASE, params=params, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        data = (payload.get('result') or {})
        batch = data.get('data') or []
        rows.extend(batch)
        total = data.get('count', len(rows))
        if not batch or len(rows) >= total:
            break
        time.sleep(sleep)
    return rows

def ratings_from_snapshot(rows: list[dict]) -> dict[str, str]:
    """Extract bond_code -> credit rating from a board snapshot."""
    out = {}
    for r in rows:
        code = str(r.get('SECURITY_CODE') or r.get('BOND_CODE') or '').split('.')[0]
        rating = str(r.get('RATING') or r.get('CREDIT_RATING') or '').strip()
        if code and rating:
            out[code] = rating
    return out
