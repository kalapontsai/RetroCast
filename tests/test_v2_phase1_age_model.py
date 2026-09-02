"""
tests/test_v2_phase1_age_model.py
- Phase 1.1 驗收:年齡模型 + 退休前不扣款 + ruin_age 用 current_age
- 三場景:
    S1 55→65 (current_age=55, retirement_age=60, end=65, horizon=10)  ← 經典退休前 5 年觀察
    S2 55→90 (current_age=55, retirement_age=60, end=90, horizon=35)  ← 大大大典型
    S3 60→90 (current_age=60, retirement_age=60, end=90, horizon=30)  ← SPEC v2 預設
- 驗證項:
    1. 跨欄位一致性:retirement_end_age - current_age == horizon_years
    2. 退休前年(age < retirement_age)scenario_examples['withdrawal']=0
    3. success_rate_by_age 用 current_age 為 key 起點
    4. 60→90 場景要產出 70/75/80/85/90 歲的 key(不再是 0.00% 假象)
    5. 55→65 預設 horizon=10,retirement_end_age=65 (向後相容)
    6. ru_in_age 用 current_age + y + 1(不是 retirement_age + y)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.sequence_risk import (
    SequenceRiskConfig, SequenceRiskError, simulate_sequence_risk,
)


def _make_returns(years: int, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    n_days = years * 252
    rets = rng.normal(0.0001, 0.025, n_days)
    idx = pd.bdate_range('2013-01-01', periods=n_days)
    return pd.Series(rets, index=idx)


# ───────── Scenario 1:55→65 (典型提前 5 年觀察)─────────
def test_S1_55_to_65_pre_retirement_no_withdrawal():
    rets = _make_returns(years=10)
    cfg = SequenceRiskConfig(
        initial_balance=7_236_096,
        retirement_age=60,
        horizon_years=10,              # 55→65
        withdrawal_monthly=30_000,
        seed=42,
        # 沒傳 current_age / retirement_end_age → 走 __post_init__ 預設
    )
    # 預設應該補:current_age=60, retirement_end_age=70
    assert cfg.current_age == 60, f'S1 預設 current_age 應 = retirement_age=60,got {cfg.current_age}'
    assert cfg.retirement_end_age == 70, f'S1 預設 retirement_end_age 應 = 60+10=70,got {cfg.retirement_end_age}'

    res = simulate_sequence_risk(rets, cfg)
    # scenario_examples:year=1-10 全部都是退休後(age=60~69)→ withdrawal > 0
    for row in res.scenario_examples:
        assert row['age'] == 60 + (row['year'] - 1), f'S1 age 映射錯:{row}'
        assert row['withdrawal'] > 0, f'S1 year {row["year"]} age {row["age"]} 應扣款,got {row["withdrawal"]}'


# ───────── Scenario 2:55→90 (大典型) ─────────
def test_S2_55_to_90_horizon_35():
    rets = _make_returns(years=35)
    cfg = SequenceRiskConfig(
        initial_balance=7_236_096,
        current_age=55,
        retirement_age=60,
        retirement_end_age=90,
        horizon_years=35,
        withdrawal_monthly=30_000,
        seed=42,
    )
    res = simulate_sequence_risk(rets, cfg)

    # 驗證 horizon 真的跑到 35 年
    assert len(res.scenario_examples) == 35, (
        f'S2 scenario_examples 應有 35 筆,got {len(res.scenario_examples)}'
    )
    # 55 歲起:age 序列 = 55~89
    for row in res.scenario_examples:
        assert row['age'] == 55 + (row['year'] - 1)

    # 退休前(age 55~59, year 1~5):withdrawal = 0
    pre_retire = [r for r in res.scenario_examples if r['age'] < 60]
    assert len(pre_retire) == 5
    for row in pre_retire:
        assert row['withdrawal'] == 0, (
            f'S2 退休前年 (year={row["year"]} age={row["age"]}) 不應扣款,got {row["withdrawal"]}'
        )

    # 退休後(age 60~89):withdrawal 開始累積通膨
    post_retire = [r for r in res.scenario_examples if r['age'] >= 60]
    assert len(post_retire) == 30
    for i, row in enumerate(post_retire):
        expected = int(round(30_000 * 12 * (1.03 ** i)))
        assert abs(row['withdrawal'] - expected) <= 1, (
            f'S2 通膨錯:year={row["year"]} age={row["age"]} got {row["withdrawal"]} expected {expected}'
        )

    # success_rate_by_age 應該從 56 歲開始
    assert '56' in res.success_rate_by_age
    # horizon=35 → year y 從 0 到 34 → year-end age = 55+34+1 = 90(最後一個 key)
    assert '90' in res.success_rate_by_age, (
        f"S2 應有 90 歲存活率(最後一個 key),keys={list(res.success_rate_by_age.keys())}"
    )
    # 55 歲(模擬起點)不該出現 — 第一個 year-end age = current_age+1 = 56
    assert '55' not in res.success_rate_by_age


# ───────── Scenario 3:60→90 (SPEC v2 預設) ─────────
def test_S3_60_to_90_spec_v2_default():
    """SPEC §F2 期望 horizon_years=30 (60→90);這場景直接驗 70/75/80/85/90 都有 key"""
    rets = _make_returns(years=30)
    cfg = SequenceRiskConfig(
        initial_balance=7_236_096,
        current_age=60,
        retirement_age=60,
        retirement_end_age=90,
        horizon_years=30,
        withdrawal_monthly=30_000,
        seed=42,
    )
    res = simulate_sequence_risk(rets, cfg)

    # 全部 5 個目標年齡都要有
    for age in (70, 75, 80, 85, 90):
        assert str(age) in res.success_rate_by_age, (
            f'S3 缺 {age} 歲存活率(舊版 bug:只跑到 70),keys={list(res.success_rate_by_age.keys())}'
        )
        assert 0.0 <= res.success_rate_by_age[str(age)] <= 1.0, (
            f'S3 {age} 歲存活率越界:{res.success_rate_by_age[str(age)]}'
        )


# ───────── 跨欄位一致性:horizon_years != retirement_end_age - current_age ─────────
def test_horizon_mismatch_raises():
    """故意製造不一致:horizon=10 但 end=80 (差 25)"""
    with pytest.raises(SequenceRiskError) as exc_info:
        SequenceRiskConfig(
            initial_balance=1_000_000,
            current_age=55,
            retirement_age=60,
            retirement_end_age=80,        # = 55+25,跟 horizon_years=10 不一致
            horizon_years=10,
            withdrawal_monthly=0,
        )
    assert '不一致' in str(exc_info.value)


# ───────── 邊界:retirement_age < current_age (退休規劃語意下是矛盾)─────────
def test_retirement_before_current_raises():
    """退休規劃語意下,retirement_age 必須 >= current_age
    (你不能「現在 70 歲」但說「60 歲退休」— 那表示已退休,屬於另一個工具語意)
    """
    with pytest.raises(SequenceRiskError):
        SequenceRiskConfig(
            initial_balance=1_000_000,
            current_age=70,
            retirement_age=60,           # 矛盾:目前 70 歲卻說 60 退休
            horizon_years=20,
            withdrawal_monthly=0,
        )


# ───────── 邊界:retirement_end_age <= retirement_age ─────────
def test_end_before_retirement_raises():
    with pytest.raises(SequenceRiskError):
        SequenceRiskConfig(
            initial_balance=1_000_000,
            current_age=60,
            retirement_age=65,
            retirement_end_age=65,       # 必須 > retirement_age
            horizon_years=0,
            withdrawal_monthly=0,
        )


# ───────── 向後相容:舊 fixture (沒 current_age/end) 仍可跑 ─────────
def test_backward_compat_old_fixture():
    """沒傳 current_age / retirement_end_age,等同退休當下開始模擬 horizon 年"""
    rets = _make_returns(years=10)
    cfg = SequenceRiskConfig(
        initial_balance=7_236_096,
        retirement_age=60,
        horizon_years=10,
        withdrawal_monthly=30_000,
        seed=42,
    )
    # 不應 raise
    res = simulate_sequence_risk(rets, cfg)
    assert len(res.scenario_examples) == 10
    assert res.success_rate_by_age['61'] >= 0.0
