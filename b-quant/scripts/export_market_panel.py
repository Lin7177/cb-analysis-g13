"""Export the market-wide CB factor panels into data/curated/market/ (CSV.GZ + SHA-256).

Usage:
    python scripts/export_market_panel.py [--catalog-dir D:/path/to/catalog]

Reads the offline market-data store via bquant.market.catalog and writes one wide panel
per factor plus manifest.json (row/bond counts, date coverage, SHA-256 of every output).
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'src'))

from bquant.market.catalog import FACTOR_FILES, export_factors  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--catalog-dir', default=None)
    parser.add_argument('--out', default=str(HERE.parent / 'data' / 'curated' / 'market'))
    args = parser.parse_args()
    out = Path(args.out)
    meta = export_factors(sorted(FACTOR_FILES), out, args.catalog_dir)
    files = sorted(out.glob('*.csv.gz'))
    manifest = {
        'purpose': 'Market-wide CB factor panels for weight estimation (see docs/methods/weight-estimation.md)',
        'factors': meta,
        'sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        'note': 'Panels are daily 14:45 snapshots keyed by CB code (e.g. 113659.SH); Qty_* carry underlying-stock fundamentals mapped to the bond code.',
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
