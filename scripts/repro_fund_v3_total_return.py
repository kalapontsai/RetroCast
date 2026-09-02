#!/usr/bin/env python3
"""Regression: fund profile N=3 必須用 v3 (股數追蹤 + 配息再投入) 算含息總報酬

歷史教訓：
- 2026-08-31 13:27 報告誤用 v2 公式 (cum_addend 純加法)，00881 N=3 顯示 180.26%
- 主人指出這跟 raw 價格報酬 182.37% 幾乎一致 → 明顯是「價格報酬」不是 Total Return
- v3 (股數追蹤) 重跑 → 00881 應該 ≥ 215% (含 4 筆有效配息累積 +37.9pp)
- 此 repro 鎖住「含息效果必須 ≥ raw 報酬 + 10pp」，避免 v2 cache 殘留

用法：
  python3 scripts/repro_fund_v3_total_return.py

預期：5 個 OK 行
"""
from __future__ import annotations

import sys
from pathlib import Path

# 確保從 repo root 跑
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.finmind import FinMindClient  # noqa: E402
from lib.portfolio import build_adjusted_close, prices_to_pivot  # noqa: E402


def main() -> int:
    client = FinMindClient()
    tickers = ['00690', '00878', '00881', '00918', '00935']
    start = '2023-08-01'
    end = '2026-07-31'

    print(f'=== fund profile N=3 v3 還原除權息 regression ===')
    print(f'期間: {start} ~ {end}')
    print(f'tickers: {tickers}')
    print()
    ok_count = 0
    for t in tickers:
        rows = client.get_stock_price(t, start, end)
        prices = prices_to_pivot({t: rows}, 'close')
        divs = client.get_dividends(t, start, end)
        splits = client.get_splits(t, start, end)
        adj = build_adjusted_close(prices, {t: divs}, {t: splits})
        first = adj[t].dropna().iloc[0]
        last = adj[t].dropna().iloc[-1]
        v3_total = last / first - 1
        raw_total = prices[t].dropna().iloc[-1] / prices[t].dropna().iloc[0] - 1
        div_sum = sum(d['cash_div'] for d in divs)
        diff_pp = (v3_total - raw_total) * 100
        # 鎖住 v3 必須明顯高於 raw（至少有配息再投入效果）
        ok = v3_total > raw_total + 0.05  # 至少 +5pp
        # 配息多的 ETF (div_sum > 2) 應該有 ≥10pp 含息效果
        if div_sum > 2:
            ok = ok and diff_pp >= 10
        status = 'OK' if ok else 'FAIL'
        if ok:
            ok_count += 1
        print(f'  [{status}] {t}: v3={v3_total*100:.2f}% vs raw={raw_total*100:.2f}% '
              f'(含息效果 +{diff_pp:.2f}pp, div_sum={div_sum:.2f})')
        if not ok:
            print(f'    EXPECTED: v3 必須 ≥ raw + 10pp for div_sum>2 ETF')
            return 1
    print()
    print(f'通過 {ok_count}/{len(tickers)}')
    return 0 if ok_count == len(tickers) else 1


if __name__ == '__main__':
    sys.exit(main())
