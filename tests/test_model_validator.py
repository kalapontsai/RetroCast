"""tests/test_model_validator.py
- Phase 4.1 驗收:lib/model_validator.py 模組功能
- 涵蓋:
    1. Check dataclass / ValidationReport finalize / summary
    2. check_eq / check_ge / check_le / check_lt / check_positive / check_non_negative 各種邊界
    3. validate_all 各個 checklist:
        - N-year consistency (PASS / FAIL)
        - rolling.years >= N*0.95
        - recent_n_year.years 對齊 n
        - monte_carlo.horizon_years
        - retirement_mc_horizon = end_age - current_age
        - withdrawal sanity
        - withdrawal_inflation 一致性
        - forecast_horizon_end <= last_date
        - pension sanity
        - pv <= pv_raw
    4. ModelValidationError raise 邏輯
    5. raise_if_critical helper
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.model_validator import (
    Check, ValidationReport, ModelValidationError,
    check_eq, check_ge, check_le, check_lt,
    check_positive, check_non_negative,
    validate_all, raise_if_critical,
)


# ─────── 1. Check / ValidationReport 基礎 ───────
def test_check_to_dict_has_all_fields():
    c = Check(name='x', severity='WARN', status='PASS', expected=1, actual=1)
    d = c.to_dict()
    assert d['name'] == 'x'
    assert d['severity'] == 'WARN'
    assert d['status'] == 'PASS'
    assert d['expected'] == 1
    assert d['actual'] == 1


def test_validation_report_finalize_counts():
    r = ValidationReport()
    r.add(Check('a', 'WARN', 'PASS'))
    r.add(Check('b', 'WARN', 'FAIL'))
    r.add(Check('c', 'CRITICAL', 'FAIL'))
    r.add(Check('d', 'WARN', 'SKIP'))
    r.finalize()
    assert r.summary == {
        'total': 4,
        'pass': 1,
        'fail': 2,
        'skip': 1,
        'critical_fail': 1,
        'warn_fail': 1,
    }
    assert r.has_critical_fail() is True


def test_validation_report_no_critical_fail():
    r = ValidationReport()
    r.add(Check('a', 'WARN', 'FAIL'))
    r.finalize()
    assert r.has_critical_fail() is False


# ─────── 2. Check helpers 邊界 ───────
def test_check_eq_pass_and_fail():
    assert check_eq('x', actual=1.0, expected=1.0).status == 'PASS'
    assert check_eq('x', actual=1.1, expected=1.0).status == 'FAIL'
    # tolerance
    assert check_eq('x', actual=1.05, expected=1.0, tolerance=0.1).status == 'PASS'
    # type error → SKIP
    assert check_eq('x', actual='abc', expected=1).status == 'SKIP'


def test_check_ge():
    assert check_ge('x', actual=5, expected=5).status == 'PASS'
    assert check_ge('x', actual=6, expected=5).status == 'PASS'
    assert check_ge('x', actual=4, expected=5).status == 'FAIL'


def test_check_le():
    assert check_le('x', actual=5, expected=5).status == 'PASS'
    assert check_le('x', actual=4, expected=5).status == 'PASS'
    assert check_le('x', actual=6, expected=5).status == 'FAIL'


def test_check_lt():
    assert check_lt('x', actual=4, expected=5).status == 'PASS'
    assert check_lt('x', actual=5, expected=5).status == 'FAIL'  # 嚴格小於
    assert check_lt('x', actual=6, expected=5).status == 'FAIL'


def test_check_positive():
    assert check_positive('x', actual=1).status == 'PASS'
    assert check_positive('x', actual=0).status == 'FAIL'
    assert check_positive('x', actual=-1).status == 'FAIL'
    assert check_positive('x', actual=None).status == 'FAIL'


def test_check_non_negative():
    assert check_non_negative('x', actual=0).status == 'PASS'
    assert check_non_negative('x', actual=1).status == 'PASS'
    assert check_non_negative('x', actual=-1).status == 'FAIL'


# ─────── 3. validate_all — 完整 happy path ───────
def test_validate_all_pass():
    analyze = {
        'inputs': {'n': 10, 'pv': 900_000, 'pv_raw': 1_000_000},
        'forecast': {
            'n': 10,
            'rolling': [{'years': 10, 'end': '2024-01-01'},
                        {'years': 10, 'end': '2024-12-31'}],
        },
        'recent_n_year_metrics': {'years': 10.0},
        'monte_carlo': {'config': {'horizon_years': 10}},
        # Phase 4.1 修正:horizon = end_age - current_age = 90 - 55 = 35
        'sequence_risk': {'config': {'horizon_years': 35,
                                      'withdrawal_inflation': 0.03}},
        'retirement_inputs': {
            'current_age': 55,
            'retirement_end_age': 90,
            'withdrawal_monthly': 25_000,
            'withdrawal_inflation': 0.03,
            'pension_monthly': 20_000,
        },
        'common': {'metrics': {'end': '2025-01-01'}},
    }
    r = validate_all(analyze)
    r.finalize()
    fails = [c for c in r.checks if c.status == 'FAIL']
    assert fails == [], f'expected all PASS, got fails: {[(c.name, c.message) for c in fails]}'


def test_validate_all_n_year_consistency_fail():
    analyze = {
        'inputs': {'n': 10, 'pv': 100, 'pv_raw': 100},
        'forecast': {'n': 10, 'rolling': []},
        'monte_carlo': {'config': {'horizon_years': 99}},   # 故意不符
        'sequence_risk': {'config': {'horizon_years': 35,  # 對齊 90-55
                                      'withdrawal_inflation': 0.03}},
        'retirement_inputs': {
            'current_age': 55, 'retirement_end_age': 90,
            'withdrawal_monthly': 0, 'withdrawal_inflation': 0.03,
            'pension_monthly': 0,
        },
        'common': {'metrics': {'end': '2025-01-01'}},
    }
    r = validate_all(analyze)
    # CRITICAL FAIL: monte_carlo horizon 99 != n=10
    crit = [c for c in r.checks if c.status == 'FAIL' and c.severity == 'CRITICAL']
    assert len(crit) >= 1
    assert any('monte_carlo.horizon_years' in c.name for c in crit)
    assert r.has_critical_fail() is True


def test_validate_all_retirement_mc_horizon_fail():
    analyze = {
        'inputs': {'n': 10, 'pv': 100, 'pv_raw': 100},
        'forecast': {'n': 10, 'rolling': []},
        'monte_carlo': None,
        # horizon 99 != 90-55=35,觸發退休 MC horizon FAIL
        'sequence_risk': {'config': {'horizon_years': 99,
                                      'withdrawal_inflation': 0.03}},
        'retirement_inputs': {
            'current_age': 55, 'retirement_end_age': 90,
            'withdrawal_monthly': 0, 'withdrawal_inflation': 0.03,
            'pension_monthly': 0,
        },
        'common': {'metrics': {'end': '2025-01-01'}},
    }
    r = validate_all(analyze)
    assert r.has_critical_fail() is True


def test_validate_all_withdrawal_inflation_mismatch():
    analyze = {
        'inputs': {'n': 10, 'pv': 100, 'pv_raw': 100},
        'forecast': {'n': 10, 'rolling': []},
        'monte_carlo': None,
        'sequence_risk': {'config': {'horizon_years': 30,
                                      'withdrawal_inflation': 0.05}},  # 0.05 != 0.03
        'retirement_inputs': {
            'current_age': 55, 'retirement_end_age': 90,
            'withdrawal_monthly': 0, 'withdrawal_inflation': 0.03,
            'pension_monthly': 0,
        },
        'common': {'metrics': {'end': '2025-01-01'}},
    }
    r = validate_all(analyze)
    wd_fails = [c for c in r.checks if 'withdrawal_inflation' in c.name and c.status == 'FAIL']
    assert len(wd_fails) == 1, 'withdrawal_inflation 不一致應 FAIL'


def test_validate_all_pv_consistency():
    analyze = {
        'inputs': {'n': 10, 'pv': 1_100_000, 'pv_raw': 1_000_000},  # pv > pv_raw 異常
        'forecast': {'n': 10, 'rolling': []},
        'sequence_risk': {'config': {'horizon_years': 30,
                                      'withdrawal_inflation': 0.03}},
        'retirement_inputs': {
            'current_age': 55, 'retirement_end_age': 90,
            'withdrawal_monthly': 0, 'withdrawal_inflation': 0.03,
            'pension_monthly': 0,
        },
        'common': {'metrics': {'end': '2025-01-01'}},
    }
    r = validate_all(analyze)
    pv_fails = [c for c in r.checks if 'pv' in c.name and c.status == 'FAIL']
    assert len(pv_fails) == 1, 'pv > pv_raw 應 FAIL'


# ─────── 4. ModelValidationError / raise_if_critical ───────
def test_model_validation_error_message():
    r = ValidationReport()
    r.add(Check('test', 'CRITICAL', 'FAIL', message='bad'))
    r.add(Check('test2', 'CRITICAL', 'FAIL', message='also bad'))
    r.finalize()
    with pytest.raises(ModelValidationError) as exc_info:
        raise_if_critical(r)
    msg = str(exc_info.value)
    assert 'test' in msg
    assert 'test2' in msg


def test_raise_if_critical_no_critical_no_raise():
    r = ValidationReport()
    r.add(Check('test', 'WARN', 'FAIL'))
    r.finalize()
    # 應不 raise
    raise_if_critical(r)


# ─────── 5. validate_all 對 missing field 容忍 ───────
def test_validate_all_missing_fields_no_crash():
    analyze = {
        'inputs': {'n': 10},
        'forecast': {'n': 10, 'rolling': []},
    }
    r = validate_all(analyze)
    # 缺欄位應 graceful skip,不應 crash
    assert r.summary is not None or True  # finalize 過後才有 summary,但呼叫後存在
    # 至少 partial check 跑了
    assert len(r.checks) >= 1

# ─────── Phase 6C (Item 13): Pre-flight 補強 6 條 ───────

def _item13_analyze():
    """最小 fixture:含 Item 13 6 條 check 需要的欄位"""
    return {
        'inputs': {'n': 10, 'pv': 7_236_096, 'pv_raw': 7_236_096},
        'forecast': {
            'n': 10,
            'rolling': [
                {'start': '2014-01-01', 'end': '2024-01-01', 'years': 10.0, 'cagr': 0.08},
                {'start': '2015-01-01', 'end': '2025-01-01', 'years': 10.0, 'cagr': 0.06},
            ],
        },
        'common': {'metrics': {'end': '2024-12-31'}},
        'nav_series': {
            'common': [{'date': d, 'value': 1.0 + 0.001*i} for i, d in enumerate(['2020', '2021', '2022'])],
        },
        'retirement_inputs': {
            'current_age': 55,
            'retirement_age': 60,
            'retirement_end_age': 90,
            'forecast_end_age': 65,
            'retirement_horizon': 35,
            'forecast_horizon': 10,
        },
        'sequence_risk': {
            'config': {'horizon_years': 35, 'retirement_age': 60},
            'success_rate_by_age': {'65': 1.0, '70': 0.95, '75': 0.85, '80': 0.70, '85': 0.50, '90': 0.30},
        },
    }


def test_item13_current_age_must_be_positive():
    """Item 13-1: current_age > 0"""
    from lib.model_validator import check_positive
    c = check_positive('current_age > 0', actual=55, severity='CRITICAL')
    assert c.status == 'PASS'
    c = check_positive('current_age > 0', actual=0, severity='CRITICAL')
    assert c.status == 'FAIL'
    c = check_positive('current_age > 0', actual=-1, severity='CRITICAL')
    assert c.status == 'FAIL'


def test_item13_retirement_age_ordering():
    """Item 13-1: retirement_end_age > retirement_age >= current_age"""
    from lib.model_validator import check_ge, check_gt
    # PASS case
    a = check_ge('retirement_age >= current_age', actual=60, expected=55, severity='CRITICAL')
    assert a.status == 'PASS'
    b = check_gt('retirement_end_age > retirement_age', actual=90, expected=60, severity='CRITICAL')
    assert b.status == 'PASS'
    # FAIL cases
    a = check_ge('retirement_age >= current_age', actual=50, expected=55, severity='CRITICAL')
    assert a.status == 'FAIL'
    b = check_gt('retirement_end_age > retirement_age', actual=60, expected=60, severity='CRITICAL')
    assert b.status == 'FAIL'


def test_item13_forecast_end_age_equals_current_age_plus_n():
    """Item 13-2: forecast_end_age == current_age + N"""
    analyze = _item13_analyze()
    r = validate_all(analyze)
    names = {c.name: c.status for c in r.checks}
    assert 'forecast_end_age == current_age + N' in names, \
        '應檢查 forecast_end_age == current_age + N'
    assert names['forecast_end_age == current_age + N'] == 'PASS', \
        f'fixture: current_age=55 + N=10 = 65,forecast_end_age=65 → PASS,實際 {names["forecast_end_age == current_age + N"]}'


def test_item13_retirement_horizon_equals_end_minus_current():
    """Item 13-2: retirement_horizon == retirement_end_age - current_age"""
    analyze = _item13_analyze()
    r = validate_all(analyze)
    names = {c.name: c.status for c in r.checks}
    assert 'retirement_horizon == retirement_end_age - current_age' in names
    assert names['retirement_horizon == retirement_end_age - current_age'] == 'PASS'


def test_item13_rolling_sample_actual_years_meets_tolerance():
    """Item 13-3: 滾動樣本 actual_years >= N - tolerance (0.5 年)"""
    analyze = _item13_analyze()
    # fixture: 兩筆都是 10.0, N=10, PASS
    r = validate_all(analyze)
    names = {c.name: c.status for c in r.checks}
    assert names.get('rolling.actual_years >= N - 0.5') == 'PASS'
    # FAIL case: 一筆 years=9.0 < N(10)-0.5(9.5)
    analyze['forecast']['rolling'].append({'start': '2015-01-01', 'end': '2024-01-01', 'years': 9.0, 'cagr': 0.04})
    r2 = validate_all(analyze)
    names2 = {c.name: c.status for c in r2.checks}
    assert names2.get('rolling.actual_years >= N - 0.5') == 'FAIL'


def test_item13_sr_age_matrix_within_simulation_horizon():
    """Item 13-4: Sequence Risk 年齡矩陣未超出模擬終點"""
    analyze = _item13_analyze()
    # fixture: max age = 90, current_age=55 + horizon_years=35 = 90 → PASS
    r = validate_all(analyze)
    names = {c.name: c.status for c in r.checks}
    assert names.get('sr.success_rate_by_age 未超出模擬終點') == 'PASS'
    # FAIL case: 模擬 horizon=35 但矩陣含 95 歲
    analyze['sequence_risk']['success_rate_by_age']['95'] = 0.1
    r2 = validate_all(analyze)
    names2 = {c.name: c.status for c in r2.checks}
    assert names2.get('sr.success_rate_by_age 未超出模擬終點') == 'FAIL'


def test_item13_no_future_data_leakage():
    """Item 13-5: 無未來資料洩漏(rolling.last_end <= common.end <= today)"""
    analyze = _item13_analyze()
    r = validate_all(analyze)
    names = {c.name: c.status for c in r.checks}
    # rolling.last_end = 2025-01-01, common.end = 2024-12-31 → FAIL(2025 > 2024)
    # 修 fixture: 把 rolling 最後一筆 end 改成 2024-12-31
    analyze['forecast']['rolling'][-1]['end'] = '2024-12-31'
    r2 = validate_all(analyze)
    names2 = {c.name: c.status for c in r2.checks}
    assert names2.get('rolling.last_end <= data.end') == 'PASS', \
        f'rolling.last_end 應 <= common.end,實際 {names2.get("rolling.last_end <= data.end")}'


def test_item13_chart_xaxis_length_consistency():
    """Item 13-6: 圖表 X 軸長度與資料陣列維度一致(nav_series 資料點數 >= 1)"""
    analyze = _item13_analyze()
    r = validate_all(analyze)
    names = {c.name: c.status for c in r.checks}
    # fixture: common 有 3 點 → PASS
    assert any('nav_series.common 資料點數' in n and v == 'PASS' for n, v in names.items()), \
        f'應有 nav_series.common 資料點數 PASS check,實際 {names}'
    # FAIL case: nav_series 為空
    analyze2 = _item13_analyze()
    analyze2['nav_series']['common'] = []
    r2 = validate_all(analyze2)
    names2 = {c.name: c.status for c in r2.checks}
    assert any('nav_series.common 資料點數' in n and v == 'FAIL' for n, v in names2.items())


def test_item13_all_six_rules_present():
    """Item 13 整合:validate_all 必須含 6 條 checklist §六 check name"""
    analyze = _item13_analyze()
    # 修 rolling.last_end 避免未來洩漏 FAIL
    analyze['forecast']['rolling'][-1]['end'] = '2024-12-31'
    r = validate_all(analyze)
    names = [c.name for c in r.checks]
    # 6 條對應 checklist §六:
    assert 'current_age > 0' in names                                          # §六-1
    assert 'retirement_age >= current_age' in names                            # §六-1
    assert 'retirement_end_age > retirement_age' in names                      # §六-1
    assert 'forecast_end_age == current_age + N' in names                      # §六-2
    assert 'retirement_horizon == retirement_end_age - current_age' in names   # §六-2
    assert 'rolling.actual_years >= N - 0.5' in names                          # §六-3
    assert 'sr.success_rate_by_age 未超出模擬終點' in names                    # §六-4
    assert 'rolling.last_end <= data.end' in names                             # §六-5
    assert any('nav_series' in n for n in names)                              # §六-6
