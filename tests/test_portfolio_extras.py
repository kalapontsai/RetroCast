"""
tests/test_portfolio_extras.py
- compute_market_value
- per_stock_history
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.portfolio import compute_market_value, per_stock_history


def _make_prices():
    """假 3 支股票、各 5 天的收盤價"""
    dates = pd.bdate_range('2024-01-01', periods=5)
    return pd.DataFrame({
        '2330': [500.0, 505.0, 510.0, 508.0, 512.0],
        '2317': [80.0, 81.0, 80.5, 82.0, 83.0],
        '0050': [120.0, 121.0, 122.5, 122.0, 123.0],
    }, index=dates)


def test_compute_market_value_default_as_of():
    """不指定 as_of → 用最後一天"""
    p = _make_prices()
    mv = compute_market_value(p, {'2330': 100, '2317': 1000})
    assert mv['as_of'] == '2024-01-05'  # 5 個 bdate
    assert mv['total'] == 512 * 100 + 83 * 1000  # 51200 + 83000 = 134200
    assert len(mv['per_stock']) == 2
    assert mv['missing'] == []


def test_compute_market_value_with_as_of():
    """指定 as_of → 用 ≤ 該日的最後共同交易日"""
    p = _make_prices()
    mv = compute_market_value(p, {'2330': 100}, as_of='2024-01-04')
    assert mv['as_of'] == '2024-01-04'
    assert mv['total'] == 508 * 100


def test_compute_market_value_missing_ticker():
    """shares 裡有 prices 沒有的 ticker → missing"""
    p = _make_prices()
    mv = compute_market_value(p, {'2330': 100, '9999': 50})
    assert mv['total'] == 51200
    assert mv['missing'] == ['9999']


def test_compute_market_value_empty():
    mv = compute_market_value(pd.DataFrame(), {'2330': 100})
    assert mv['total'] == 0
    assert mv['missing'] == ['2330']


def test_per_stock_history():
    p = _make_prices()
    h = per_stock_history(p)
    assert set(h.keys()) == {'2330', '2317', '0050'}
    for t, info in h.items():
        assert info['rows'] == 5
        assert info['start'] == '2024-01-01'
        assert info['end'] == '2024-01-05'
        assert info['years'] > 0
        assert info['first_close'] > 0
        assert info['last_close'] is not None
        assert info['last_close'] > 0


def test_per_stock_history_empty_column():
    p = _make_prices()
    p['9999'] = float('nan')  # 全部 NaN
    h = per_stock_history(p)
    assert h['9999']['rows'] == 0
    assert h['9999']['years'] == 0
    assert h['9999']['first_close'] is None
    assert h['9999']['last_close'] is None
    assert h['9999']['start'] is None
    assert h['9999']['end'] is None
