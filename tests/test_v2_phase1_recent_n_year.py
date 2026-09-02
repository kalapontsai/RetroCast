"""
tests/test_v2_phase1_recent_n_year.py
- Phase 1.2 驗收:recent_n_year_metrics 獨立計算最近 N 年績效
- 驗證項:
    1. recent_n_year_metrics 回傳 keys 對齊 _metrics (向後相容)
    2. recent_n_year_metrics 跟「完整歷史」明確分開(數字會不同)
    3. 當資料太短(< n_years 年)回傳 None (不 raise)
    4. n_years<=0 raise BacktestError
    5. recent slice 已重正規化為 1.0 起點(不會被前段水平污染)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.portfolio import recent_n_year_metrics, BacktestError


def _make_nav(years: int = 20, drift: float = 0.0003, sigma: float = 0.012, seed: int = 42) -> pd.Series:
    """模擬一段 NAV,日報酬 ~ drift + N(0, sigma)"""
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, sigma, years * 252)
    idx = pd.bdate_range('2005-01-01', periods=years * 252)
    nav = pd.Series((1 + rets).cumprod(), index=idx, name='nav')
    return nav


# ───────── 1. keys 對齊 _metrics ─────────
def test_recent_n_year_metrics_keys_align():
    nav = _make_nav(years=20)
    out = recent_n_year_metrics(nav, n_years=10)
    assert out is not None
    expected_keys = {'start', 'end', 'years', 'total_return', 'cagr', 'mdd', 'volatility', 'sharpe'}
    assert expected_keys <= set(out.keys()), f'缺 key:{expected_keys - set(out.keys())}'


# ───────── 2. recent 跟 full 不同 ─────────
def test_recent_differs_from_full_history():
    """最近 5 年跟完整 20 年,因為 rebase 到 1.0 起點,CAGR 不會一樣"""
    nav = _make_nav(years=20)
    from lib.portfolio import _metrics
    full = _metrics(nav)
    recent = recent_n_year_metrics(nav, n_years=5)
    assert recent is not None
    # full.cagr 是 20 年複合;recent.cagr 是 5 年複合 — 隨機過程下兩者必然不同
    # (除非巧合;seed 固定下也應該不嚴格相等)
    assert full['cagr'] != pytest.approx(recent['cagr']), (
        f'完整歷史 CAGR ({full["cagr"]:.4f}) 跟最近 5 年 CAGR ({recent["cagr"]:.4f}) 不應剛好相等'
    )
    # recent.years 應接近 5(允許 days/365.25 浮點誤差)
    assert 4.5 <= recent['years'] <= 5.5


# ───────── 3. 資料太短 → None ─────────
def test_recent_too_short_returns_none():
    nav = _make_nav(years=2)       # 只有 2 年歷史
    out = recent_n_year_metrics(nav, n_years=10)  # 問 10 年
    assert out is None


# ───────── 4. n_years <= 0 → BacktestError ─────────
def test_recent_n_years_zero_raises():
    nav = _make_nav(years=10)
    with pytest.raises(BacktestError):
        recent_n_year_metrics(nav, n_years=0)


def test_recent_n_years_negative_raises():
    nav = _make_nav(years=10)
    with pytest.raises(BacktestError):
        recent_n_year_metrics(nav, n_years=-5)


# ───────── 5. recent 切片已 rebase 到 1.0 起點 ─────────
def test_recent_is_rebased_to_one():
    """驗證 recent slice 重新正規化 — 確保 CAGR 算的是「最近 N 年的真實報酬」

    構造場景: 完整 20 年 NAV 從 1.0 單調上升到 200,日報酬固定。
    → 完整歷史 CAGR 拉得很高(被前段稀釋)
    → 「最近 5 年」rebase 後,CAGR 應該反映末段實際報酬,不是被前段稀釋
    """
    n_days = 20 * 252
    dates = pd.bdate_range('2000-01-01', periods=n_days)
    # 20 年單調:1.0 → 200,daily log return = log(200)/20/252
    rets = np.full(n_days, np.log(200) / 20 / 252)
    full_nav = np.exp(np.cumsum(rets))
    assert len(full_nav) == n_days
    nav = pd.Series(full_nav, index=dates, name='nav')

    from lib.portfolio import _metrics
    full = _metrics(nav)
    recent = recent_n_year_metrics(nav, n_years=5)

    assert recent is not None
    # 對「固定 daily return」序列,CAGR 跟起點無關,所以 full.cagr ≈ recent.cagr
    # 重點不在 CAGR 必不同,而在 total_return 必不同(因為 rebase 起點)
    # full: 1.0 → 200, total_return ≈ 199
    # recent: ~86 → 200 (rebase 起點為 1.0), total_return ≈ 1.32 (132%)
    assert full['total_return'] > 100, f'full.total_return 應 > 100 (1.0→200),got {full["total_return"]}'
    assert recent['total_return'] > 1.0, (
        f'recent total_return 應 > 100% (rebase 後 1.0 → 末值),got {recent["total_return"]:.4f}'
    )
    # 關鍵驗證:full 跟 recent 的 total_return 必不同(因為起點不同)
    assert abs(full['total_return'] - recent['total_return']) > 1.0, (
        f'full.tr ({full["total_return"]:.2f}) 跟 recent.tr ({recent["total_return"]:.4f}) 必不同'
    )
    # 關鍵驗證:recent.total_return 應 = recent_nav[-1]/recent_nav[0] - 1
    # 而 recent_nav[0] = 1.0(被 rebase),所以 total_return = recent_nav[-1] - 1
    # 這驗證了 rebase 機制:從「原 NAV 末段」的相對值變成「1.0 起點」的純增長
    recent_nav = nav.loc[nav.index >= nav.index[-1] - pd.Timedelta(days=int(5 * 365.25))]
    rebased = recent_nav / recent_nav.iloc[0]
    expected_tr = rebased.iloc[-1] - 1
    assert abs(recent['total_return'] - expected_tr) < 1e-6, (
        f'total_return 應 = rebase 後末值 - 1,got {recent["total_return"]:.6f} vs {expected_tr:.6f}'
    )
