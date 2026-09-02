"""
tests/test_v2_phase2_pension_and_special.py
- Phase 2C/2D 驗收:pension(年金)注入 + special_expenses(一次性大額支出)
- 驗證項:
    1. pension_monthly > 0 → 存活率提升(因為有注入現金流)
    2. special_expense 該年 → 餘額明顯下降(快速走向 ruin)
    3. pension_start_age < retirement_age → 提前領年金也支援
    4. 兩者同時存在 → 效果可疊加
    5. 邊界值:pension=0 / expense=[] 維持 backward-compat
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


def _make_returns(years: int = 35, daily_drift: float = 0.0003, daily_sigma: float = 0.012, seed: int = 42):
    rng = np.random.default_rng(seed)
    rets = rng.normal(daily_drift, daily_sigma, years * 252)
    idx = pd.bdate_range('1990-01-01', periods=years * 252)
    return pd.Series(rets, index=idx)


# ─────── 1. pension 提高存活率 ───────
def test_pension_increases_survival():
    rets = _make_returns()
    base_cfg = SequenceRiskConfig(
        initial_balance=5_000_000,
        retirement_age=60,
        horizon_years=30,
        withdrawal_monthly=35_000,    # 較高提款壓力
    )
    base_result = simulate_sequence_risk(rets, base_cfg)

    pension_cfg = SequenceRiskConfig(
        initial_balance=5_000_000,
        retirement_age=60,
        horizon_years=30,
        withdrawal_monthly=35_000,
        pension_monthly=20_000,        # 領勞保年金
        pension_inflation=0.02,
    )
    pension_result = simulate_sequence_risk(rets, pension_cfg)

    assert pension_result.survival_rate >= base_result.survival_rate, (
        f'pension 應提高存活率,但 {pension_result.survival_rate:.2%} < {base_result.survival_rate:.2%}'
    )
    # 預期 pension 結果的中位終值應該 >= base
    assert pension_result.median_final_balance >= base_result.median_final_balance, (
        f'pension 結果中位終值應 >= base,got {pension_result.median_final_balance} vs {base_result.median_final_balance}'
    )


# ─────── 2. special_expense 縮短存活 ───────
def test_special_expense_reduces_survival():
    rets = _make_returns()
    base_cfg = SequenceRiskConfig(
        initial_balance=5_000_000,
        retirement_age=60,
        horizon_years=30,
        withdrawal_monthly=20_000,
    )
    base_result = simulate_sequence_risk(rets, base_cfg)

    expense_cfg = SequenceRiskConfig(
        initial_balance=5_000_000,
        retirement_age=60,
        horizon_years=30,
        withdrawal_monthly=20_000,
        special_expenses=[
            {'year_offset': 10, 'amount': 5_000_000, 'label': '房屋裝修'},  # 65 歲時大額支出
        ],
    )
    expense_result = simulate_sequence_risk(rets, expense_cfg)

    # 中位終值會被特殊支出拉低
    assert expense_result.median_final_balance < base_result.median_final_balance, (
        f'5M 一次性支出應拉低中位終值,got {expense_result.median_final_balance} vs base {base_result.median_final_balance}'
    )


# ─────── 3. pension_start_age 提前 ───────
def test_pension_start_age_custom():
    """pension_start_age < retirement_age: 提前領(例如 55 歲提早退休年金)
       仍應能正常運作,不會 crash
    """
    rets = _make_returns()
    cfg = SequenceRiskConfig(
        initial_balance=3_000_000,
        retirement_age=60,
        horizon_years=30,
        withdrawal_monthly=25_000,
        pension_monthly=15_000,
        pension_start_age=55,           # 比退休年齡早 5 年
        pension_inflation=0.02,
    )
    result = simulate_sequence_risk(rets, cfg)
    assert isinstance(result.survival_rate, float)
    assert 0.0 <= result.survival_rate <= 1.0


# ─────── 4. pension + special_expenses 疊加 ───────
def test_pension_and_special_expenses_combine():
    """同時有 pension(正向現金流)和 special_expenses(負向現金流),
       兩者都應生效 — 結果應介於單獨 pension 跟單獨 expense 之間
    """
    rets = _make_returns()
    pension_only = simulate_sequence_risk(rets, SequenceRiskConfig(
        initial_balance=5_000_000, retirement_age=60, horizon_years=30,
        withdrawal_monthly=25_000,
        pension_monthly=15_000,
    ))
    expense_only = simulate_sequence_risk(rets, SequenceRiskConfig(
        initial_balance=5_000_000, retirement_age=60, horizon_years=30,
        withdrawal_monthly=25_000,
        special_expenses=[{'year_offset': 10, 'amount': 2_000_000}],
    ))
    both = simulate_sequence_risk(rets, SequenceRiskConfig(
        initial_balance=5_000_000, retirement_age=60, horizon_years=30,
        withdrawal_monthly=25_000,
        pension_monthly=15_000,
        special_expenses=[{'year_offset': 10, 'amount': 2_000_000}],
    ))
    # both.median_final_balance 應介於 expense_only 跟 pension_only 之間(?)
    # 嚴格說不能這樣保證,但應該 > expense_only(因為 pension 補回一些)
    assert both.median_final_balance > expense_only.median_final_balance, (
        f'both 應比單獨 expense 好,got {both.median_final_balance} vs {expense_only.median_final_balance}'
    )


# ─────── 5. backward-compat: pension=0 / expense=[] ───────
def test_default_pension_and_expense_match_legacy():
    """預設 pension=0 / expense=[] 應跟 Phase 1 行為完全一致

    注意:seed=None 走 np.random.default_rng(None) 每次不同,
    所以本測試必須明確固定 seed 才能比對。
    """
    rets = _make_returns()
    base = simulate_sequence_risk(rets, SequenceRiskConfig(
        initial_balance=5_000_000, retirement_age=60, horizon_years=30,
        withdrawal_monthly=25_000, seed=42,
    ))
    explicit = simulate_sequence_risk(rets, SequenceRiskConfig(
        initial_balance=5_000_000, retirement_age=60, horizon_years=30,
        withdrawal_monthly=25_000, seed=42,
        pension_monthly=0.0,
        pension_inflation=0.02,
        pension_start_age=60,
        special_expenses=[],
    ))
    # 同 seed 下結果必須一致
    assert base.survival_rate == explicit.survival_rate
    assert base.median_final_balance == explicit.median_final_balance
    assert base.success_rate_by_age == explicit.success_rate_by_age
