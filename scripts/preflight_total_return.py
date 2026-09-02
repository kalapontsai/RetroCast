#!/usr/bin/env python3
"""
Pre-flight Check: Total Return 算法驗證（黃金逐檔法）

對齊主人的 2026-08-31 13:47 黃金驗證方法：
  「直接把每檔的 [2023-08-01 收盤價、2026-07-31 收盤價、期間所有現金股利、
    股數再投入後終值] 逐檔列出來，這樣可以直接抓出到底是哪一檔的
    Total Return 演算法有問題，而不需要只看最終百分比」

這個工具會對 profile 內每檔股票，逐檔列出：
  - first_raw / last_raw（window 區間內的 raw close）
  - 期間所有配息事件（date, cash_div, stock_div_ratio）
  - 期間 split 事件（如果有）
  - 股數追蹤後的最終 shares
  - 預期 NAV 終值（final_shares × last_raw）
  - 預期 Total Return（last_nav / first_raw - 1）

比對 `_run_analyze` 算出來的 per_stock_n_year.total_return 是否等於
黃金法算出的 expected_total_return，**任何一檔超過 0.5% 差距就 FAIL**。

教訓脈絡：
  - 2026-08-31 主人給 havocfuture.tw 對照組 → 抓出 v2 演算法不夠
  - 主人給 fund profile 4 檔 → 抓出 v2 cache 殘留 (00881=180% vs raw 182%)
  - **主人給 kadela profile 9 檔 → 抓出 v4 double-count bug**
    （per_stock_n_year_window 拿累積 adj 直接切 window 造成重複計算）

這個 pre-flight 是對主人方法論的程式化致敬。

用法：
  python3 scripts/preflight_total_return.py [profile_name]

預設 profile = fund（4 檔 00881/00878/00690/00918，主人 13:31 那組）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.finmind import FinMindClient  # noqa: E402
from lib.portfolio import prices_to_pivot  # noqa: E402


def golden_method_for_ticker(
    ticker: str,
    start_date: str,
    end_date: str,
    client: FinMindClient,
) -> dict:
    """
    主人黃金驗證法：對單一 ticker 算出所有透明中間數值。

    Returns:
        dict with keys: first_raw, last_raw, events, final_shares,
                        expected_nav_final, expected_total_return,
                        raw_total_return, div_count, div_sum
    """
    rows = client.get_stock_price(ticker, start_date, end_date)
    prices = prices_to_pivot({ticker: rows}, 'close')
    raw = prices[ticker].dropna()
    raw = raw[raw > 0]
    if raw.empty:
        return None

    first_raw = float(raw.iloc[0])
    last_raw = float(raw.iloc[-1])
    raw_total = last_raw / first_raw - 1

    divs = client.get_dividends(ticker, start_date, end_date)
    splits = client.get_splits(ticker, start_date, end_date)

    index_dates_str = set(raw.index.strftime('%Y-%m-%d').tolist())

    events = []
    for d in divs:
        if d['date'] and d['date'] in index_dates_str:
            events.append({
                'date': d['date'],
                'kind': 'div',
                'cash': float(d.get('cash_div', 0) or 0),
                'stock_ratio': float(d.get('stock_div_ratio', 0) or 0),
            })
    for sp in splits:
        if sp['date'] and sp['date'] in index_dates_str:
            events.append({
                'date': sp['date'],
                'kind': 'split',
                'ratio': float(sp.get('split_ratio', 1.0) or 1.0),
            })
    events.sort(key=lambda e: e['date'])

    # 股數追蹤（從 1 股起算）
    shares = 1.0
    for t_date, p in raw.items():
        date_str = t_date.strftime('%Y-%m-%d')
        for ev in events:
            if ev['date'] == date_str:
                if ev['kind'] == 'div':
                    shares *= (1 + ev['stock_ratio'])
                    if p > 0 and ev['cash'] > 0:
                        shares += ev['cash'] / p
                elif ev['kind'] == 'split':
                    shares *= ev['ratio']

    expected_nav_final = shares * last_raw
    expected_total = expected_nav_final / first_raw - 1
    div_count = sum(1 for e in events if e['kind'] == 'div')
    div_sum = sum(e['cash'] for e in events if e['kind'] == 'div')
    split_count = sum(1 for e in events if e['kind'] == 'split')

    return {
        'ticker': ticker,
        'start': str(raw.index[0].date()),
        'end': str(raw.index[-1].date()),
        'first_raw': first_raw,
        'last_raw': last_raw,
        'raw_total_return': raw_total,
        'div_count': div_count,
        'div_sum': div_sum,
        'split_count': split_count,
        'final_shares': shares,
        'expected_nav_final': expected_nav_final,
        'expected_total_return': expected_total,
        'events': events,
    }


def main() -> int:
    profile = sys.argv[1] if len(sys.argv) > 1 else 'fund'

    # fund profile 是 13:31 主人驗證組（4 檔）
    # kadela_stock 是 13:47 主人驗證組（9 檔）
    user_profile_dir = Path('/mnt/d/stock/retrocast/user_profile')
    profile_file = user_profile_dir / f'{profile}.csv'

    if not profile_file.is_file():
        print(f'❌ profile 不存在: {profile_file}')
        print(f'   用法: python3 scripts/preflight_total_return.py [profile]')
        return 1

    # 解析 CSV (格式: ticker,shares)
    tickers = []
    for line in profile_file.read_text(encoding='utf-8').splitlines():
        line = line.strip().replace(',', ' ').split()
        if not line or line[0].startswith('#'):
            continue
        ticker = line[0].strip().strip('"').upper()
        if not ticker or not ticker[0].isdigit():
            continue
        tickers.append(ticker)

    if not tickers:
        print(f'❌ profile {profile} 沒有有效 ticker')
        return 1

    # 預設 window：N=3 (跟 13:31/13:47 主人驗證組一致)
    start_date = '2023-08-01'
    end_date = '2026-07-31'

    print('=' * 90)
    print(f'🛫 Pre-flight Check: Total Return 黃金逐檔驗證 (主人 2026-08-31 13:47 法)')
    print(f'   profile: {profile}')
    print(f'   window:  {start_date} ~ {end_date}')
    print(f'   tickers: {tickers}')
    print('=' * 90)
    print()

    client = FinMindClient()
    golden_results = {}
    failures = []

    for t in tickers:
        golden = golden_method_for_ticker(t, start_date, end_date, client)
        if golden is None:
            print(f'⚠ {t}: 無 raw price data')
            continue

        golden_results[t] = golden

        print(f'━━━ {t} ━━━')
        print(f'  期間: {golden["start"]} ~ {golden["end"]}')
        print(f'  raw: first={golden["first_raw"]:.2f} → last={golden["last_raw"]:.2f}')
        print(f'  raw 價格報酬: {golden["raw_total_return"]*100:+.2f}%')
        print(f'  期間事件: {golden["div_count"]} 筆配息 '
              f'(cash 總和 = {golden["div_sum"]:.2f} 元/股), '
              f'{golden["split_count"]} 筆 split')
        if golden['events']:
            print(f'  事件清單:')
            for ev in golden['events']:
                if ev['kind'] == 'div':
                    print(f'    {ev["date"]} DIV cash={ev["cash"]:.4f} stock_ratio={ev["stock_ratio"]:.4f}')
                elif ev['kind'] == 'split':
                    print(f'    {ev["date"]} SPLIT ratio={ev["ratio"]:.6f}')
        print(f'  股數追蹤: 1 → {golden["final_shares"]:.6f}')
        print(f'  預期 NAV 終值: {golden["expected_nav_final"]:.4f}')
        print(f'  預期 Total Return: {golden["expected_total_return"]*100:+.2f}%')
        print()

    # 跟實際 _run_analyze 算出的結果比對
    print('=' * 90)
    print('🔍 比對 _run_analyze 實際結果 vs 黃金法期望值')
    print('=' * 90)

    import app  # noqa: PLC0415
    app.USER_PROFILE_DIR = user_profile_dir

    body = {'profile': profile, 'n': 3}
    result = app._run_analyze(body)
    actual = result.get('history', {}).get('per_stock_n_year', {})

    print()
    print(f'{"ticker":<8} {"golden預期":>12} {"_run_analyze":>14} {"差距":>10} {"狀態":>8}')
    print('-' * 60)
    for t in tickers:
        if t not in golden_results or t not in actual:
            print(f'{t:<8} {"?":>12} {"?":>14} {"?":>10}')
            continue
        expected = golden_results[t]['expected_total_return']
        actual_val = actual[t].get('total_return')
        if actual_val is None:
            print(f'{t:<8} {expected*100:>11.2f}% {"None":>14} {"?":>10} {"FAIL":>8}')
            failures.append(f'{t}: actual is None')
            continue
        diff = actual_val - expected
        status = '✅ OK' if abs(diff) < 0.005 else '❌ FAIL'
        if abs(diff) >= 0.005:
            failures.append(f'{t}: diff={diff*100:+.2f}pp')
        print(f'{t:<8} {expected*100:>11.2f}% {actual_val*100:>13.2f}% {diff*100:>+9.2f}pp {status:>8}')

    print()
    if failures:
        print('=' * 90)
        print(f'❌ Pre-flight FAIL ({len(failures)} 個 ticker 差距 >= 0.5%)')
        print('=' * 90)
        for f in failures:
            print(f'  - {f}')
        print()
        print('這代表 _run_analyze 的 per_stock_n_year.total_return 算法跟黃金逐檔法不一致。')
        print('常見原因：')
        print('  1) build_adjusted_close 算法版本不是 v3 (股數追蹤)')
        print('  2) per_stock_n_year_window 沒有從 raw 重跑 v3 (v4 double-count bug)')
        print('  3) Flask/WSL 端 module cache 還沒清乾淨')
        print('解法：')
        print('  - 改 lib/portfolio.py 後 cp 到 /mnt/d/stock/retrocast/')
        print('  - 清 pycache (find ... -name "*.pyc" -delete)')
        print('  - 重啟 Flask')
        return 1
    else:
        print('=' * 90)
        print(f'✅ Pre-flight PASS (所有 {len(golden_results)} 檔差距 < 0.5%)')
        print('=' * 90)
        return 0


if __name__ == '__main__':
    sys.exit(main())
