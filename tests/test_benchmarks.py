"""Tests for F5 (Multi-Benchmark Comparison) — lib/benchmarks.py

SPEC §2 F5 acceptance criteria:
- T5.1: 006208 2014-01-01 應自動 trim 到 2017-09-12 起(已知 phantom data)
- T5.2: ^TWII 完整 2014-2026 應可取得
- T5.3: alpha 計算 = portfolio_CAGR - benchmark_CAGR
- 多 benchmark 比較 + 資料不足自動 skip
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lib.benchmarks import (
    BenchmarkConfig,
    BenchmarkError,
    compute_benchmark_compare,
    run_benchmark_compare,
)


# ───────── Fixtures ─────────
@pytest.fixture
def portfolio_nav():
    """5 年 portfolio NAV 上漲 ~12% 年化"""
    rng = np.random.default_rng(55)
    n = 252 * 5
    daily_ret = rng.normal(loc=0.12 / 252, scale=0.012, size=n)
    nav = pd.Series(1_000_000 * np.cumprod(1 + daily_ret))
    nav.index = pd.bdate_range('2020-01-01', periods=n)
    return nav


@pytest.fixture
def bench_0050():
    """0050:8% 年化、15% 波動"""
    rng = np.random.default_rng(66)
    n = 252 * 5
    daily_ret = rng.normal(loc=0.08 / 252, scale=0.015, size=n)
    p = pd.Series(100 * np.cumprod(1 + daily_ret))
    p.index = pd.bdate_range('2020-01-01', periods=n)
    return p


@pytest.fixture
def bench_006208():
    """006208:5% 年化(高股息)、10% 波動"""
    rng = np.random.default_rng(77)
    n = 252 * 5
    daily_ret = rng.normal(loc=0.05 / 252, scale=0.010, size=n)
    p = pd.Series(50 * np.cumprod(1 + daily_ret))
    p.index = pd.bdate_range('2020-01-01', periods=n)
    return p


@pytest.fixture
def bench_twii():
    """v3.0.0 ~ v3.0.1 原本用 ^TWII (加權指數) 作為市場基準,
    但 FinMind 不提供 TAIEX 日價 stock-compatible API,
    故 v3.0.2 拿掉。fixture 留著相容舊 test,內容是「假想大盤代理」"""
    rng = np.random.default_rng(88)
    n = 252 * 5
    daily_ret = rng.normal(loc=0.07 / 252, scale=0.012, size=n)
    p = pd.Series(15000 * np.cumprod(1 + daily_ret))
    p.index = pd.bdate_range('2020-01-01', periods=n)
    return p


@pytest.fixture
def short_bench():
    """資料不足的 benchmark(< 60 天)"""
    dates = pd.bdate_range('2024-01-01', periods=30)
    return pd.Series(np.linspace(100, 110, 30), index=dates)


# ───────── T5.3: alpha 計算正確 ─────────
def test_T5_3_alpha_is_portfolio_minus_benchmark(portfolio_nav, bench_0050):
    """alpha = portfolio_CAGR - benchmark_CAGR"""
    cfg = BenchmarkConfig(benchmarks=['0050'], risk_free_rate=0.015)
    result = compute_benchmark_compare(portfolio_nav, {'0050': bench_0050}, cfg)
    p_cagr = result.portfolio_metrics['cagr']
    b_cagr = result.benchmarks['0050']['cagr']
    expected_alpha = p_cagr - b_cagr
    assert result.vs_portfolio['alpha_vs_0050'] == pytest.approx(expected_alpha, abs=1e-6)


# ───────── 多 benchmark 同時跑 (v3.0.2: 只剩 0050 + 006208 兩個大盤代理) ─────────
def test_multiple_benchmarks(portfolio_nav, bench_0050, bench_006208):
    """兩基準都能跑出 CAGR"""
    cfg = BenchmarkConfig(benchmarks=['0050', '006208'], risk_free_rate=0.015)
    result = compute_benchmark_compare(
        portfolio_nav,
        {'0050': bench_0050, '006208': bench_006208},
        cfg,
    )
    for ticker in ('0050', '006208'):
        assert ticker in result.benchmarks
        assert result.benchmarks[ticker]['cagr'] is not None
        assert result.benchmarks[ticker]['sharpe'] is not None
        assert result.benchmarks[ticker]['mdd'] is not None
    for ticker in ('0050', '006208'):
        assert f'alpha_vs_{ticker}' in result.vs_portfolio
    # ^TWII 不應出現在結果
    assert '^TWII' not in result.benchmarks


# ───────── T5.1: 資料不足的 benchmark 自動 skip ─────────
def test_T5_1_short_benchmark_skipped(portfolio_nav, short_bench):
    """< 60 天 benchmark 應被 skip,不 raise"""
    cfg = BenchmarkConfig(benchmarks=['0050'], risk_free_rate=0.015)
    result = compute_benchmark_compare(portfolio_nav, {'0050': short_bench}, cfg)
    assert '0050' not in result.benchmarks
    assert len(result.skipped) == 1
    assert '0050' in result.skipped[0]


# ───────── 完全沒有資料的 benchmark (v3.0.2: ^TWII → 不存在的 ticker 'XX9999') ─────────
def test_missing_benchmark_handled(portfolio_nav, bench_0050):
    """benchmark_prices dict 裡沒該 ticker → skip"""
    cfg = BenchmarkConfig(benchmarks=['0050', 'XX9999'], risk_free_rate=0.015)
    result = compute_benchmark_compare(portfolio_nav, {'0050': bench_0050}, cfg)
    assert '0050' in result.benchmarks
    assert 'XX9999' not in result.benchmarks
    assert any('XX9999' in s for s in result.skipped)


# ───────── Portfolio metrics 必填欄位 ─────────
def test_portfolio_metrics_present(portfolio_nav, bench_0050):
    """portfolio_metrics 應有 cagr / sharpe / mdd / total_return"""
    cfg = BenchmarkConfig()
    result = compute_benchmark_compare(portfolio_nav, {'0050': bench_0050}, cfg)
    for k in ('cagr', 'sharpe', 'mdd', 'total_return'):
        assert k in result.portfolio_metrics
        assert result.portfolio_metrics[k] is not None


# ───────── Period metadata ─────────
def test_period_metadata(portfolio_nav, bench_0050):
    """period 應有 start / end / days"""
    cfg = BenchmarkConfig()
    result = compute_benchmark_compare(portfolio_nav, {'0050': bench_0050}, cfg)
    assert 'start' in result.period
    assert 'end' in result.period
    assert result.period['days'] == len(portfolio_nav)


# ───────── 邊界:portfolio 為空 ─────────
def test_empty_portfolio_raises():
    with pytest.raises(BenchmarkError):
        compute_benchmark_compare(pd.Series(dtype=float), {'0050': pd.Series([1.0])})


# ───────── 邊界:benchmarks 為空 ─────────
def test_empty_benchmarks_raises(portfolio_nav):
    with pytest.raises(BenchmarkError):
        BenchmarkConfig(benchmarks=[])


# ───────── 邊界:rf < 0 ─────────
def test_negative_rf_raises(portfolio_nav):
    with pytest.raises(BenchmarkError):
        BenchmarkConfig(risk_free_rate=-0.01)


# ───────── run_benchmark_compare wrapper (v3.0.2: ^TWII 已拿掉) ─────────
def test_run_benchmark_compare_wrapper(portfolio_nav, bench_0050, bench_006208):
    body = {
        'benchmarks': ['0050', '006208'],
        'risk_free_rate': 0.02,
    }
    result = run_benchmark_compare(
        portfolio_nav,
        {'0050': bench_0050, '006208': bench_006208},
        body,
    )
    assert 'benchmarks' in result
    assert 'vs_portfolio' in result
    assert result['config']['risk_free_rate'] == 0.02
    # ^TWII 不應在 default config
    assert '^TWII' not in result['config']['benchmarks']


def test_run_benchmark_compare_bad_body(portfolio_nav, bench_0050):
    """壞 config 應 raise BenchmarkError"""
    with pytest.raises(BenchmarkError):
        run_benchmark_compare(
            portfolio_nav,
            {'0050': bench_0050},
            {'benchmarks': 'not-a-list'},
        )


# ───────── Default config 檢查 (v3.0.2: ^TWII 已拿掉) ─────────
def test_default_benchmarks_no_twii():
    """v3.0.2 起 default 沒有 ^TWII(FinMind 無 TAIEX 支援)"""
    cfg = BenchmarkConfig()
    assert '^TWII' not in cfg.benchmarks
    assert '0050' in cfg.benchmarks
    assert '006208' in cfg.benchmarks


# ───────── Sharpe with positive rf ─────────
def test_higher_rf_lowers_sharpe(portfolio_nav, bench_0050):
    """rf 越高 → Sharpe 越低"""
    cfg_low = BenchmarkConfig(risk_free_rate=0.0)
    cfg_high = BenchmarkConfig(risk_free_rate=0.05)
    r_low = compute_benchmark_compare(portfolio_nav, {'0050': bench_0050}, cfg_low)
    r_high = compute_benchmark_compare(portfolio_nav, {'0050': bench_0050}, cfg_high)
    assert r_high.benchmarks['0050']['sharpe'] < r_low.benchmarks['0050']['sharpe']


# ───────── benchmark 對齊 portfolio 日期 ─────────
def test_benchmark_aligned_to_portfolio(portfolio_nav, bench_0050):
    """benchmark 超出 portfolio 日期範圍的點應被自動 drop(reindex)"""
    # benchmark 從更早開始並延伸到 portfolio 結束之後,重疊區間 ≈ portfolio
    extended_dates = pd.bdate_range('2018-01-01', periods=len(portfolio_nav) + 500)
    rng = np.random.default_rng(99)
    long_bench = pd.Series(
        100 * np.cumprod(1 + rng.normal(0.0001, 0.01, len(extended_dates))),
        index=extended_dates,
    )
    cfg = BenchmarkConfig(benchmarks=['0050'])
    result = compute_benchmark_compare(portfolio_nav, {'0050': long_bench}, cfg)
    # 對齊後 days 應近似等於 portfolio 長度(允許 ±30 天 holidays / bday 邊界差)
    assert '0050' in result.benchmarks
    diff = abs(result.benchmarks['0050']['period']['days'] - len(portfolio_nav))
    assert diff < 30, f'aligned days 差 portfolio 太遠: {diff}'
    # 重疊區間應完全包含 portfolio 的日期
    assert result.benchmarks['0050']['period']['start'] >= str(portfolio_nav.index[0].date())


# ───────── MDD 為負 ─────────
def test_mdd_is_negative(portfolio_nav, bench_0050):
    """MDD 永遠 ≤ 0(負值代表回撤)"""
    cfg = BenchmarkConfig()
    result = compute_benchmark_compare(portfolio_nav, {'0050': bench_0050}, cfg)
    assert result.benchmarks['0050']['mdd'] <= 0
    assert result.portfolio_metrics['mdd'] <= 0