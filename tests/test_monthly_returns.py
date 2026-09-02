"""tests/test_monthly_returns.py - v3.0.3 N8"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.monthly_returns import compute_monthly_returns_by_ticker  # noqa: E402


def _make_daily(ticker: str, years: list, monthly_returns: list) -> pd.Series:
    """Mock daily_returns 用月初固定報酬模擬"""
    idx = pd.date_range(start=f"{years[0]}-01-01", periods=len(monthly_returns) * 21,
                        freq='B', tz=None)
    vals = []
    for i, mret in enumerate(monthly_returns):
        # 21 個交易日,每個 = (1+mret)**(1/21) - 1
        daily = (1 + mret) ** (1/21) - 1
        vals.extend([daily] * 21)
    return pd.Series(vals[:len(idx)], index=idx, name=ticker)


def test_empty_input_returns_empty():
    out = compute_monthly_returns_by_ticker({})
    assert out == {'tickers': []}


def test_single_ticker_single_year():
    s = _make_daily('0050', [2024], [0.01] * 12)
    out = compute_monthly_returns_by_ticker({'0050': s})
    assert len(out['tickers']) == 1
    t = out['tickers'][0]
    assert t['ticker'] == '0050'
    assert t['first_year'] == 2024
    assert t['last_year'] == 2024
    assert 2024 in t['data']
    months = t['data'][2024]
    assert len([k for k in months if k != 'year_avg']) == 12
    assert 'year_avg' in months
    assert isinstance(months['year_avg'], float)


def test_year_avg_is_arithmetic_mean():
    # 1-12 月各有不同報酬,平均應該是 arithmetic mean
    s = _make_daily('0050', [2024], [0.01, 0.02, -0.01, 0.03, 0.0, 0.015,
                                    -0.02, 0.025, 0.005, -0.01, 0.04, 0.01])
    out = compute_monthly_returns_by_ticker({'0050': s})
    months = out['tickers'][0]['data'][2024]
    expected = sum([0.01, 0.02, -0.01, 0.03, 0.0, 0.015,
                     -0.02, 0.025, 0.005, -0.01, 0.04, 0.01]) / 12
    assert abs(months['year_avg'] - expected) < 0.001  # 容忍 compounding 浮點誤差


def test_multiple_tickers_sorted_alphabetically():
    s1 = _make_daily('2330', [2024], [0.01] * 12)
    s2 = _make_daily('0050', [2024], [0.02] * 12)
    s3 = _make_daily('2002', [2024], [0.03] * 12)
    out = compute_monthly_returns_by_ticker({'2330': s1, '0050': s2, '2002': s3})
    tickers = [t['ticker'] for t in out['tickers']]
    assert tickers == sorted(tickers)


def test_none_values_for_empty_data():
    out = compute_monthly_returns_by_ticker({'0050': pd.Series([], dtype=float)})
    assert out['tickers'] == []


def test_nan_in_daily_returns_handled():
    idx = pd.date_range('2024-01-01', periods=10, freq='B')
    vals = [0.01, np.nan, np.nan, 0.02, np.nan, 0.03, np.nan, 0.04, np.nan, 0.05]
    s = pd.Series(vals, index=idx, name='0050')
    out = compute_monthly_returns_by_ticker({'0050': s})
    # 不應該 crash
    assert len(out['tickers']) == 1


def test_multiple_years():
    s = _make_daily('0050', [2023, 2024], [0.01] * 24)
    out = compute_monthly_returns_by_ticker({'0050': s})
    t = out['tickers'][0]
    assert t['first_year'] == 2023
    assert t['last_year'] == 2024
    assert 2023 in t['data']
    assert 2024 in t['data']


def test_year_avg_none_when_no_valid_months():
    # 全 NaN → year_avg None
    idx = pd.date_range('2024-01-01', periods=20, freq='B')
    vals = [np.nan] * 20
    s = pd.Series(vals, index=idx, name='0050')
    out = compute_monthly_returns_by_ticker({'0050': s})
    # 整組空 → 跳過(tickers 為空)
    assert out['tickers'] == []
