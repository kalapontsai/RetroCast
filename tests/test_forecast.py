"""
tests/test_forecast.py
- 測試 N-Year rolling CAGR + 百分位數 + 終值
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.forecast import (
    ForecastError, build_forecast, future_value, rolling_n_year_cagr,
    scenario_percentiles,
)


def _make_nav(start: str = '2010-01-01', years: int = 20, daily_drift: float = 0.0004, seed: int = 42) -> pd.Series:
    """總報酬持續上升的假 NAV"""
    rng = np.random.default_rng(seed)
    n = years * 252
    idx = pd.bdate_range(start, periods=n)
    rets = rng.normal(daily_drift, 0.015, size=n)
    nv = np.exp(np.cumsum(rets))
    return pd.Series(nv, index=idx, name='NAV')


def test_future_value_basic():
    assert future_value(1_000_000, 0.10, 10) == pytest.approx(2_593_742.46, rel=1e-3)


def test_rolling_n_year_cagr_basic():
    nav = _make_nav(years=20)
    df = rolling_n_year_cagr(nav, n=10)
    assert len(df) > 0
    assert (df['years'] >= 10 * 0.95).all()
    assert (df['cagr'] > -1).all() and (df['cagr'] < 1).all()


def test_rolling_too_short_raises():
    nav = _make_nav(years=3)
    with pytest.raises(ForecastError):
        rolling_n_year_cagr(nav, n=10)


def test_scenario_percentiles_ordering():
    nav = _make_nav(years=20)
    df = rolling_n_year_cagr(nav, n=10)
    p = scenario_percentiles(df)
    # P10 < P25 < P50 < P75 < P90
    assert p['Bear'] <= p['Conservative']
    assert p['Conservative'] <= p['Base']
    assert p['Base'] <= p['Optimistic']
    assert p['Optimistic'] <= p['Bull']


def test_build_forecast_full():
    nav = _make_nav(years=20)
    out = build_forecast(nav, n=10, pv=1_000_000)

    assert out['n'] == 10
    assert out['pv'] == 1_000_000
    assert out['rolling_count'] > 0
    assert out['r_count'] > 0
    assert out['r_count'] == out['rolling_count']  # 兩個名子是同一個值（compatibility alias）
    assert len(out['scenarios']) == 5
    assert all(s['fv'] > 0 for s in out['scenarios'])
    # Base (P50) 倍數應該 >= 1，若 CAGR > 0
    base = next(s for s in out['scenarios'] if s['label'] == 'Base')
    if base['cagr'] > 0:
        assert base['multiplier'] > 1
    # FV 應該隨 CAGR 遞增
    cagrs = [s['cagr'] for s in out['scenarios']]
    assert cagrs == sorted(cagrs)
    # 驗證 quantile 欄位是數字
    assert all(isinstance(s['quantile'], (int, float)) for s in out['scenarios'])
    # 驗證 label 是字串
    assert all(isinstance(s['label'], str) for s in out['scenarios'])


def test_build_forecast_invalid_n():
    nav = _make_nav(years=20)
    with pytest.raises(ForecastError):
        build_forecast(nav, n=0, pv=1_000_000)


def test_build_forecast_short_history():
    nav = _make_nav(years=2)
    with pytest.raises(ForecastError):
        build_forecast(nav, n=10, pv=1_000_000)
