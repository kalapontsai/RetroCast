"""tests/test_app.py
- 測試 app.py 模組層級的 helpers (目前只有 default_end_date)
- 跟 Flask create_app() 沒直接關係,只測純函式邏輯
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import default_end_date


class TestDefaultEndDate:
    """v3.0.2: 回測 end_date 預設為「前一個月最後一天」"""

    def test_mid_month_returns_last_of_prev_month(self):
        """8/27 → 2026-07-31"""
        assert default_end_date(date(2026, 8, 27)) == '2026-07-31'

    def test_first_day_of_month_returns_last_of_prev_month(self):
        """8/1 → 2026-07-31 (月初也算「這個月」,回上個月最後一天)"""
        assert default_end_date(date(2026, 8, 1)) == '2026-07-31'

    def test_last_day_of_month_returns_last_of_prev_month(self):
        """8/31 → 2026-07-31 (月底當天還算這個月)"""
        assert default_end_date(date(2026, 8, 31)) == '2026-07-31'

    def test_january_cross_year_returns_dec_31(self):
        """1 月跨年: 2026/1/15 → 2025-12-31"""
        assert default_end_date(date(2026, 1, 15)) == '2025-12-31'

    def test_february_28_or_29(self):
        """2 月: 3/1 → 前一個月最後一天 (閏年/平年都對)"""
        # 平年 2026
        assert default_end_date(date(2026, 3, 1)) == '2026-02-28'
        # 閏年 2024
        assert default_end_date(date(2024, 3, 1)) == '2024-02-29'

    def test_december_returns_nov_30(self):
        """12 月: 12/15 → 2026-11-30"""
        assert default_end_date(date(2026, 12, 15)) == '2026-11-30'

    def test_april_30(self):
        """4 月只有 30 天: 5/1 → 2026-04-30"""
        assert default_end_date(date(2026, 5, 1)) == '2026-04-30'

    def test_default_no_arg_uses_today(self):
        """不傳 today 應回當下「前一個月最後一天」(不驗證精確值,只驗證格式)"""
        result = default_end_date()
        # YYYY-MM-DD 格式
        assert len(result) == 10
        assert result[4] == '-' and result[7] == '-'


# ───────── v3.0.4 fix: _build_analyze_meta NaN/Inf leak ─────────
class TestBuildAnalyzeMetaNoNaNLeak:
    """daily_returns_by_ticker 不該 leak inf (某天 close=0 → pct_change 出 ±inf)"""

    def _fake_client_with_close_zero_rows(self, rows):
        from unittest.mock import MagicMock
        c = MagicMock()
        c.get_stock_price = MagicMock(return_value=rows)
        return c

    def test_close_zero_does_not_leak_inf(self):
        """構造含 close=0 的 rows, 確認 result 無 inf/nan"""
        import math
        from app import _build_analyze_meta
        rows = [
            {'date': '2024-01-01', 'close': 100.0},
            {'date': '2024-01-02', 'close': 105.0},
            {'date': '2024-01-03', 'close': 0.0},
            {'date': '2024-01-04', 'close': 50.0},
            {'date': '2024-01-05', 'close': 0.0},   # (0-50)/50=-1
            {'date': '2024-01-06', 'close': 0.0},   # (0-0)/0=nan
            {'date': '2024-01-07', 'close': 200.0},  # (200-0)/0=+inf ← 重點
        ]
        client = self._fake_client_with_close_zero_rows(rows)
        result = _build_analyze_meta(client, ['6208'], '2024-01-01', '2024-01-31')

        daily = result['daily_returns_by_ticker']['6208']
        for entry in daily:
            assert not math.isinf(entry['ret']), f'leaked inf: {entry}'
            assert not math.isnan(entry['ret']), f'leaked nan: {entry}'

    def test_meta_dumpable_with_allow_nan_false(self):
        """result 必須能被 json.dumps(allow_nan=False) 處理 (= 沒 NaN/Inf)"""
        import json
        from app import _build_analyze_meta
        rows = [
            {'date': '2024-01-01', 'close': 100.0},
            {'date': '2024-01-02', 'close': 0.0},
            {'date': '2024-01-03', 'close': 200.0},
        ]
        client = self._fake_client_with_close_zero_rows(rows)
        result = _build_analyze_meta(client, ['6208'], '2024-01-01', '2024-01-31')
        # 允許 nan/inf 也能 dump (SafeJSONEncoder 會清), 但健全代碼應該可以直接 dump
        json.dumps(result, allow_nan=False)  # 不應 raise
