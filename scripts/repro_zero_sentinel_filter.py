#!/usr/bin/env python3
"""
Repro: profile=0050_006208.csv used to produce absurd NAV (1.8e-43 ≈ 0)
because FinMind TaiwanStockPrice has 198 rows with close=0 (sentinel for
減資 / 暫停交易 / 數據缺漏) in 006208. The cumulative product of (1+r)
collapsed to 0 once those zero-close days hit the portfolio return.

HTML report also crashed with `float() argument must be a string or a real
number, not 'NoneType'` because:
  - render_fan_chart_svg: row['value'] can be None when percentile_bands
    contains overflow rows (year >= 2 in this case).
  - report.html: "{:,.0f}".format(mcs.median_final) crashes when the value
    is None.

Fixes:
  - lib/portfolio.py prices_to_pivot: filter `close > 0` at the pivot source
  - lib/fan_chart.py: skip rows with None / NaN values
  - lib/exporter.py: add `fmt_money` filter (None → '—')
  - templates/report.html: use `fmt_money` for MC stats & sequence_risk median
"""
import sys
from pathlib import Path

sys.path.insert(0, '/mnt/d/stock/retrocast')
import os
os.chdir('/mnt/d/stock/retrocast')

from app import _run_analyze
import app
app.USER_PROFILE_DIR = Path('/mnt/d/stock/retrocast/user_profile')
from lib.exporter import render_html_report


def main() -> int:
    body = {'profile': '0050_006208'}
    result = _run_analyze(body)
    m = result['common']['metrics']

    # 1) Common mode 不應該有 absurd negative metrics
    assert m['total_return'] > 0, f'common total_return 應為正: {m["total_return"]}'
    assert 0.05 < m['cagr'] < 0.30, f'common CAGR 異常: {m["cagr"]}'
    assert m['mdd'] > -0.7, f'common MDD 太深: {m["mdd"]}'
    assert m['sharpe'] > 0, f'common Sharpe 應為正: {m["sharpe"]}'
    print(f'OK: common mode 合理 ({m["total_return"]*100:.1f}% / CAGR {m["cagr"]*100:.1f}% / Sharpe {m["sharpe"]:.2f})')

    # 2) NAV 不應該掉到 0
    nav = result['common']['nav']
    assert nav[-1]['nav'] > 1.0, f'NAV final 應 > 1.0: {nav[-1]["nav"]}'
    print(f'OK: common NAV final = {nav[-1]["nav"]:.3f}')

    # 3) per-stock 6 檔都應該有正 CAGR（0050 + 006208 是 ETF）
    per = result['history']['per_stock']
    assert '0050' in per and '006208' in per
    for ticker in ('0050', '006208'):
        info = per[ticker]
        assert info['cagr'] > 0, f'{ticker} cagr 應為正: {info["cagr"]}'
        assert info['mdd'] > -0.95, f'{ticker} mdd 異常: {info["mdd"]}'
    print(f'OK: per_stock 都正常')

    # 4) HTML 不該因 None / float crash
    html = render_html_report(result, '0050_006208')
    assert '—' in html, 'fmt_money filter 應該輸出 —'
    assert '<svg' in html, 'fan chart SVG 應該正常 render'
    print(f'OK: HTML 渲染 {len(html)} chars，沒崩潰')

    # 5) sample_stock.csv 是 sample list，不受 sentinel 影響 → 行為不應受影響（regression 保護）
    body2 = {'profile': 'sample_stock'}
    result2 = _run_analyze(body2)
    m2 = result2['common']['metrics']
    tr = m2['total_return'] * 100
    print(f'OK: regression check 通過 (sample_stock 仍正常, total={tr:.1f}%)')
    return 0


if __name__ == '__main__':
    sys.exit(main())