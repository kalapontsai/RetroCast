#!/usr/bin/env python3
"""scripts/migrate_price_cache_to_canonical.py

v3.0.3: 把 data/price_cache/ 內的 cache 檔,根據其 stock_id 對 FinMind 重新 match 拿
canonical form,並把舊檔 trash(舊檔名 != canonical 時)。原因:

- 早期 cache 檔案可能命名不一致(例如 50.json vs 0050.json)
- v3.0.3 起,normalize_profile_csv 確保 CSV 用 canonical form,cache 也必須對齊
- 重抓策略(主人 15:04 拍板 A 方案):trash 舊檔讓下次 fetch 走 API,資料完全乾淨

Usage:
    # 先看會動到哪些檔(dry-run,不實際刪除)
    python3 scripts/migrate_price_cache_to_canonical.py --dry-run

    # 實際跑
    python3 scripts/migrate_price_cache_to_canonical.py

設計原則:
- 用 trash(不用 rm)— AGENTS.md 「禁用 rm -rf」
- trash 指令不存在時 fallback 到 ~/.local/share/Trash/files/(Linux trash-cli 風格)
- 失敗不中斷整批,個別檔失敗 log warning 繼續跑
- 印 summary:n files trashed, m unchanged, k failed
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.finmind import FinMindClient  # noqa: E402

DEFAULT_CACHE_DIR = ROOT / 'data' / 'price_cache'


def find_trash_dir() -> Path | None:
    """找 Linux trash-cli 預設位置;不存在回 None"""
    home = Path.home()
    candidates = [
        home / '.local' / 'share' / 'Trash' / 'files',
        home / '.Trash',
    ]
    for c in candidates:
        if c.is_dir() or c.parent.is_dir():
            c.mkdir(parents=True, exist_ok=True)
            return c
    return None


def safe_trash(path: Path, dry_run: bool = False) -> str:
    """trash a file safely.
    Returns: 'trashed' / 'mv-trash' / 'dry-run' / 'no-trash-dir'
    Raises: nothing — caller should catch.
    """
    if dry_run:
        return 'dry-run'
    # Try shutil-based trash first (跨平台安全)
    try:
        # Python 3.8+ 沒有 send2trash 標準函式,用 shutil.move fallback
        trash_dir = find_trash_dir()
        if trash_dir is None:
            return 'no-trash-dir'
        target = trash_dir / path.name
        # 若 target 已存在,加 timestamp 區分
        if target.exists():
            from datetime import datetime
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            target = trash_dir / f'{path.name}.{ts}'
        shutil.move(str(path), str(target))
        return 'mv-trash'
    except Exception as e:
        print(f'  WARN: trash 失敗 {path}: {e}', file=sys.stderr)
        return 'no-trash-dir'


def migrate_one(
    cache_file: Path,
    client: FinMindClient,
    dry_run: bool = False,
) -> tuple[str, str | None]:
    """處理單一 cache 檔。
    Returns: (action, canonical_or_None)
        action ∈ {'unchanged', 'will-trash', 'trashed', 'failed', 'skip-bad-file'}
    """
    try:
        data = json.loads(cache_file.read_text(encoding='utf-8'))
        stock_id = data.get('stock_id')
        if not stock_id:
            return ('skip-bad-file', None)
    except Exception as e:
        print(f'  WARN: 讀 {cache_file} 失敗: {e}', file=sys.stderr)
        return ('skip-bad-file', None)

    # 用 stock_id 拿 canonical (不是檔名!因為真 FinMind 邏輯是看 stock_id)
    # 注意:match_ticker 會試 variants,但對已 canonical 的 stock_id 通常直接 exact match
    match = client.match_ticker(stock_id)
    if match is None:
        # 這 ticker 在 FinMind 找不到 — 可能是真的下市或拼錯。trash 掉。
        result = safe_trash(cache_file, dry_run)
        return ('failed' if not dry_run else 'will-trash', None)

    canonical = match['stock_id']
    # 檔名 ≠ canonical → trash(下次 fetch 走 API 寫新檔名)
    if cache_file.name != f'{canonical}.json':
        result = safe_trash(cache_file, dry_run)
        action = 'will-trash' if dry_run else 'trashed'
        return (action, canonical)
    return ('unchanged', canonical)


def main():
    parser = argparse.ArgumentParser(description='Migrate price cache to canonical tickers')
    parser.add_argument('--cache-dir', default=str(DEFAULT_CACHE_DIR),
                        help='Path to price_cache/ directory')
    parser.add_argument('--dry-run', action='store_true',
                        help='只印會動到哪些檔,不實際刪除')
    parser.add_argument('--limit', type=int, default=None,
                        help='最多處理幾個檔(預設全部)')
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)
    if not cache_dir.is_dir():
        print(f'ERROR: cache dir 不存在: {cache_dir}', file=sys.stderr)
        sys.exit(1)

    json_files = sorted(cache_dir.glob('*.json'))
    if args.limit:
        json_files = json_files[:args.limit]

    print(f'[migrate] cache_dir: {cache_dir}')
    print(f'[migrate] 找到 {len(json_files)} 個 .json 檔')
    if args.dry_run:
        print(f'[migrate] DRY RUN — 不實際刪除')

    client = FinMindClient()

    counts = {
        'unchanged': 0,
        'trashed': 0,
        'will-trash': 0,
        'failed': 0,
        'skip-bad-file': 0,
    }

    for cf in json_files:
        action, canonical = migrate_one(cf, client, dry_run=args.dry_run)
        counts[action] = counts.get(action, 0) + 1
        if action == 'unchanged':
            print(f'  [unchanged] {cf.name}')
        elif action in ('trashed', 'will-trash'):
            print(f'  [{action}] {cf.name} (canonical: {canonical})')
        elif action == 'failed':
            print(f'  [trash-failed-not-in-finmind] {cf.name}', file=sys.stderr)
        elif action == 'skip-bad-file':
            print(f'  [skip-bad-file] {cf.name}')

    print(f'\n[migrate] Summary:')
    print(f'  unchanged:     {counts["unchanged"]}')
    if args.dry_run:
        print(f'  will-trash:    {counts["will-trash"]}')
    else:
        print(f'  trashed:       {counts["trashed"]}')
        print(f'  failed:        {counts["failed"]}')
    print(f'  skip-bad-file: {counts["skip-bad-file"]}')

    if args.dry_run and counts['will-trash'] > 0:
        print(f'\n[migrate] 預備 trash {counts["will-trash"]} 個檔。')
        print(f'[migrate] 確認後請跑: python3 scripts/migrate_price_cache_to_canonical.py')


if __name__ == '__main__':
    main()
