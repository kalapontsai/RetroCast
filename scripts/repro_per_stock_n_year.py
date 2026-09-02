#!/usr/bin/env python3
"""
Repro: /api/analyze on 0050_006208 with n=10 should produce BOTH tables:
  - per_stock (各股完整歷史): 0050 報 23.09y、006208 報 14.04y
  - per_stock_n_year (N 年區間對齊): 兩支都用「同一個 10y 窗口」
    → 0050 跟 006208 start date 完全相同（2026-07-31 為 end，往前推 10y）

檢查：
  - 兩支股票 N 年窗口的 start 跟 end 完全一致（時間對齊）
  - 兩支股票的 years 都是 ~10（不是各自上市首日）
  - 兩支股票都有完整 11 個欄位（含 short 標記）
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
    body = {'profile': '0050_006208', 'n': 10}
    result = _run_analyze(body)
    ps = result['history']['per_stock']
    pny = result['history']['per_stock_n_year']

    # 1. per_stock 仍然各股不同起點
    assert ps['0050']['years'] > 20, f'0050 full-history years 應 > 20: {ps["0050"]["years"]}'
    assert 10 < ps['006208']['years'] < 20, f'006208 full-history years 應 10~20: {ps["006208"]["years"]}'
    print(f'OK: per_stock 仍是各股完整歷史 (0050={ps["0050"]["years"]:.2f}y, 006208={ps["006208"]["years"]:.2f}y)')

    # 2. per_stock_n_year 是時間對齊版：兩支股票的 start/end 完全一致
    end_0050 = pny['0050']['end']
    end_006208 = pny['006208']['end']
    start_0050 = pny['0050']['start']
    start_006208 = pny['006208']['start']
    assert start_0050 == start_006208, f'N 年窗口起點不一致: 0050={start_0050}, 006208={start_006208}'
    assert end_0050 == end_006208, f'N 年窗口終點不一致: 0050={end_0050}, 006208={end_006208}'
    print(f'OK: N 年窗口對齊 ({start_0050} ~ {end_0050})')

    # 3. N 年區間內兩支都有完整 11 欄位
    expected = {'n_years', 'years', 'start', 'end', 'rows', 'first_close', 'last_close',
                'total_return', 'cagr', 'mdd', 'volatility', 'sharpe', 'short'}
    for ticker, info in pny.items():
        missing = expected - set(info.keys())
        assert not missing, f'{ticker} 缺欄位: {missing}'
    print(f'OK: 兩支股票都有完整 {len(expected)} 欄位')

    # 4. N 年區間內的 years 應該 ~10（不是 23 也不是 14）
    assert abs(pny['0050']['years'] - 10) < 0.1, f'0050 N 年 years 應 ≈ 10: {pny["0050"]["years"]}'
    assert abs(pny['006208']['years'] - 10) < 0.1, f'006208 N 年 years 應 ≈ 10: {pny["006208"]["years"]}'
    print(f'OK: N 年區間 years 都是 10y ({pny["0050"]["years"]:.2f}, {pny["006208"]["years"]:.2f})')

    # 5. HTML 兩個表格都在
    html = render_html_report(result, '0050_006208')
    assert '一.五、各標的歷史真實績效' in html, '完整歷史表標題沒出現'
    assert '一.六、各標的 N 年區間對齊' in html, 'N 年對齊表標題沒出現'
    assert '(10y)' in html, 'N=10 標示沒出現'
    print(f'OK: HTML 兩個表格都渲染 ({len(html)} chars)')
    return 0


if __name__ == '__main__':
    sys.exit(main())