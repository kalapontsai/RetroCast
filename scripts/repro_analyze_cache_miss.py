"""
repro: 驗證 /api/analyze 在 cache 已有資料時,連跑兩次仍會重抓 FinMind 的根因

預期: 第二次完全 0 次 FinMind call
實際: 看會打幾次 + 看哪些資料集

執行: python3 scripts/repro_analyze_cache_miss.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

REPO = Path('/mnt/d/stock/retrocast')
sys.path.insert(0, str(REPO))

from app import create_app
from lib.finmind import FinMindClient


def main() -> int:
    print(f'=== Cache 既有狀態 ===')
    cache_dir = REPO / 'data' / 'price_cache'
    json_files = sorted(cache_dir.glob('*.json'))
    print(f'  {len(json_files)} 個 cache 檔案')

    # 找出 kadela_stock 涵蓋的 ticker
    profile = REPO / 'user_profile' / 'kadela_stock.csv'
    tickers = []
    if profile.exists():
        for line in profile.read_text(encoding='utf-8').splitlines()[1:]:
            t = line.split(',')[0].strip().strip('"')
            if t:
                tickers.append(t)
    print(f'  kadela_stock tickers: {tickers}')
    print(f'  其中已 cache: {[t for t in tickers if (cache_dir / f"{t}.json").exists()]}')
    print()

    app = create_app()
    client = app.test_client()

    call_log: list[tuple[int, str, dict | None]] = []
    call_id = {'i': 0}

    original_query = FinMindClient.query

    def counting_query(self, dataset, params=None):
        call_id['i'] += 1
        call_log.append((call_id['i'], dataset, params))
        return original_query(self, dataset, params)

    body = json.dumps({
        'profile': 'kadela_stock',
        'n': 10,
        'forecast_basis': 'common',
        'enable_v2': False,  # 關掉 v2 簡化路徑,只跑主分析
    })

    print('=== Test: 連跑兩次 /api/analyze,計 FinMind call ===')
    with patch.object(FinMindClient, 'query', counting_query):
        # === Round 1 ===
        n_before = call_id['i']
        t0 = time.time()
        r1 = client.post('/api/analyze', data=body, content_type='application/json')
        dt1 = time.time() - t0
        n_round1 = call_id['i'] - n_before
        print(f'  Round 1: status={r1.status_code} 耗時={dt1:.1f}s FinMind calls={n_round1}')

        # === Round 2 ===
        n_before = call_id['i']
        t0 = time.time()
        r2 = client.post('/api/analyze', data=body, content_type='application/json')
        dt2 = time.time() - t0
        n_round2 = call_id['i'] - n_before
        print(f'  Round 2: status={r2.status_code} 耗時={dt2:.1f}s FinMind calls={n_round2}')

    print()
    print('=== Round 2 的 FinMind call 細目 ===')
    for i, ds, p in call_log[-n_round2:]:
        params_str = ', '.join(f'{k}={v}' for k, v in (p or {}).items() if k != 'token')
        print(f'  #{i} {ds} ({params_str})')

    print()
    print('=== 結論 ===')
    if n_round2 == 0:
        print('  ✅ Round 2 完全用 cache,沒打 FinMind')
        return 0
    else:
        # 分類打點
        first_trading_calls = [c for c in call_log[-n_round2:] if c[1] == 'TaiwanStockPrice' and (c[2] or {}).get('start_date') == '1990-01-01']
        other = [c for c in call_log[-n_round2:] if c not in first_trading_calls]
        print(f'  ❌ Round 2 仍打 {n_round2} 次 FinMind')
        print(f'     其中 get_first_trading_day 觸發: {len(first_trading_calls)} 次')
        print(f'     其他: {len(other)} 次')
        return 1


if __name__ == '__main__':
    sys.exit(main())
