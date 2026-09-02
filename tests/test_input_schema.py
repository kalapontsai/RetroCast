"""tests/test_input_schema.py
- Phase 4.2 驗收:lib/input_schema.py 模組功能
- 涵蓋:
    1. SpecialExpense / RetirementInputs / DerivedRetirement dataclass
    2. derived() 計算正確
    3. parse_retirement_inputs 預設值
    4. parse_retirement_inputs 邊界(年齡上下限、提款負數、退休年齡<現在年齡等)
    5. InputSchemaError 錯誤訊息
    6. special_expenses 各類型驗證
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.input_schema import (
    DerivedRetirement, InputSchemaError, RetirementInputs,
    SpecialExpense, parse_retirement_inputs,
)


# ─────── 1. SpecialExpense / RetirementInputs / DerivedRetirement ───────
def test_special_expense_default_label():
    s = SpecialExpense(year_offset=5, amount=100_000)
    assert s.year_offset == 5
    assert s.amount == 100_000
    assert s.label == ''


def test_special_expense_with_label():
    s = SpecialExpense(year_offset=10, amount=5_000_000, label='房屋裝修')
    assert s.label == '房屋裝修'


def test_retirement_inputs_default():
    ri = RetirementInputs(current_age=55, retirement_age=65, retirement_end_age=90)
    assert ri.forecast_years == 10  # default
    assert ri.withdrawal_monthly == 0.0
    assert ri.withdrawal_inflation == 0.03
    assert ri.pension_monthly == 0.0
    assert ri.special_expenses == []


def test_derived_calculations():
    ri = RetirementInputs(current_age=55, retirement_age=65, retirement_end_age=90)
    d = ri.derived()
    assert d.years_to_retirement == 10
    assert d.retirement_years == 25
    assert d.forecast_end_age == 65
    assert d.retirement_horizon == 35


def test_derived_60_to_90():
    ri = RetirementInputs(current_age=60, retirement_age=60, retirement_end_age=90)
    d = ri.derived()
    assert d.years_to_retirement == 0
    assert d.retirement_years == 30
    assert d.retirement_horizon == 30


# ─────── 2. parse_retirement_inputs 預設值 ───────
def test_parse_empty_body_uses_defaults():
    ri = parse_retirement_inputs({})
    assert ri.current_age == 55
    assert ri.retirement_age == 65
    assert ri.retirement_end_age == 90
    assert ri.forecast_years == 10


def test_parse_none_body_uses_defaults():
    ri = parse_retirement_inputs(None)
    assert ri.current_age == 55


# ─────── 3. parse_retirement_inputs 邊界錯誤 ───────
def test_parse_invalid_body_type():
    with pytest.raises(InputSchemaError, match='應為 dict'):
        parse_retirement_inputs('not a dict')


def test_parse_current_age_too_young():
    with pytest.raises(InputSchemaError, match='current_age 應在'):
        parse_retirement_inputs({'current_age': 0})


def test_parse_current_age_too_old():
    with pytest.raises(InputSchemaError, match='current_age 應在'):
        parse_retirement_inputs({'current_age': 121})


def test_parse_retirement_age_before_current_age():
    """retirement_age 必須 >= current_age"""
    with pytest.raises(InputSchemaError, match='retirement_age 應在'):
        parse_retirement_inputs({'current_age': 70, 'retirement_age': 60})


def test_parse_retirement_end_age_equal_retirement_age():
    """retirement_end_age 必須 > retirement_age"""
    with pytest.raises(InputSchemaError, match='retirement_end_age 應在'):
        parse_retirement_inputs({
            'current_age': 55, 'retirement_age': 65, 'retirement_end_age': 65,
        })


def test_parse_withdrawal_negative():
    with pytest.raises(InputSchemaError, match='withdrawal_monthly 應'):
        parse_retirement_inputs({'withdrawal_monthly': -1})


def test_parse_withdrawal_inflation_negative():
    with pytest.raises(InputSchemaError, match='withdrawal_inflation 應'):
        parse_retirement_inputs({'withdrawal_inflation': -0.01})


def test_parse_forecast_years_zero():
    with pytest.raises(InputSchemaError, match='forecast_years 應在'):
        parse_retirement_inputs({'forecast_years': 0})


def test_parse_forecast_years_too_large():
    with pytest.raises(InputSchemaError, match='forecast_years 應在'):
        parse_retirement_inputs({'forecast_years': 100})


def test_parse_non_dict_special_expenses():
    with pytest.raises(InputSchemaError, match='special_expenses 應為'):
        parse_retirement_inputs({'special_expenses': 'not a list'})


def test_parse_special_expense_missing_field():
    with pytest.raises(InputSchemaError, match='需含 year_offset'):
        parse_retirement_inputs({'special_expenses': [{'amount': 100}]})


def test_parse_special_expense_negative_amount():
    with pytest.raises(InputSchemaError, match='amount 應'):
        parse_retirement_inputs({'special_expenses': [{'year_offset': 5, 'amount': -1}]})


def test_parse_age_non_numeric():
    with pytest.raises(InputSchemaError, match='必須是數字'):
        parse_retirement_inputs({'current_age': 'fifty'})


# ─────── 4. parse_retirement_inputs happy path ───────
def test_parse_55_to_65_short_horizon():
    ri = parse_retirement_inputs({
        'current_age': 55,
        'retirement_age': 55,
        'retirement_end_age': 65,
    })
    d = ri.derived()
    assert d.retirement_horizon == 10
    assert d.years_to_retirement == 0


def test_parse_55_to_90_long_horizon():
    ri = parse_retirement_inputs({
        'current_age': 55,
        'retirement_age': 65,
        'retirement_end_age': 90,
    })
    d = ri.derived()
    assert d.retirement_horizon == 35


def test_parse_60_to_90_default_horizon():
    ri = parse_retirement_inputs({
        'current_age': 60,
        'retirement_age': 60,
        'retirement_end_age': 90,
    })
    d = ri.derived()
    assert d.retirement_horizon == 30


def test_parse_with_special_expenses():
    ri = parse_retirement_inputs({
        'current_age': 60, 'retirement_age': 60, 'retirement_end_age': 90,
        'special_expenses': [
            {'year_offset': 10, 'amount': 5_000_000, 'label': '房屋裝修'},
            {'year_offset': 20, 'amount': 2_000_000},
        ],
    })
    assert len(ri.special_expenses) == 2
    assert ri.special_expenses[0].label == '房屋裝修'
    assert ri.special_expenses[1].label == ''


def test_parse_with_all_fees():
    ri = parse_retirement_inputs({
        'current_age': 60, 'retirement_age': 60, 'retirement_end_age': 90,
        'fee_buy': 0.001425, 'fee_sell': 0.001425,
        'tax_sell': 0.003, 'slippage': 0.001,
    })
    assert ri.fee_buy == 0.001425
    assert ri.fee_sell == 0.001425
    assert ri.tax_sell == 0.003
    assert ri.slippage == 0.001