#!/usr/bin/env python3
"""
Repro: HTML report on 0050_6208.csv should show per-stock 8-column table
(開始日期/結束日期/回測年數/累積總報酬率/年化報酬率/歷史最大跌幅/年化波動率/性價比).

之前 result['history']['per_stock'] 只回傳 years/start/end/rows/first_close/last_close
6 個欄位，沒有 5 個進階指標 (total_return/cagr/mdd/volatility/sharpe)。
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
    per = result['history']['per_stock']

    # 1) 結構檢查
    expected_fields = {
        'years', 'start', 'end', 'rows',
        'first_close', 'last_close',
        'total_return', 'cagr', 'mdd', 'volatility', 'sharpe',
    }
    for ticker, info in per.items():
        missing = expected_fields - set(info.keys())
        assert not missing, f'{ticker} 缺欄位: {missing}'
    print(f'OK: 兩支股票都有完整 {len(expected_fields)} 欄位')

    # 2) 數值合理性（0050 + 6208 都是上市 > 20 年的正報酬股）
    for ticker, info in per.items():
        assert info['years'] > 13, f'{ticker} years 應 > 13: {info["years"]}'
        assert info['total_return'] > 0, f'{ticker} total_return 應 > 0: {info["total_return"]}'
        assert info['cagr'] is not None and 0 < info['cagr'] < 0.3, f'{ticker} cagr 異常: {info["cagr"]}'
        assert info['mdd'] is not None and info['mdd'] > -1.0, f'{ticker} mdd 異常 (-100%): {info["mdd"]}'
        assert info['volatility'] is not None and 0.1 < info['volatility'] < 1.0, f'{ticker} vol 異常: {info["volatility"]}'
        assert info['sharpe'] is not None and -1 < info['sharpe'] < 5, f'{ticker} sharpe 異常: {info["sharpe"]}'
    print(f'OK: 數值合理性檢查通過 (CAGR>0 / MDD>-100% / Sharpe 合理範圍)')

    # 3) HTML 報告檢查
    html = render_html_report(result, '0050_6208')
    assert '一.五、各標的歷史真實績效' in html, '新 card 標題沒出現'
    assert '歷史最大跌幅 (MDD)' in html, 'MDD 欄位 header 沒出現'
    assert '年化波動率' in html, '波動率欄位 header 沒出現'
    assert '性價比 (Sharpe)' in html, 'Sharpe 欄位 header 沒出現'
    assert '1820.06%' in html, '0050 含息+split v3 股數追蹤法 total_return=1820.06% 沒出現'
    assert '13.66%' in html, '0050 含息+split v3 CAGR=13.66% 沒出現'
    print(f'OK: HTML 報告渲染正確')

    # 4) 列印給人看
    print()
    print('=== per_stock 8 欄位輸出 ===')
    headers = ['股票', '開始', '結束', '年數', '總報酬率', 'CAGR', 'MDD', '波動率', 'Sharpe']
    print('  ' + ' | '.join(f'{h:>12s}' for h in headers))
    for t, info in sorted(per.items()):
        def fmt(v, decimals=2, suffix='%'):
            if v is None: return '—'
            return f'{v*100:.{decimals}f}{suffix}' if suffix == '%' else f'{v:.{decimals}f}'
        row = [
            t, info['start'], info['end'], f"{info['years']:.2f}",
            fmt(info['total_return']), fmt(info['cagr']),
            fmt(info['mdd']), fmt(info['volatility']),
            f"{info['sharpe']:.2f}" if info['sharpe'] is not None else '—',
        ]
        print('  ' + ' | '.join(f'{c:>12s}' for c in row))
    return 0


if __name__ == '__main__':
    sys.exit(main())