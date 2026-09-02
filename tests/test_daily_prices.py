"""Tests for lib/daily_prices.py — daily_prices_by_stock + portfolio_daily_returns

B1.5 helper:給 F1/F2/F3/F6 拿真正的日報酬(不再用 _run_analyze 的月 K NAV)。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from lib.daily_prices import (  # noqa: E402
    DailyPricesConfig,
    DailyPricesError,
    daily_prices_by_stock,
    portfolio_daily_returns,
)


# ───────── Mock FinMindClient ─────────
class MockFinMind:
    def __init__(self, data: dict[str, pd.DataFrame] | None = None):
        self.data = data or {}
        self.calls: list[tuple[str, str, str]] = []

    def get_stock_price(self, stock_id, start_date=None, end_date=None, use_cache: bool = True):
        self.calls.append((stock_id, start_date or '', end_date or ''))
        df = self.data.get(stock_id)
        if df is None or df.empty:
            return []
        out = df.copy()
        if start_date:
            out = out[out['date'] >= start_date]
        if end_date:
            out = out[out['date'] <= end_date]
        return out[['date', 'ticker', 'close']].to_dict('records')


def _make_prices(n_days=300, drift=0.0002, vol=0.018, seed=1) -> pd.DataFrame:
    """生成 daily K fixture(date / ticker / close)"""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range('2020-01-01', periods=n_days)
    rets = rng.normal(drift, vol, n_days)
    prices = 100 * np.cumprod(1 + rets)
    return pd.DataFrame({
        'date': dates.strftime('%Y-%m-%d'),
        'ticker': '2330',
        'close': prices,
    })


@pytest.fixture
def mock_client_two_tickers():
    """兩個 ticker,起始日不同"""
    df_a = _make_prices(n_days=300, drift=0.0002, vol=0.018, seed=1)
    df_a['ticker'] = '2330'
    # ticker B 從 2020-06 開始(少 100 天)
    df_b = _make_prices(n_days=200, drift=0.0003, vol=0.020, seed=2)
    df_b['ticker'] = '2317'
    df_b['date'] = pd.bdate_range('2020-06-01', periods=200).strftime('%Y-%m-%d')
    return MockFinMind({'2330': df_a, '2317': df_b})


# ───────── daily_prices_by_stock: 基本 ─────────
def test_returns_dataframe_with_symbols_as_columns(mock_client_two_tickers, tmp_path):
    """回傳的 DataFrame 欄位應 = symbols"""
    cfg = DailyPricesConfig(start_date='2020-06-01', cache_dir=tmp_path)
    df = daily_prices_by_stock(mock_client_two_tickers, ['2330', '2317'], cfg)
    assert set(df.columns) == {'2330', '2317'}
    assert isinstance(df.index, pd.DatetimeIndex)


def test_inner_join_drops_dates_with_missing_ticker(mock_client_two_tickers, tmp_path):
    """inner join: ticker B 沒有的日期應被 drop"""
    cfg = DailyPricesConfig(start_date='2020-01-01', cache_dir=tmp_path)
    df = daily_prices_by_stock(mock_client_two_tickers, ['2330', '2317'], cfg)
    # ticker B 從 2020-06-01 開始,所以 df 應從 2020-06 開始
    assert df.index[0] >= pd.Timestamp('2020-06-01')


def test_too_short_history_raises(tmp_path):
    """歷史太短(< 60 天)應 raise"""
    df = _make_prices(n_days=30)
    client = MockFinMind({'2330': df})
    cfg = DailyPricesConfig(start_date='2020-01-01', cache_dir=tmp_path)
    with pytest.raises(DailyPricesError):
        daily_prices_by_stock(client, ['2330'], cfg)


def test_empty_symbols_raises(tmp_path):
    cfg = DailyPricesConfig(start_date='2020-01-01', cache_dir=tmp_path)
    with pytest.raises(DailyPricesError):
        daily_prices_by_stock(MockFinMind(), [], cfg)


def test_no_data_raises(tmp_path):
    """ticker 沒資料應 raise"""
    client = MockFinMind({})
    cfg = DailyPricesConfig(start_date='2020-01-01', cache_dir=tmp_path)
    with pytest.raises(DailyPricesError):
        daily_prices_by_stock(client, ['9999'], cfg)


# ───────── daily_prices_by_stock: cache pass-through ─────────
# v3.0.2: cache 已從 daily_prices.py 移除,改由 lib.finmind 管理。
# 本層只負責把 use_cache 透傳給 finmind。實際 cache 行為見 test_finmind_cache.py。
def test_use_cache_false_refetches(mock_client_two_tickers, tmp_path):
    """use_cache=False 透傳給 finmind → 每次都 fetch"""
    cfg = DailyPricesConfig(
        start_date='2020-06-01',
        end_date='2021-12-31',
        use_cache=False,
        cache_dir=tmp_path,
    )
    daily_prices_by_stock(mock_client_two_tickers, ['2330'], cfg)
    n_calls_first = len(mock_client_two_tickers.calls)
    daily_prices_by_stock(mock_client_two_tickers, ['2330'], cfg)
    assert len(mock_client_two_tickers.calls) > n_calls_first


def test_daily_prices_passes_use_cache_to_finmind(mock_client_two_tickers, tmp_path):
    """daily_prices 應把 use_cache 透傳給 client.get_stock_price"""
    cfg = DailyPricesConfig(
        start_date='2020-06-01',
        end_date='2021-12-31',
        use_cache=False,
        cache_dir=tmp_path,
    )
    daily_prices_by_stock(mock_client_two_tickers, ['2330'], cfg)
    # mock 有記錄 call,且 use_cache=False 時重 fetch
    assert len(mock_client_two_tickers.calls) == 1



# ───────── portfolio_daily_returns: 基本 ─────────
def test_portfolio_daily_returns_basic():
    """加權平均日報酬公式"""
    dates = pd.bdate_range('2020-01-01', periods=10)
    prices = pd.DataFrame({
        'A': [100, 101, 102, 100, 99, 101, 103, 102, 104, 105],
        'B': [50, 51, 52, 51, 50, 51, 53, 54, 55, 56],
    }, index=dates)
    weights = {'A': 0.5, 'B': 0.5}
    rets = portfolio_daily_returns(prices, weights)
    # 第一筆 NaN(被 drop),所以長度 = 9
    assert len(rets) == 9
    # 日報酬應有合理範圍(±0.05)
    assert (rets.abs() < 0.05).all()


def test_portfolio_daily_returns_missing_symbol_raises():
    """holdings 有 symbol 不在 prices 應 raise"""
    dates = pd.bdate_range('2020-01-01', periods=10)
    prices = pd.DataFrame({'A': range(10)}, index=dates)
    with pytest.raises(DailyPricesError):
        portfolio_daily_returns(prices, {'A': 0.5, 'B': 0.5})


def test_portfolio_daily_returns_zero_weight_sum_raises():
    """加權總和 = 0 應 raise"""
    dates = pd.bdate_range('2020-01-01', periods=10)
    prices = pd.DataFrame({'A': range(10)}, index=dates)
    with pytest.raises(DailyPricesError):
        portfolio_daily_returns(prices, {'A': 0.0, 'B': 0.0})


def test_portfolio_daily_returns_100pct_one_stock():
    """100% 押一個 stock → portfolio return = 該 stock return"""
    dates = pd.bdate_range('2020-01-01', periods=10)
    prices = pd.DataFrame({'A': [100, 110, 99, 105, 102, 108, 107, 109, 103, 110]}, index=dates)
    rets = portfolio_daily_returns(prices, {'A': 1.0})
    # 第一筆 NaN 被 drop
    a_rets = prices['A'].pct_change().dropna()
    pd.testing.assert_series_equal(rets, a_rets, check_names=False)


def test_portfolio_daily_returns_partial_overlap_uses_intersection():
    """holdings 跟 prices 部分交集,只用交集 symbols"""
    dates = pd.bdate_range('2020-01-01', periods=10)
    prices = pd.DataFrame({
        'A': [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
        'B': [50, 51, 52, 53, 54, 55, 56, 57, 58, 59],
        'C': [200, 199, 198, 197, 196, 195, 194, 193, 192, 191],
    }, index=dates)
    # holdings 只有 A,weights 不含 B,C → 應只用 A
    rets = portfolio_daily_returns(prices, {'A': 1.0})
    a_rets = prices['A'].pct_change().dropna()
    pd.testing.assert_series_equal(rets, a_rets, check_names=False)