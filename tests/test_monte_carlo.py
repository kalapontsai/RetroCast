"""
tests/test_monte_carlo.py
- F1 驗收:T1.1/T1.2/T1.3 + 邊界 + 重現性
- 用合成日報酬(不依賴 FinMind/真實 kadela_stock)
- seed=42 + daily_drift=0.0008 校準到 ~9.7% arithmetic CAGR
  (→ log-normal 10y median 約 15.6M,落在 SPEC T1.1 的 [14M, 18M] 區間)
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.monte_carlo import (
    MonteCarloConfig, MonteCarloError, simulate_monte_carlo,
)


# ───────── 假資料產生器 ─────────
def _make_returns(
    years: int = 11,
    daily_drift: float = 0.0008,
    daily_sigma: float = 0.0126,
    seed: int = 42,
) -> pd.Series:
    """N 年合成日報酬(252 交易日/年)"""
    rng = np.random.default_rng(seed)
    n_days = years * 252
    rets = rng.normal(daily_drift, daily_sigma, n_days)
    idx = pd.bdate_range('2013-01-01', periods=n_days)
    return pd.Series(rets, index=idx)


# ───────── 結構測試 ─────────
def test_smoke_basic_structure():
    """最小 smoke:shape / 結構 / 數值合理性"""
    rets = _make_returns()
    cfg = MonteCarloConfig(initial_balance=7_236_096, horizon_years=10,
                           n_simulations=1000, seed=42)
    res = simulate_monte_carlo(rets, cfg)
    assert res.n_simulations == 1000
    assert res.horizon_years == 10
    assert len(res.yearly_stats) == 10
    assert len(res.percentile_bands) == 50   # 10 years × 5 percentiles
    # summary 必備欄位
    for k in ('median_final', 'p10_final', 'p90_final', 'mean_final',
              'prob_above_initial', 'prob_zero_or_negative',
              'survival_to_horizon'):
        assert k in res.summary
    # survival 應該是 1.0(純成長模擬,短期不會破產)
    assert res.summary['survival_to_horizon'] == 1.0
    assert res.summary['prob_zero_or_negative'] == 0.0
    # NT$ 數字四捨五入到整數
    for k in ('median_final', 'p10_final', 'p90_final', 'mean_final'):
        assert isinstance(res.summary[k], int)


# ───────── T1.1:11y 歷史, n=10000, horizon=10 → median 落在 [14M, 18M] ─────────
def test_T1_1_median_in_spec_range():
    rets = _make_returns(years=11)
    cfg = MonteCarloConfig(initial_balance=7_236_096, horizon_years=10,
                           n_simulations=10_000, seed=42)
    res = simulate_monte_carlo(rets, cfg)
    median = res.summary['median_final']
    assert 14_000_000 <= median <= 18_000_000, (
        f'T1.1 失敗:median={median:,} 不在 SPEC 規範 [14M, 18M]'
    )


# ───────── T1.2:block=False vs block=True 應不同 ─────────
def test_T1_2_block_bootstrap_differs_from_iid():
    rets = _make_returns(years=11)
    cfg_a = MonteCarloConfig(initial_balance=7_236_096, horizon_years=10,
                             n_simulations=10_000, block_bootstrap=False, seed=42)
    cfg_b = MonteCarloConfig(initial_balance=7_236_096, horizon_years=10,
                             n_simulations=10_000, block_bootstrap=True, seed=42)
    ra = simulate_monte_carlo(rets, cfg_a)
    rb = simulate_monte_carlo(rets, cfg_b)
    # 保留序列結構差異 → 至少 median_final / p10 / p90 之一應不同
    diffs = (
        ra.summary['median_final'] != rb.summary['median_final'],
        ra.summary['p10_final'] != rb.summary['p10_final'],
        ra.summary['p90_final'] != rb.summary['p90_final'],
    )
    assert any(diffs), 'block=False vs True 結果完全相同(應該至少有差異)'


# ───────── T1.3:效能 10000 sims × 50y < 60s ─────────
def test_T1_3_performance_50y_under_60s():
    """SPEC F1 acceptance:10,000 次 × 50 年 < 60s"""
    rets = _make_returns(years=11)
    cfg = MonteCarloConfig(initial_balance=7_236_096, horizon_years=50,
                           n_simulations=10_000, seed=42)
    t0 = time.perf_counter()
    res = simulate_monte_carlo(rets, cfg)
    elapsed = time.perf_counter() - t0
    assert elapsed < 60, f'10000×50y 耗時 {elapsed:.2f}s,超過 SPEC 60s 上限'
    assert res.summary['median_final'] > 0


def test_T1_3_performance_30y_under_60s():
    """股寶要求的 30y case(也應 < 60s)"""
    rets = _make_returns(years=11)
    cfg = MonteCarloConfig(initial_balance=7_236_096, horizon_years=30,
                           n_simulations=10_000, seed=42)
    t0 = time.perf_counter()
    res = simulate_monte_carlo(rets, cfg)
    elapsed = time.perf_counter() - t0
    assert elapsed < 60, f'10000×30y 耗時 {elapsed:.2f}s,超過 60s 上限'


# ───────── 重現性 ─────────
def test_reproducibility_same_seed():
    """同 seed → 完全相同結果"""
    rets = _make_returns()
    cfg = MonteCarloConfig(initial_balance=7_236_096, horizon_years=10,
                           n_simulations=10_000, seed=42)
    r1 = simulate_monte_carlo(rets, cfg)
    r2 = simulate_monte_carlo(rets, cfg)
    assert r1.summary == r2.summary
    assert r1.yearly_stats == r2.yearly_stats


def test_reproducibility_different_seed_bounded_variance():
    """不同 seed → 結果變動 < 0.5%(SPEC acceptance)"""
    rets = _make_returns()
    cfg = MonteCarloConfig(initial_balance=7_236_096, horizon_years=10,
                           n_simulations=10_000, seed=42)
    r1 = simulate_monte_carlo(rets, cfg)
    r2 = simulate_monte_carlo(rets, MonteCarloConfig(
        initial_balance=7_236_096, horizon_years=10,
        n_simulations=10_000, seed=43,
    ))
    diff_pct = abs(r1.summary['median_final'] - r2.summary['median_final']) / r1.summary['median_final']
    assert diff_pct < 0.005, f'不同 seed 變動 {diff_pct*100:.2f}% 超過 0.5% 上限'


# ───────── 邊界:initial_balance <= 0 → raise ─────────
def test_boundary_initial_zero_raises():
    rets = _make_returns()
    cfg = MonteCarloConfig(initial_balance=0, horizon_years=10)
    with pytest.raises(MonteCarloError):
        simulate_monte_carlo(rets, cfg)


def test_boundary_initial_negative_raises():
    rets = _make_returns()
    cfg = MonteCarloConfig(initial_balance=-1, horizon_years=10)
    with pytest.raises(MonteCarloError):
        simulate_monte_carlo(rets, cfg)


# ───────── 邊界:horizon_years 超出 [1, 50] ─────────
def test_boundary_horizon_too_long_raises():
    rets = _make_returns(years=11)
    cfg = MonteCarloConfig(initial_balance=1_000_000, horizon_years=51)
    with pytest.raises(MonteCarloError):
        simulate_monte_carlo(rets, cfg)


def test_boundary_horizon_zero_raises():
    rets = _make_returns()
    cfg = MonteCarloConfig(initial_balance=1_000_000, horizon_years=0)
    with pytest.raises(MonteCarloError):
        simulate_monte_carlo(rets, cfg)


# ───────── 邊界:歷史太短 → raise ─────────
def test_boundary_short_history_raises():
    short_rets = pd.Series([0.001, 0.002, 0.003])  # 只 3 天
    cfg = MonteCarloConfig(initial_balance=1_000_000, horizon_years=10)
    with pytest.raises(MonteCarloError):
        simulate_monte_carlo(short_rets, cfg)


# ───────── 邊界:n_simulations < 100 → raise ─────────
def test_boundary_too_few_sims_raises():
    rets = _make_returns()
    cfg = MonteCarloConfig(initial_balance=1_000_000, horizon_years=10,
                           n_simulations=50)
    with pytest.raises(MonteCarloError):
        simulate_monte_carlo(rets, cfg)


# ───────── 邊界:block_size_days < 1 → raise ─────────
def test_boundary_block_size_zero_raises():
    rets = _make_returns()
    cfg = MonteCarloConfig(initial_balance=1_000_000, horizon_years=10,
                           block_size_days=0)
    with pytest.raises(MonteCarloError):
        simulate_monte_carlo(rets, cfg)


# ───────── 邊界:annual_withdrawal < 0 → raise(F2 用)─────────
def test_boundary_negative_withdrawal_raises():
    rets = _make_returns()
    cfg = MonteCarloConfig(initial_balance=1_000_000, horizon_years=10,
                           annual_withdrawal=-100)
    with pytest.raises(MonteCarloError):
        simulate_monte_carlo(rets, cfg)

# ───────── 邊界:OverflowError / NaN in final_values (2026-08-27 修復) ─────────
def test_compute_summary_handles_inf_in_final_values():
    """simulate_monte_carlo 在 cumprod overflow 會產生 inf final_values;
    修復前 _compute_summary 會 OverflowError,修復後 int 統計欄位 None,
    prob 欄位包含 inf 路徑(算「未破產」,語意正確)。
    """
    from lib.monte_carlo import _compute_summary
    # 模擬 10 路徑,5 路 inf、5 路 finite
    final_values = np.array(
        [np.inf] * 5 + [1_000_000.0, 2_000_000.0, 3_000_000.0, 4_000_000.0, 5_000_000.0]
    )
    initial = 1_000_000.0
    result = _compute_summary(final_values, initial)

    # int 統計:基於有限值,中位數 = 3_000_000
    assert result['median_final'] == 3_000_000
    assert result['p10_final'] is not None
    assert result['p90_final'] is not None
    # prob 欄位:5/10 inf 路徑都算「above initial」「未破產」
    # 5 inf 都 > 1M,5 finite 中 [1M=init=False, 2M=T, 3M=T, 4M=T, 5M=T] → 4/5
    # 合計 5+4=9/10 = 0.9(注意:1M == initial 不算 strictly above)
    assert result['prob_above_initial'] == 0.9
    assert result['prob_zero_or_negative'] == 0.0
    # survival_to_horizon 看 > 0,全部 finite 跟 inf 都 > 0 → 10/10 = 1.0
    assert result['survival_to_horizon'] == 1.0


def test_compute_summary_handles_all_inf():
    """所有路徑都 overflow → int 統計全部 None,prob 全 1.0(沒破產)。"""
    from lib.monte_carlo import _compute_summary
    final_values = np.array([np.inf] * 10)
    result = _compute_summary(final_values, 1_000_000.0)

    assert result['median_final'] is None
    assert result['p10_final'] is None
    assert result['p90_final'] is None
    assert result['mean_final'] is None
    assert result['prob_above_initial'] == 1.0
    assert result['prob_zero_or_negative'] == 0.0
    assert result['survival_to_horizon'] == 1.0


def test_compute_summary_handles_nan_in_final_values():
    """NaN 路徑(罕見,可能來自 0 * inf):nan-aware stats 應略過,prob 用原始 array。"""
    from lib.monte_carlo import _compute_summary
    final_values = np.array([np.nan, 1_000_000.0, 2_000_000.0, 3_000_000.0])
    result = _compute_summary(final_values, 1_000_000.0)

    # 1 個 NaN + 3 個 finite → 中位數 2_000_000
    assert result['median_final'] == 2_000_000
    assert result['mean_final'] == 2_000_000
    # NaN > initial 是 False,1M == initial 也是 False,只有 2M/3M strictly > 1M → 2/4
    # (NaN 算「沒破產」是有爭議,但不 raise 才是重點;這裡只驗證不崩)
    assert result['prob_above_initial'] == 0.5  # 2/4 (NaN=False, 1M=init=False, 2M/3M=True)
    assert result['survival_to_horizon'] == 0.75  # NaN=False, 其餘 3 個 finite > 0 → 3/4
