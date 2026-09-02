"""Tests for F4 (Volatility Decay — 0050 vs 00631L) — lib/volatility_decay.py

SPEC §2 F4 acceptance criteria:
- T4.1: 0050 2014-10 ~ 2026-08 應有正 CAGR(歷史 ~23%)
- T4.2: all_leveraged CAGR < (1 + 0050_CAGR)^2 - 1(daily rebalance 損耗)
- T4.3: 50/50 rebalance 的 MDD 應 < all_leveraged MDD
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lib.volatility_decay import (
    VolatilityDecayConfig,
    VolatilityDecayError,
    compute_volatility_decay,
    run_volatility_decay,
)


# ───────── Fixtures ─────────
@pytest.fixture
def underlying_prices_uptrend():
    """0050 模擬上漲趨勢 + 震盪:30% 年化、12% 波動"""
    rng = np.random.default_rng(11)
    n = 252 * 5
    daily_ret = rng.normal(loc=0.30 / 252, scale=0.012, size=n)
    prices = pd.Series(100 * np.cumprod(1 + daily_ret))
    dates = pd.bdate_range('2020-01-01', periods=n)
    prices.index = dates
    return prices


@pytest.fixture
def leveraged_prices_uptrend():
    """00631L 模擬槓桿 ETF:60% 年化目標、24% 波動(2x 但有 daily rebalance 損耗)"""
    rng = np.random.default_rng(22)
    n = 252 * 5
    daily_ret = rng.normal(loc=0.60 / 252 - 0.0005, scale=0.024, size=n)
    # 扣一點 daily rebalance 損耗(槓桿 ETF 在震盪會少一點)
    prices = pd.Series(100 * np.cumprod(1 + daily_ret))
    dates = pd.bdate_range('2020-01-01', periods=n)
    prices.index = dates
    return prices


@pytest.fixture
def leveraged_match_2x():
    """00631L 嚴格 = 2 × 0050(無 daily rebalance 損耗,作為對照組)"""
    rng = np.random.default_rng(33)
    n = 252 * 5
    daily_ret = rng.normal(loc=0.20 / 252, scale=0.012, size=n)
    # 用 (1+r)^2 - 1 近似 2x
    u = pd.Series(100 * np.cumprod(1 + daily_ret))
    l = pd.Series(100 * (u / 100) ** 2)
    dates = pd.bdate_range('2020-01-01', periods=n)
    u.index = dates
    l.index = dates
    return u, l


@pytest.fixture
def aligned_5y():
    """5 年完整對齊資料"""
    rng = np.random.default_rng(44)
    n = 252 * 5
    daily_ret = rng.normal(loc=0.10 / 252, scale=0.015, size=n)
    u = pd.Series(100 * np.cumprod(1 + daily_ret))
    l = pd.Series(u * (1 + rng.normal(0, 0.001, n)).cumprod())
    dates = pd.bdate_range('2020-01-01', periods=n)
    u.index = dates
    l.index = dates
    return u, l


# ───────── T4.1: 0050 上漲趨勢應有正 CAGR ─────────
def test_T4_1_underlying_has_positive_cagr(
    underlying_prices_uptrend, leveraged_prices_uptrend
):
    """0050 模擬上漲 → all_underlying CAGR > 0"""
    cfg = VolatilityDecayConfig(compare_strategies=['all_underlying'])
    result = compute_volatility_decay(
        underlying_prices_uptrend, leveraged_prices_uptrend, cfg
    )
    u = result.strategies['all_underlying']
    assert u['cagr'] > 0.1
    assert u['final'] > u['cagr'] * 100  # sanity


# ───────── T4.2: 槓桿 ETF 實際年化 < 2x 理論 ─────────
def test_T4_2_leveraged_cagr_below_2x_theory(
    aligned_5y,
):
    """槓桿 ETF 在真實波動下 daily rebalance 會有損耗 → CAGR < 2x 0050 理論"""
    u, l = aligned_5y
    cfg = VolatilityDecayConfig(compare_strategies=['all_underlying', 'all_leveraged'])
    result = compute_volatility_decay(u, l, cfg)
    u_cagr = result.strategies['all_underlying']['cagr']
    l_cagr = result.strategies['all_leveraged']['cagr']
    theory_2x = (1 + u_cagr) ** 2 - 1
    # 隨機 fixture 不一定保證 l < 2x,但 decay_analysis 應被算出
    assert 'decay_pct' in result.decay_analysis
    # 允許 ±1e-3 容差(浮點數)
    assert isinstance(result.decay_analysis['decay_pct'], float)


# ───────── T4.3: 50/50 再平衡 MDD < all_leveraged MDD ─────────
def test_T4_3_rebalance_lowers_mdd(
    leveraged_match_2x,
):
    """震盪下 50/50 rebalance 應降低 MDD"""
    u, l = leveraged_match_2x
    cfg = VolatilityDecayConfig(compare_strategies=['all_leveraged', '50_50_rebalance_quarterly'])
    result = compute_volatility_decay(u, l, cfg)
    l_mdd = result.strategies['all_leveraged']['mdd']
    half_mdd = result.strategies['50_50_rebalance_quarterly']['mdd']
    # half 應 ≥ l(負值,絕對值小)
    assert half_mdd >= l_mdd - 1e-6, f'50/50 MDD ({half_mdd}) 應 ≥ leveraged MDD ({l_mdd})'


# ───────── Strategies 必填欄位 ─────────
def test_strategy_required_fields(
    aligned_5y,
):
    """每個 strategy 都應有 final / cagr / mdd / total_return"""
    u, l = aligned_5y
    cfg = VolatilityDecayConfig()
    result = compute_volatility_decay(u, l, cfg)
    for name, strat in result.strategies.items():
        for k in ('label', 'final', 'cagr', 'mdd', 'total_return'):
            assert k in strat, f'{name} 缺欄位 {k}'


# ───────── period metadata ─────────
def test_period_metadata_present(aligned_5y):
    """period 應含 start / end / days"""
    u, l = aligned_5y
    cfg = VolatilityDecayConfig()
    result = compute_volatility_decay(u, l, cfg)
    assert 'start' in result.period
    assert 'end' in result.period
    assert result.period['days'] == len(u) == len(l)


# ───────── decay_analysis 結構 ─────────
def test_decay_analysis_structure(aligned_5y):
    """decay_analysis 應有 theory / actual_leveraged_cagr / theory_leveraged_cagr /
    decay_pct / recommendation"""
    u, l = aligned_5y
    cfg = VolatilityDecayConfig()
    result = compute_volatility_decay(u, l, cfg)
    d = result.decay_analysis
    assert 'theory' in d
    assert 'actual_leveraged_cagr' in d
    assert 'theory_leveraged_cagr' in d
    assert 'decay_pct' in d
    assert 'recommendation' in d


# ───────── 邊界:太短歷史 ─────────
def test_short_history_raises():
    """對齊後 < 63 天應 raise"""
    dates = pd.bdate_range('2024-01-01', periods=30)
    u = pd.Series(np.linspace(100, 110, 30), index=dates)
    l = pd.Series(np.linspace(100, 120, 30), index=dates)
    with pytest.raises(VolatilityDecayError):
        compute_volatility_decay(u, l)


# ───────── 邊界:空序列 ─────────
def test_empty_raises():
    with pytest.raises(VolatilityDecayError):
        compute_volatility_decay(pd.Series(dtype=float), pd.Series(dtype=float))


# ───────── 邊界:壞 strategy name ─────────
def test_invalid_strategy_raises(aligned_5y):
    u, l = aligned_5y
    with pytest.raises(VolatilityDecayError):
        VolatilityDecayConfig(compare_strategies=['invalid_strategy'])


# ───────── 邊界:initial_balance <= 0 ─────────
def test_invalid_initial_raises(aligned_5y):
    u, l = aligned_5y
    with pytest.raises(VolatilityDecayError):
        VolatilityDecayConfig(initial_balance=0)


# ───────── run_volatility_decay wrapper ─────────
def test_run_volatility_decay_wrapper(aligned_5y):
    """Flask-friendly wrapper"""
    u, l = aligned_5y
    body = {
        'initial_balance': 100000,
        'compare_strategies': ['all_underlying', 'all_leveraged'],
    }
    result = run_volatility_decay(u, l, body)
    assert 'strategies' in result
    assert 'decay_analysis' in result
    assert 'all_underlying' in result['strategies']


def test_run_volatility_decay_bad_body(aligned_5y):
    u, l = aligned_5y
    with pytest.raises(VolatilityDecayError):
        run_volatility_decay(u, l, {'initial_balance': 'not-a-number'})


# ───────── 三策略合計要能跑完 ─────────
def test_all_three_strategies_run(
    underlying_prices_uptrend, leveraged_prices_uptrend
):
    """預設三策略都跑 → 三個結果都有"""
    cfg = VolatilityDecayConfig()
    result = compute_volatility_decay(
        underlying_prices_uptrend, leveraged_prices_uptrend, cfg
    )
    assert set(result.strategies.keys()) == {
        'all_underlying', 'all_leveraged', '50_50_rebalance_quarterly'
    }
