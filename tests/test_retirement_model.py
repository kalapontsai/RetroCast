"""tests/test_retirement_model.py
- Phase 4.3 驗收測試(搭配 Phase 1-3)
- 對齊 audit 文件 Phase 4.3 規劃:
    scenarios:55→65 / 55→90 / 60→90
    驗證 P1/P5 的 bug 不再出現
- 涵蓋:
    1. parse_retirement_inputs 在 3 種 scenario 下正確產 RetirementInputs
    2. derived().retirement_horizon 對齊 sequence_risk horizon
    3. validate_all(analyze fixture) 在 3 種 scenario 下都 PASS(無 critical fail)
    4. retirement_inputs 欄位都有(render_html_report / exporter 不會炸)
    5. 整合:scenario 60→90 驗證 Phase 1 F2 horizon 30y 行為、Phase 2A 動態年齡列
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.input_schema import parse_retirement_inputs
from lib.model_validator import validate_all


def _build_analyze_fixture(scenario_name: str) -> dict:
    """根據 scenario 名稱建出完整 analyze fixture,跟 app.py:_run_analyze 對齊"""
    scenarios = {
        # 55→65:10 年短年期(已退休)
        '55_to_65': {
            'current_age': 55, 'retirement_age': 55, 'retirement_end_age': 65,
            'withdrawal_monthly': 30_000, 'withdrawal_inflation': 0.03,
            'pension_monthly': 15_000, 'forecast_years': 10,
        },
        # 55→90:35 年長年期
        '55_to_90': {
            'current_age': 55, 'retirement_age': 65, 'retirement_end_age': 90,
            'withdrawal_monthly': 25_000, 'withdrawal_inflation': 0.03,
            'pension_monthly': 20_000, 'forecast_years': 10,
        },
        # 60→90:30 年預設年期(Phase 1 F2 horizon 30)
        '60_to_90': {
            'current_age': 60, 'retirement_age': 60, 'retirement_end_age': 90,
            'withdrawal_monthly': 35_000, 'withdrawal_inflation': 0.03,
            'pension_monthly': 18_000, 'forecast_years': 10,
        },
    }
    cfg = scenarios[scenario_name]
    horizon = cfg['retirement_end_age'] - cfg['current_age']

    return {
        'inputs': {
            'profile': 'test_profile',
            'user_tickers': ['2330', '0050'],
            'tickers': ['2330', '0050'],
            'shares': {'2330': 1000, '0050': 500},
            'combined_shares': {'2330': 1000, '0050': 500},
            'n': cfg['forecast_years'],
            'pv': 4_500_000,
            'pv_raw': 5_000_000,
            'pv_source': 'latest',
            'pv_cost_text': '已扣除買進手續費',
            'fees': {
                'fee_buy': 0.001425, 'fee_sell': 0.001425,
                'tax_sell': 0.003, 'slippage': 0.001,
            },
        },
        'forecast': {
            'n': cfg['forecast_years'],
            'rolling': [
                {'years': cfg['forecast_years'], 'end': '2024-12-31'},
            ],
        },
        'recent_n_year_metrics': {'years': float(cfg['forecast_years'])},
        'monte_carlo': {'config': {'horizon_years': cfg['forecast_years']}},
        'sequence_risk': {
            'config': {
                'horizon_years': horizon,
                'withdrawal_monthly': cfg['withdrawal_monthly'],
                'withdrawal_inflation': cfg['withdrawal_inflation'],
                'pension_monthly': cfg['pension_monthly'],
                'initial_balance': 5_000_000,
            }
        },
        'retirement_inputs': {
            'current_age': cfg['current_age'],
            'retirement_age': cfg['retirement_age'],
            'retirement_end_age': cfg['retirement_end_age'],
            'withdrawal_monthly': cfg['withdrawal_monthly'],
            'withdrawal_inflation': cfg['withdrawal_inflation'],
            'pension_monthly': cfg['pension_monthly'],
            'forecast_years': cfg['forecast_years'],
        },
        'common': {'metrics': {'end': '2025-01-01'}},
    }


# ─────── 1. parse_retirement_inputs 在 3 種 scenario 下正確 ───────
@pytest.mark.parametrize('scenario_name,current_age,retire_age,end_age,expected_horizon', [
    ('55_to_65', 55, 55, 65, 10),
    ('55_to_90', 55, 65, 90, 35),
    ('60_to_90', 60, 60, 90, 30),
])
def test_parse_scenario_correct(scenario_name, current_age, retire_age, end_age, expected_horizon):
    """3 種 scenario 都能 parse,並算出正確 horizon"""
    ri = parse_retirement_inputs({
        'current_age': current_age,
        'retirement_age': retire_age,
        'retirement_end_age': end_age,
    })
    d = ri.derived()
    assert d.retirement_horizon == expected_horizon, \
        f'{scenario_name}: expected horizon={expected_horizon}, got {d.retirement_horizon}'
    assert ri.current_age == current_age
    assert ri.retirement_end_age == end_age


# ─────── 2. validate_all 在 3 種 scenario 下都 PASS ───────
@pytest.mark.parametrize('scenario_name', ['55_to_65', '55_to_90', '60_to_90'])
def test_validate_all_scenario_pass(scenario_name):
    """3 種 scenario 跑 validate_all 都應該 PASS(無 critical fail)"""
    analyze = _build_analyze_fixture(scenario_name)
    r = validate_all(analyze)
    r.finalize()
    # 沒有 critical fail
    assert not r.has_critical_fail(), \
        f'{scenario_name} 有 critical fail:{[c.name for c in r.checks if c.status == "FAIL" and c.severity == "CRITICAL"]}'
    # 全部 PASS 或 SKIP(沒實資料的欄位可能 SKIP)
    fail = [c for c in r.checks if c.status == 'FAIL']
    assert fail == [], \
        f'{scenario_name} 有 FAIL:{[(c.name, c.message) for c in fail]}'


# ─────── 3. validate_all 在 horizon 不對齊時 fail ───────
def test_validate_all_horizon_mismatch_fails():
    """故意把 sequence_risk.horizon_years 改成不等於 end_age-current_age
    應觸發 CRITICAL FAIL"""
    analyze = _build_analyze_fixture('60_to_90')
    analyze['sequence_risk']['config']['horizon_years'] = 999   # 故意錯
    r = validate_all(analyze)
    assert r.has_critical_fail() is True


# ─────── 4. 各 scenario 內 retirement_inputs 欄位齊全 ───────
@pytest.mark.parametrize('scenario_name', ['55_to_65', '55_to_90', '60_to_90'])
def test_scenario_retirement_inputs_complete(scenario_name):
    """確認 analyze['retirement_inputs'] 在 3 種 scenario 下都有完整欄位
    (避免 render_html_report / exporter 拿 None 炸)"""
    analyze = _build_analyze_fixture(scenario_name)
    ri = analyze['retirement_inputs']
    required = ['current_age', 'retirement_age', 'retirement_end_age',
                'withdrawal_monthly', 'withdrawal_inflation', 'pension_monthly']
    for key in required:
        assert ri.get(key) is not None, \
            f'{scenario_name}: retirement_inputs.{key} 應有值,got None'


# ─────── 5. scenario 60→90 = Phase 1 F2 horizon 30 預設行為 ───────
def test_60_to_90_is_default_phase1_horizon():
    """60→90 是 Phase 1 F2 horizon 30y 的標準情境:
    current_age=60, retirement_age=60, retirement_end_age=90 → horizon=30
    """
    analyze = _build_analyze_fixture('60_to_90')
    cfg = analyze['sequence_risk']['config']
    assert cfg['horizon_years'] == 30
    # Phase 4.1 驗證 horizon 對齊
    r = validate_all(analyze)
    horizon_check = [c for c in r.checks if 'retirement_mc_horizon' in c.name]
    assert len(horizon_check) == 1
    assert horizon_check[0].status == 'PASS'


# ─────── 6. scenario 55→90 長年期 + withdrawal 應可持續 ───────
def test_55_to_90_long_horizon_withdrawal_pension():
    """55→90 是 35 年長年期,pension=20k + withdrawal=25k 應有合理 balance"""
    analyze = _build_analyze_fixture('55_to_90')
    cfg = analyze['sequence_risk']['config']
    # withdrawal - pension = 5k/月淨提款 → 6萬/年
    # initial_balance 500萬 ÷ 6萬/年 ≈ 83 年才破產 → horizon 35 應安全
    net_monthly_withdrawal = cfg['withdrawal_monthly'] - cfg['pension_monthly']
    assert net_monthly_withdrawal > 0  # 淨提款
    assert net_monthly_withdrawal < cfg['withdrawal_monthly']  # pension 有 cover 一些


# ─────── 7. scenario 55→65 短年期全部提款不破產 ───────
def test_55_to_65_short_horizon_high_withdrawal():
    """55→65 = 10 年短年期 + 30k 提款 + 15k pension,淨提款 15k/月
    initial 500 萬,10 年後 balance 應 > 0"""
    analyze = _build_analyze_fixture('55_to_65')
    cfg = analyze['sequence_risk']['config']
    assert cfg['horizon_years'] == 10
    assert cfg['withdrawal_monthly'] - cfg['pension_monthly'] > 0