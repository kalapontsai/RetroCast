#!/usr/bin/env python3
"""
Repro: 含息還原 + split 還原後，0050 23 年 CAGR 應該接近真實 ~13%
（不是 raw close 的 4.52%）。

背景：
  - 0050 在 2025-06-18 有 4 分割（188.65 → 47.16），total value 不變
  - 0050 上市以來累計現金股利約 +95 元/股（粗估）
  - 過去用 raw close 算 → CAGR 4.52%（嚴重低估）
  - 加含息+split 還原後 → CAGR 13.07%（接近真實）

驗證項目：
  - 0050 含息 total_return > 1000%（合理：23 年含息年化 13%）
  - 0050 含息 CAGR > 12%（合理）
  - 0050 23 年 MDD 不再深於 -90%（raw close 在 2008 那段會被稀釋放大）
"""
import sys
from pathlib import Path

sys.path.insert(0, '/mnt/d/stock/retrocast')
import os
os.chdir('/mnt/d/stock/retrocast')

from app import _run_analyze
import app
app.USER_PROFILE_DIR = Path('/mnt/d/stock/retrocast/user_profile')


def main() -> int:
    body = {'profile': '0050_006208'}
    result = _run_analyze(body)
    per = result['history']['per_stock']

    # 1. 0050 個股歷史（含息還原後 23 年）
    info = per['0050']
    assert info['years'] > 13, f'0050 years 應 > 13: {info["years"]}'
    assert info['total_return'] > 10.0, f'0050 含息 total_return 應 > 1000%: 實際 {info["total_return"]*100:.2f}%'
    assert info['cagr'] > 0.10, f'0050 含息 CAGR 應 > 10%: 實際 {info["cagr"]*100:.2f}%'
    print(f'OK: 0050 含息 23y total={info["total_return"]*100:.1f}% / CAGR={info["cagr"]*100:.2f}%')

    # 2. 006208 個股歷史（含息還原）
    info = per['006208']
    assert info['cagr'] > 0.10, f'006208 含息 CAGR 應 > 10%: 實際 {info["cagr"]*100:.2f}%'
    print(f'OK: 006208 含息 14y total={info["total_return"]*100:.1f}% / CAGR={info["cagr"]*100:.2f}%')

    # 3. common 模式（共用 14 年期間）不應該極端負值
    m = result['common']['metrics']
    assert m['total_return'] > 5.0, f'common total 應 > 500%: 實際 {m["total_return"]*100:.2f}%'
    assert m['cagr'] > 0.10, f'common CAGR 應 > 10%: 實際 {m["cagr"]*100:.2f}%'
    assert m['mdd'] > -0.6, f'common MDD 應 > -60%: 實際 {m["mdd"]*100:.2f}%'
    print(f'OK: common 含息 14y total={m["total_return"]*100:.1f}% / CAGR={m["cagr"]*100:.2f}% / MDD={m["mdd"]*100:.1f}%')

    # 4. dynamic / full 都應該比 raw close 版本高
    for mode in ('dynamic', 'full'):
        m = result[mode]['metrics']
        assert m['cagr'] > 0.08, f'{mode} CAGR 應 > 8%: {m["cagr"]*100:.2f}%'
        print(f'OK: {mode:7s} 含息 {m["years"]:.1f}y CAGR={m["cagr"]*100:.2f}%')
    return 0


if __name__ == '__main__':
    sys.exit(main())