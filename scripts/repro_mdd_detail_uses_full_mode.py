#!/usr/bin/env python3
"""Regression: 報告裡的 MDD 詳細表必須用 full mode，不是 common mode

歷史教訓：
- 2026-08-31 14:25 主人在 elhomeo_stock 報告看到 MDD 詳細表是 -11.86%
- 但 common mode 對 elhomeo 其實只有 0.487 年 (含 2026 才上市的股票)
- 三模式 KPI 卡顯示 common=-26.39% / dynamic=-30.17% / full=-19.63%
- 詳細表卻顯示 -11.86% (用 common 但 common 區間被早期事件拉短)
- 主人說「前面的三種模式都比這個值大」→ 指出詳細表該用 full mode
- v5 fix: template 把 common_m 換成 full_m + 加說明文字

鎖住：對 elhomeo_stock profile，
  - 報告 MDD 詳細表的 mdd_peak_date 必須在 2000~2008 之間 (full mode 起點 2000-01-04)
  - 不能是 2026-06 之類的近期日期 (那代表還在用 common mode)

用法：
  python3 scripts/repro_mdd_detail_uses_full_mode.py

預期：OK 通過
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from app import _run_analyze  # noqa: PLC0415
    import app  # noqa: PLC0415

    app.USER_PROFILE_DIR = Path('/mnt/d/stock/retrocast/user_profile')
    body = {'profile': 'elhomeo_stock', 'n': 3}
    result = _run_analyze(body)
    html = app.render_html_report(result, profile_name='elhomeo_stock')

    print('=== MDD 詳細表 regression check ===')

    # 抽 MDD 詳細區塊
    m = re.search(r'▶ MDD 詳細.*?</table>', html, re.DOTALL)
    if not m:
        print('❌ FAIL: 報告找不到 MDD 詳細區塊')
        return 1

    section = m.group(0)
    # 抓 mdd_peak_date
    peak_m = re.search(r'Peak Date.*?<td>(\d{4}-\d{2}-\d{2})', section, re.DOTALL)
    trough_m = re.search(r'Trough Date.*?<td>(\d{4}-\d{2}-\d{2})', section, re.DOTALL)
    recovery_m = re.search(r'Recovery Date.*?<td>([^<]+)', section, re.DOTALL)
    mdd_m = re.search(r'歷史最大回撤.*?<b[^>]*>(-?[0-9.]+)%', section, re.DOTALL)

    if not peak_m or not trough_m:
        print('❌ FAIL: 找不到 Peak/Trough 日期')
        return 1

    peak_year = int(peak_m.group(1)[:4])
    trough_year = int(trough_m.group(1)[:4])

    print(f'  Peak: {peak_m.group(1)}')
    print(f'  Trough: {trough_m.group(1)}')
    print(f'  Recovery: {recovery_m.group(1) if recovery_m else "?"}')
    print(f'  MDD: {mdd_m.group(1) if mdd_m else "?"}%')
    print()

    # 鎖住條件：elhomeo_stock full mode 區間是 2000-01-04 ~ 2026-07-31 (26.57 年)
    # full mode MDD 會在 2008 金融海嘯附近 (peak 2008-05, trough 2008-10)
    ok = True
    if peak_year >= 2020:
        print(f'❌ FAIL: Peak {peak_year} 太晚 → 還在用 common mode (0.5 年區間)')
        ok = False
    else:
        print(f'✅ OK: Peak {peak_year} 在 2000~2019 → 使用 full mode')

    if trough_year >= 2020:
        print(f'❌ FAIL: Trough {trough_year} 太晚 → 還在用 common mode')
        ok = False
    else:
        print(f'✅ OK: Trough {trough_year} 在 2000~2019 → 使用 full mode')

    # MDD 應該 < -20% (full mode 有 26 年, 必有大回撤)
    if mdd_m:
        mdd_val = abs(float(mdd_m.group(1)))
        if mdd_val < 15:
            print(f'❌ FAIL: MDD {mdd_val:.2f}% 太小 → 應該用 full mode 才能看到長期大回撤')
            ok = False
        else:
            print(f'✅ OK: MDD {mdd_val:.2f}% 合理範圍')

    if not ok:
        print()
        print('💡 解法：')
        print('  1. 檢查 templates/report.html 是否還在用 common_m 而非 full_m')
        print('  2. cp 到 /mnt/d/stock/retrocast/templates/report.html')
        print('  3. 清 pycache + 重啟 Flask')
        return 1

    print()
    print('✅ MDD 詳細表使用 full mode regression PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
