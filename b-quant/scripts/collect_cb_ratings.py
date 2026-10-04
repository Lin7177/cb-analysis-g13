"""Collect the market-wide CB credit-rating snapshot from Eastmoney's public endpoint.

Usage:
    python scripts/collect_cb_ratings.py [--out data/curated/market/cb_ratings.csv]

Writes bond_code, bond_name, rating, collect_date + SHA-256 manifest entry appended to
market/manifest.json. This is a real collector: run it to refresh the snapshot.
"""
import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
import sys

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'src'))

from bquant.collect.eastmoney import cb_board_snapshot, ratings_from_snapshot  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=str(HERE.parent / 'data' / 'curated' / 'market' / 'cb_ratings.csv'))
    args = parser.parse_args()
    out = Path(args.out)
    rows = cb_board_snapshot()
    rating_map = ratings_from_snapshot(rows)
    frame = pd.DataFrame([{'bond_code': c, 'rating': rt} for c, rt in sorted(rating_map.items())])
    names = {str(r.get('SECURITY_CODE') or '').split('.')[0]: r.get('SECURITY_NAME_ABBR') or r.get('SECURITY_SHORT_NAME') or '' for r in rows}
    frame.insert(1, 'bond_name', frame.bond_code.map(names))
    frame['collect_date'] = date.today().isoformat()
    frame.to_csv(out, index=False, encoding='utf-8-sig')
    manifest_path = out.parent / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {'sha256': {}}
    manifest.setdefault('collectors', {})
    manifest['collectors']['cb_ratings'] = {
        'file': out.name, 'rows': int(len(frame)),
        'rated': int((frame.rating != '').sum()),
        'source': 'Eastmoney datacenter RPT_BOND_CB_LIST (public endpoint)',
        'sha256': hashlib.sha256(out.read_bytes()).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'rows={len(frame)} rated={int((frame.rating != "").sum())} -> {out}')


if __name__ == '__main__':
    main()
