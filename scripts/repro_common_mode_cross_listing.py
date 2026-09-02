#!/usr/bin/env python3
"""
Repro: /api/analyze on cross-listing portfolio (0050_6208.csv) used to throw
'沒有共同歷史期間（所有股票起點都不重疊）' even though 0050 (2003-06-30) and
6208 (2002-12-23) actually have overlapping history.

Root cause: `_mode_common` in lib/portfolio.py used
    p.loc[common_start:].dropna(axis=1, how='any')
which dropped a column on ANY missing row. When 6208 still had a handful of
NaN rows after 0050's listing date, both columns got dropped, triggering the
misleading "起點不重疊" error.

Fix: use how='all' so a column is kept as long as it has any data after
common_start, and improve the error message to include per-stock first dates.
"""
import sys, os
from pathlib import Path

# Force runtime under /mnt/d/stock/retrocast
sys.path.insert(0, '/mnt/d/stock/retrocast')
os.chdir('/mnt/d/stock/retrocast')

from app import _run_analyze
import app
app.USER_PROFILE_DIR = Path('/mnt/d/stock/retrocast/user_profile')


def main() -> int:
    body = {'profile': '0050_006208'}
    result = _run_analyze(body)
    assert 'common' in result, "common mode missing"
    common = result['common']
    metrics = common['metrics']
    nav = common['nav']
    print(f"OK: common mode ran")
    print(f"  nav points: {len(nav)}")
    print(f"  metrics: years={metrics['years']:.2f}  cagr={metrics['cagr']*100:.2f}%  "
          f"total_return={metrics['total_return']*100:.2f}%  mdd={metrics['mdd']*100:.2f}%")
    print(f"  first: {nav[0]}")
    print(f"  last : {nav[-1]}")
    assert metrics['years'] > 13, f"expected years>13 (006208 上市 14 年), got {metrics['years']}"
    # 23 年月點 (yearly) 約 23 點以上，nav 通常以週/月顆粒回傳
    assert len(nav) >= 20, f"expected >=20 nav points, got {len(nav)}"
    return 0


if __name__ == '__main__':
    sys.exit(main())