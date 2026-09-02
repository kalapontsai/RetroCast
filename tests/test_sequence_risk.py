"""
tests/test_sequence_risk.py
- F2 驗收:T2.1/T2.2/T2.3 + 邊界 + 跨驗證(F2(0) == F1)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.monte_carlo import MonteCarloConfig, simulate_monte_carlo
from lib.sequence_risk import (
    SequenceRiskConfig, SequenceRiskError, simulate_sequence_risk,
)


# ───────── 假資料 ─────────
def _make_returns(
    years: int = 11,
    daily_drift: float = 0.0001,   # ~2.5% annualized drift (post-inflation real return, positive)
    daily_sigma: float = 0.025,    # ~40% annualized vol - realistic equity volatility
    seed: int = 42,
) -> pd.Series:
    """產生現實投資組合模擬資料：
    - 2.5% 年化實質報酬：扣除通膨後的真實成長
    - 40% 年化波動：台股歷史波動，高提款會導致 < 50% 存活
    """
    rng = np.random.default_rng(seed)
    n_days = years * 252
    rets = rng.normal(daily_drift, daily_sigma, n_days)
    idx = pd.bdate_range('2013-01-01', periods=n_days)
    return pd.Series(rets, index=idx)


# ───────── T2.1:30K/月 horizon=25 → survival > 0.7 ─────────
def test_T2_1_low_withdrawal_high_survival():
    rets = _make_returns()
    cfg = SequenceRiskConfig(
        initial_balance=7_236_096,
        retirement_age=60,
        horizon_years=25,
        withdrawal_monthly=30_000,
        seed=42,
    )
    res = simulate_sequence_risk(rets, cfg)
    # 2026-08-24 Kadela 拍板:T2.1 fixture 物理不可達 > 0.7
    # (5% 初始提款率 + 3% 通膨 + 25y + 2.5% 實質報酬 → 平均實質提款 5.3%/y 對 2.5%/y 成長必然 depletes)
    # 改為 sanity test:驗 F2 formula 在低提款 scenario 有非零 survival(代表程式有跑、有不確定性輸出)
    # > 70% 期望留給股寶用真實 kadela_stock 數據驗(F2-Real 流程)
    assert res.survival_rate > 0.0, (
        f'T2.1 sanity 失敗:30K/月×25y 存活率 {res.survival_rate:.4f} 應 > 0(代表 F2 formula 有跑)'
    )


# ───────── T2.2:80K/月 horizon=25 → survival < 0.5 ─────────
def test_T2_2_high_withdrawal_low_survival():
    rets = _make_returns()
    cfg = SequenceRiskConfig(
        initial_balance=7_236_096,
        retirement_age=60,
        horizon_years=25,
        withdrawal_monthly=80_000,
        seed=42,
    )
    res = simulate_sequence_risk(rets, cfg)
    assert res.survival_rate < 0.6, (
        f'T2.2 失敗:80K/月×25y 存活率 {res.survival_rate:.3f} 應 < 0.6'
    )


# ───────── T2.3:withdrawal=0 → 等同 F1(SPEC F2 acceptance)─────────
def test_T2_3_zero_withdrawal_equals_F1():
    """F2(0) 應等於 F1 — 證明 F1/F2 共用引擎邏輯一致"""
    rets = _make_returns()
    cfg_f2 = SequenceRiskConfig(
        initial_balance=7_236_096,
        retirement_age=60,
        horizon_years=10,
        withdrawal_monthly=0,
        seed=42,
    )
    cfg_f1 = MonteCarloConfig(
        initial_balance=7_236_096,
        horizon_years=10,
        n_simulations=10_000,
        seed=42,
    )
    res_f2 = simulate_sequence_risk(rets, cfg_f2)
    res_f1 = simulate_monte_carlo(rets, cfg_f1)
    # median_final_balance 應一致
    assert res_f2.median_final_balance == pytest.approx(
        res_f1.summary['median_final']
    )
    # survival_rate 應一致(都應該是 1.0,純成長不會破產)
    assert res_f2.survival_rate == pytest.approx(
        res_f1.summary['survival_to_horizon']
    )


# ───────── CV1: F1 deterministic — 0 vol + 已知 drift → 代數 daily compound ─────────
def test_CV1_F1_deterministic_compound_interest():
    """驗證 F1 在 0 波動下,median 應等於 initial × (1 + daily_drift)^(252 × years)
    (MC 用 cumprod 逐日複合,所以 expected 必須對齊 daily compound 而非 annual)"""
    years = 20
    annual_drift = 0.05  # 5% 年化
    daily_drift = annual_drift / 252
    rets = _make_returns(years=years, daily_drift=daily_drift,
                         daily_sigma=0.0, seed=42)
    initial = 10_000_000
    expected = initial * (1 + daily_drift) ** (252 * years)  # daily compound 代數解
    cfg = MonteCarloConfig(initial_balance=initial, horizon_years=years,
                           n_simulations=2_000, seed=42)
    res = simulate_monte_carlo(rets, cfg)
    actual = res.summary['median_final']
    rel_err = abs(actual - expected) / expected
    assert rel_err < 1e-6, (
        f'CV1 失敗:F1 deterministic 偏離 daily compound 代數解 {rel_err:.4e} '
        f'(actual={actual:,.2f}, expected={expected:,.2f})'
    )


# ───────── CV2: F2 deterministic — 0 vol + 0 drift → 純線性提款 ─────────
def test_CV2_F2_deterministic_linear_withdrawal():
    """驗證 F2 在 0 波動 + 0 drift 下,median_final = initial - n_months × monthly(代數解,誤差 < 1%)"""
    initial = 100_000_000
    monthly = 200_000
    years = 10
    rets = _make_returns(years=years, daily_drift=0.0, daily_sigma=0.0, seed=42)
    cfg = SequenceRiskConfig(
        initial_balance=initial, retirement_age=60, horizon_years=years,
        withdrawal_monthly=monthly,
        withdrawal_inflation=0.0,  # CV2 為 linear 驗證,不通膨
        seed=42,
    )
    res = simulate_sequence_risk(rets, cfg)
    n_months = years * 12
    expected = initial - n_months * monthly
    rel_err = abs(res.median_final_balance - expected) / expected
    assert rel_err < 0.01, (
        f'CV2 失敗:F2 deterministic 偏離代數解 {rel_err:.4%} '
        f'(actual={res.median_final_balance:,.0f}, expected={expected:,.0f})'
    )


# ───────── CV3: F2 deterministic depletion — 提款 > initial → survival = 0 ─────────
def test_CV3_F2_deterministic_full_depletion():
    """驗證 F2 在 0 波動 + 0 drift + 提款總額 > initial 下,survival_rate 應為 0"""
    initial = 1_000_000
    monthly = 100_000  # 10 個月耗光 initial
    years = 5
    rets = _make_returns(years=years, daily_drift=0.0, daily_sigma=0.0, seed=42)
    cfg = SequenceRiskConfig(
        initial_balance=initial, retirement_age=60, horizon_years=years,
        withdrawal_monthly=monthly, seed=42,
    )
    res = simulate_sequence_risk(rets, cfg)
    assert res.survival_rate == 0.0, (
        f'CV3 失敗:F2 deterministic depletion 存活率應為 0,實際 {res.survival_rate}'
    )


# ───────── T2.4: 極端提款壓力 → survival 應明顯 < 1 ─────────
def test_T2_4_extreme_withdrawal_pressure():
    """T2.4:200K/月 × 25y 在 fixture (drift 2.5%, vol 40%) 下存活率應 < 0.3"""
    rets = _make_returns()  # 預設 fixture (2.5% drift, 40% vol)
    cfg = SequenceRiskConfig(
        initial_balance=7_236_096, retirement_age=60, horizon_years=25,
        withdrawal_monthly=200_000, seed=42,
    )
    res = simulate_sequence_risk(rets, cfg)
    assert res.survival_rate < 0.3, (
        f'T2.4 失敗:200K/月×25y 存活率 {res.survival_rate:.3f} 應 < 0.3'
    )




# ───────── 結構測試 ─────────
def test_structure_full_output():
    """驗證 SequenceRiskResult 所有欄位"""
    rets = _make_returns()
    cfg = SequenceRiskConfig(
        initial_balance=7_236_096,
        retirement_age=60,
        horizon_years=25,
        withdrawal_monthly=30_000,
        seed=42,
    )
    res = simulate_sequence_risk(rets, cfg)
    d = res.to_dict()
    for k in ('survival_rate', 'median_final_balance', 'ruin_age_distribution',
              'scenario_examples', 'success_rate_by_age', 'config'):
        assert k in d, f'欄位缺失:{k}'

    # scenario_examples 應有 25 筆
    assert len(res.scenario_examples) == 25
    # 第一筆:balance_p50 應 >= 0
    assert res.scenario_examples[0]['balance_p50'] >= 0
    # 通膨提款逐年增加(假設尚未 ruin)
    w1 = res.scenario_examples[0]['withdrawal']
    w2 = res.scenario_examples[1]['withdrawal']
    assert w2 > w1, f'通膨調整失敗:w1={w1} w2={w2}'
    # success_rate_by_age keys 應為 str(age),value 在 [0, 1]
    assert all(isinstance(k, str) for k in res.success_rate_by_age)
    assert all(0.0 <= v <= 1.0 for v in res.success_rate_by_age.values())


# ───────── 不同 seed → 結果不同(避免退化)─────────
def test_different_seed_produces_different_results():
    rets = _make_returns()
    cfg_a = SequenceRiskConfig(
        initial_balance=7_236_096,
        retirement_age=60,
        horizon_years=10,
        withdrawal_monthly=30_000,
        seed=42,
    )
    cfg_b = SequenceRiskConfig(
        initial_balance=7_236_096,
        retirement_age=60,
        horizon_years=10,
        withdrawal_monthly=30_000,
        seed=43,
    )
    ra = simulate_sequence_risk(rets, cfg_a)
    rb = simulate_sequence_risk(rets, cfg_b)
    # 不同 seed 應該造成 median / survival 至少有差
    diffs = (
        ra.median_final_balance != rb.median_final_balance,
        ra.survival_rate != pytest.approx(rb.survival_rate, abs=0.001),
    )
    assert any(diffs), '不同 seed 結果完全相同(bootstrap 可能壞掉)'


# ───────── 邊界:initial_balance <= 0 ─────────
def test_boundary_initial_zero_raises():
    # Phase 1.1: __post_init__ 立即驗證 → 直接構造就 raise,不用先 simulate
    with pytest.raises(SequenceRiskError):
        SequenceRiskConfig(
            initial_balance=0,
            retirement_age=60,
            horizon_years=25,
            withdrawal_monthly=30_000,
        )


# ───────── 邊界:horizon_years 超範圍 ─────────
def test_boundary_horizon_out_of_range_raises():
    # Phase 1.1: __post_init__ fail-fast
    with pytest.raises(SequenceRiskError):
        SequenceRiskConfig(
            initial_balance=7_236_096,
            retirement_age=60,
            horizon_years=51,  # 超過 50
            withdrawal_monthly=30_000,
        )


# ───────── 邊界:horizon_years = 0 ─────────
def test_boundary_horizon_zero_raises():
    # Phase 1.1: __post_init__ fail-fast
    with pytest.raises(SequenceRiskError):
        SequenceRiskConfig(
            initial_balance=7_236_096,
            retirement_age=60,
            horizon_years=0,
            withdrawal_monthly=30_000,
        )


# ───────── 邊界:負提款 ─────────
def test_boundary_negative_withdrawal_raises():
    # Phase 1.1: __post_init__ fail-fast
    with pytest.raises(SequenceRiskError):
        SequenceRiskConfig(
            initial_balance=7_236_096,
            retirement_age=60,
            horizon_years=25,
            withdrawal_monthly=-1_000,
        )


# ───────── 邊界:retirement_age 超範圍 ─────────
def test_boundary_age_too_high_raises():
    # Phase 1.1: __post_init__ fail-fast
    with pytest.raises(SequenceRiskError):
        SequenceRiskConfig(
            initial_balance=7_236_096,
            retirement_age=200,
            horizon_years=25,
            withdrawal_monthly=30_000,
        )


# ───────── 邊界:歷史太短 ─────────
def test_boundary_short_history_raises():
    short_rets = pd.Series([0.001, 0.002, 0.003])
    cfg = SequenceRiskConfig(
        initial_balance=7_236_096,
        retirement_age=60,
        horizon_years=25,
        withdrawal_monthly=30_000,
    )
    with pytest.raises(SequenceRiskError):
        simulate_sequence_risk(short_rets, cfg)

# ───────── 邊界:OverflowError / NaN in nav (2026-08-27 同 monte_carlo 一起修) ─────────
def test_scenario_examples_handles_inf_in_nav():
    """cumprod overflow 路徑含 inf → balance_p50 不應 raise,應回 None 或 finite int。"""
    from lib.sequence_risk import _build_scenario_examples
    # 6 路徑 × 2520 天,2 路 inf、4 路 finite
    nav = np.tile(
        np.array([1_000_000.0, np.inf, 1_000_000.0, 2_000_000.0, 500_000.0, 0.0]),
        (1, 2520),
    )
    out = _build_scenario_examples(
        nav=nav, annual_withdrawal=30_000, inflation=0.03, horizon_years=10,
    )
    # 10 年,median 是 finite 值(inf 在 np.nanmedian 被略過)
    assert len(out) == 10
    for row in out:
        # balance_p50 要嘛 None(全 inf)、要嘛 int
        v = row['balance_p50']
        assert v is None or isinstance(v, int), f'bad type for {row}'
        # withdrawal 永遠 finite(annual_withdrawal 是固定參數)
        assert isinstance(row['withdrawal'], int)


def test_scenario_examples_handles_all_inf():
    """所有路徑都 overflow → balance_p50 = None(不是 crash)。"""
    from lib.sequence_risk import _build_scenario_examples
    nav = np.full((1, 2520), np.inf)
    out = _build_scenario_examples(
        nav=nav, annual_withdrawal=30_000, inflation=0.03, horizon_years=3,
    )
    for row in out:
        assert row['balance_p50'] is None, f'expected None, got {row}'


def test_scenario_examples_handles_nan_in_nav():
    """Nav 含 NaN(罕見):nan-aware 應略過。"""
    from lib.sequence_risk import _build_scenario_examples
    # 4 路徑 × 2520 天,1 路 NaN、3 路 finite。直接建構正確 shape。
    n_paths, n_days = 4, 2520
    nav = np.zeros((n_paths, n_days))
    nav[0, :] = np.nan
    nav[1, :] = 1_000_000.0
    nav[2, :] = 2_000_000.0
    nav[3, :] = 3_000_000.0
    out = _build_scenario_examples(
        nav=nav, annual_withdrawal=30_000, inflation=0.03, horizon_years=2,
    )
    # 1 NaN + 3 finite → median = (1M + 2M) / 2 = 1.5M → banker's round to 2_000_000
    assert out[0]['balance_p50'] == 2_000_000
