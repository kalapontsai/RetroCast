"""
repro: 驗證 _build_analyze_meta 與 monthly_returns 內的 daily_returns_by_ticker
不再 leak inf (某天 close=0 → pct_change 出 ±inf)。

執行: python3 scripts/repro_meta_inf_leak.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, '/mnt/d/stock/retrocast')

from app import _build_analyze_meta


def find_nan_paths(obj, path='', found=None):
    if found is None:
        found = []
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        found.append((path, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            find_nan_paths(v, f'{path}.{k}', found)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            find_nan_paths(v, f'{path}[{i}]', found)
    return found


def main() -> int:
    # 構造 mock rows,模擬某天 close=0
    rows = [
        {'date': '2024-01-01', 'close': 100.0},
        {'date': '2024-01-02', 'close': 105.0},
        {'date': '2024-01-03', 'close': 0.0},     # 這天 pct_change 算 (0-105)/105 = -1, OK
        {'date': '2024-01-04', 'close': 50.0},
        {'date': '2024-01-05', 'close': 0.0},     # 這天 pct_change 算 (0-50)/50 = -1, OK
        {'date': '2024-01-06', 'close': 0.0},     # 連 0 → (0-0)/0 = nan
        {'date': '2024-01-07', 'close': 0.0},     # (0-0)/0 = nan
        {'date': '2024-01-08', 'close': 200.0},   # (200-0)/0 = +inf ← leak!
    ]

    client = MagicMock()
    client.get_stock_price = MagicMock(return_value=rows)

    result = _build_analyze_meta(client, ['6208'], '2024-01-01', '2024-01-31')

    daily = result['daily_returns_by_ticker'].get('6208', [])
    print(f'daily_returns_by_ticker.6208 數: {len(daily)}')
    inf_count = sum(1 for r in daily if math.isinf(r['ret']))
    nan_count = sum(1 for r in daily if math.isnan(r['ret']))
    print(f'其中 inf: {inf_count}, nan: {nan_count}')

    # json.dumps(allow_nan=False) 必須成功 (= 沒 NaN/Inf)
    try:
        json.dumps(result, allow_nan=False)
        can_serialize = True
    except ValueError:
        can_serialize = False
    print(f'json.dumps(allow_nan=False) 成功: {can_serialize}')

    if inf_count == 0 and nan_count == 0 and can_serialize:
        print()
        print('✅ PASS: 沒有 inf/nan leak 到 result')
        return 0
    else:
        print()
        print('❌ FAIL: 仍有 NaN/Inf leak')
        nans = find_nan_paths(result)
        for p, v in nans[:10]:
            print(f'  {p} = {v}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
