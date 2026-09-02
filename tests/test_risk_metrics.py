"""Tests for F3 (VaR/CVaR) + F6 (Sharpe with Rf) — lib/risk_metrics.py

SPEC §2 F3 + F6 acceptance criteria:
- F3: 歷史法 (直接取 percentile) ; CVaR 用條件平均; 多 horizon (1d/21d/252d)
- F3 T3.1: 1d 95% VaR 應為負、絕對值約 1-2%
- F3 T3.2: |CVaR_95| >= |VaR_95| (CVaR 永遠 ≥ VaR 絕對值)
- F6 T6.1: rf=0.015 應比 rf=0 結果低
- F6 T6.2: custom rf=0.05 應比 rf=0.015 結果更低
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lib.risk_metrics import (
    DEFAULT_RISK_FREE_RATE,
    RiskMetricsConfig,
    RiskMetricsError,
    compute_risk_metrics,
    run_risk_metrics,
)


# ───────── Fixtures ─────────
@pytest.fixture
def daily_returns_normal():
    """正常日報酬 ~1.0 std/252=4% 波動"""
    rng = np.random.default_rng(42)
    rets = rng.normal(loc=0.0005, scale=0.01, size=500)
    return pd.Series(rets)


@pytest.fixture
def daily_returns_high_vol():
    """高波動(annual ~30%)"""
    rng = np.random.default_rng(7)
    rets = rng.normal(loc=0.001, scale=0.019, size=500)
    return pd.Series(rets)


# ───────── T3.1: VaR 為負、絕對值合理 ─────────
def test_T3_1_var_1d_95_negative(daily_returns_normal):
    """1d 95% VaR 應為負"""
    cfg = RiskMetricsConfig(confidence_levels=[0.95], horizon_days=[1])
    result = compute_risk_metrics(daily_returns_normal, cfg)
    var = result.var_cvar['var_1d_95']
    assert var is not None
    assert var < 0
    # 1% daily std → 5% percentile 約 -1.645σ ≈ -1.65%
    assert -0.05 < var < -0.005


# ───────── T3.2: |CVaR| >= |VaR| ─────────
def test_T3_2_cvar_more_extreme_than_var(daily_returns_normal):
    """CVaR 絕對值永遠 ≥ VaR"""
    cfg = RiskMetricsConfig(confidence_levels=[0.95, 0.99], horizon_days=[1])
    result = compute_risk_metrics(daily_returns_normal, cfg)
    for cl in (95, 99):
        var = result.var_cvar[f'var_1d_{cl}']
        cvar = result.var_cvar[f'cvar_1d_{cl}']
        assert abs(cvar) >= abs(var) - 1e-6, f'CVaR_{cl}={cvar} should be ≥ |VaR_{cl}|={abs(var)}'


# ───────── 多 horizon (1d / 21d / 252d) ─────────
def test_multiple_horizons_present(daily_returns_normal):
    """1d / 21d / 252d 都應有 VaR/CVaR"""
    cfg = RiskMetricsConfig(confidence_levels=[0.95], horizon_days=[1, 21, 252])
    result = compute_risk_metrics(daily_returns_normal, cfg)
    for h in ('1d', '21d', '252d'):
        assert f'var_{h}_95' in result.var_cvar
        assert f'cvar_{h}_95' in result.var_cvar


# ───────── T6.1: rf=0.015 < rf=0 ─────────
def test_T6_1_sharpe_lower_with_positive_rf(daily_returns_normal):
    """rf > 0 應使 Sharpe with rf < Sharpe rf=0"""
    cfg_no_rf = RiskMetricsConfig(risk_free_rate=0.0)
    cfg_with_rf = RiskMetricsConfig(risk_free_rate=0.015)
    r_no = compute_risk_metrics(daily_returns_normal, cfg_no_rf)
    r_with = compute_risk_metrics(daily_returns_normal, cfg_with_rf)
    assert r_with.sharpe['sharpe_with_rf'] < r_no.sharpe['sharpe_rf_0']


# ───────── T6.2: rf=0.05 < rf=0.015 ─────────
def test_T6_2_higher_rf_lowers_sharpe(daily_returns_normal):
    """rf 越高 → Sharpe 越低"""
    cfg_low = RiskMetricsConfig(risk_free_rate=0.015)
    cfg_high = RiskMetricsConfig(risk_free_rate=0.05)
    r_low = compute_risk_metrics(daily_returns_normal, cfg_low)
    r_high = compute_risk_metrics(daily_returns_normal, cfg_high)
    assert r_high.sharpe['sharpe_with_rf'] < r_low.sharpe['sharpe_with_rf']


# ───────── 多 confidence level ─────────
def test_99_var_more_extreme_than_95(daily_returns_normal):
    """99% VaR 絕對值應 ≥ 95% VaR"""
    cfg = RiskMetricsConfig(confidence_levels=[0.95, 0.99], horizon_days=[1])
    result = compute_risk_metrics(daily_returns_normal, cfg)
    assert abs(result.var_cvar['var_1d_99']) >= abs(result.var_cvar['var_1d_95'])


# ───────── 邊界:太短歷史 → error ─────────
def test_short_history_raises():
    """歷史 < 30 天應 raise"""
    with pytest.raises(RiskMetricsError):
        compute_risk_metrics(pd.Series([0.01] * 10))


# ───────── 邊界:confidence 超出 (0,1) ─────────
def test_invalid_confidence_raises(daily_returns_normal):
    """confidence_level 須在 (0,1)"""
    with pytest.raises(RiskMetricsError):
        RiskMetricsConfig(confidence_levels=[1.5])
    with pytest.raises(RiskMetricsError):
        RiskMetricsConfig(confidence_levels=[0.0])


# ───────── JSON-safety 邊界 ─────────
def test_to_dict_json_safe(daily_returns_normal):
    """to_dict 結果可 json.dumps(透過 SafeJSONEncoder)"""
    import json
    import math

    class SafeJSONEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
                return None
            return super().default(obj)

    result = compute_risk_metrics(daily_returns_normal)
    d = result.to_dict()
    # 不應 raise,即使有 None / float
    s = json.dumps(d, cls=SafeJSONEncoder)
    assert 'var_cvar' in s
    assert 'sharpe' in s


# ───────── run_risk_metrics wrapper ─────────
def test_run_risk_metrics_wrapper(daily_returns_normal):
    """Flask-friendly wrapper"""
    body = {'risk_free_rate': 0.02, 'confidence_levels': [0.95], 'horizon_days': [1, 21]}
    result = run_risk_metrics(daily_returns_normal, body)
    assert 'var_cvar' in result
    assert 'sharpe' in result
    assert result['sharpe']['rf_used'] == 0.02


def test_run_risk_metrics_bad_body(daily_returns_normal):
    """壞 config 應 raise RiskMetricsError"""
    with pytest.raises(RiskMetricsError):
        run_risk_metrics(daily_returns_normal, {'confidence_levels': 'not-a-list'})


# ───────── NumPy array 輸入也支援 ─────────
def test_accepts_numpy_array():
    """可以直接傳 np.ndarray(不一定要 pd.Series)"""
    rng = np.random.default_rng(1)
    rets = rng.normal(0.001, 0.015, 300)
    cfg = RiskMetricsConfig()
    result = compute_risk_metrics(rets, cfg)
    assert result.var_cvar['var_1d_95'] is not None


# ───────── 2026-08-27:NaN-in-Sharpe → JSON 輸出 `NaN` 導致前端崩 ─────────
def test_sharpe_constant_returns_no_nan_or_inf():
    """std≈0(浮點殘差 ~2e-19)的退化輸入:Sharpe 不該是 NaN / inf。
    JSON 必須能 parse;None 也算合法。
    """
    cfg = RiskMetricsConfig()
    rets = np.full(100, 0.001)
    result = compute_risk_metrics(rets, cfg)
    for k in ('sharpe_with_rf', 'sharpe_rf_0'):
        v = result.sharpe[k]
        if isinstance(v, float):
            assert not (np.isnan(v) or np.isinf(v)), f'{k} = {v}'


def test_sharpe_with_inf_input_no_nan_in_to_dict():
    """含 inf 的輸入(模擬 cumprod overflow 場景):to_dict 不該輸出 NaN/inf"""
    rets = np.array([0.01] * 250 + [np.inf] * 50)
    cfg = RiskMetricsConfig()
    result = compute_risk_metrics(rets, cfg)
    d = result.to_dict()

    def _assert_clean(obj, path=''):
        if isinstance(obj, dict):
            for k, v in obj.items():
                _assert_clean(v, f'{path}.{k}')
        elif isinstance(obj, float):
            assert not (np.isnan(obj) or np.isinf(obj)), \
                f'{path} has NaN/inf: {obj}'

    _assert_clean(d)


def test_to_dict_json_dumps_with_nan_scrubbed():
    """_scrub_nan_inf 在 to_dict 層做最後防線:
    即使 _compute_sharpe / _compute_var_cvar 漏掉 NaN(理論上不該),輸出仍乾淨
    """
    rets = np.array([0.01, 0.02, -0.01, 0.03] * 100)
    cfg = RiskMetricsConfig()
    result = compute_risk_metrics(rets, cfg)
    # 模擬「上游漏 NaN」:塞 nan / inf 進結果
    result.sharpe['sharpe_rf_0'] = float('nan')
    result.var_cvar['var_1d_95'] = float('inf')
    d = result.to_dict()
    assert d['sharpe']['sharpe_rf_0'] is None
    assert d['var_cvar']['var_1d_95'] is None


def test_var_cvar_handles_high_sigma_input():
    """高 sigma 輸入(5% daily):cumprod clip + nan-safe,
    不該讓 horizon_returns 產生 inf 進 JSON
    """
    rng = np.random.default_rng(99)
    rets = rng.normal(0.001, 0.05, size=2000)
    cfg = RiskMetricsConfig(horizon_days=[252])
    result = compute_risk_metrics(rets, cfg)
    d = result.to_dict()
    for k, v in d['var_cvar'].items():
        if isinstance(v, float):
            assert not (np.isnan(v) or np.isinf(v)), f'{k} = {v}'
    for k, v in d['sharpe'].items():
        if isinstance(v, float):
            assert not (np.isnan(v) or np.isinf(v)), f'{k} = {v}'


def test_app_json_provider_converts_nan_to_null():
    """確認 create_app 設定的 SafeJSONProvider 把 NaN 轉 null
    2026-08-27 慘案:flask.Flask.json_encoder = ... 在 Flask 3.x 是 no-op,
    輸出 `{"k":NaN}` 不是合法 JSON,前端 fetch().json() 崩。
    """
    from app import create_app
    app = create_app()
    with app.test_request_context():
        out = app.json.dumps({
            'sharpe_rf_0': float('nan'),
            'sharpe_with_rf': float('inf'),
            'normal': 1.23,
        })
    import json
    parsed = json.loads(out)
    assert parsed['sharpe_rf_0'] is None
    assert parsed['sharpe_with_rf'] is None
    assert parsed['normal'] == 1.23


def test_template_sharpe_rows_render_when_none():
    """templates/report.html:354,355 用 | fmt_float filter,
    確認 Sharpe 為 None 時 Jinja 不會炸(2026-08-27 13:28 / 13:41 慘案)
    """
    from jinja2 import Environment
    from lib.exporter import _fmt_float

    env = Environment()
    env.filters['fmt_float'] = _fmt_float

    # 模擬 None 情況
    tpl = env.from_string('{{ x | fmt_float }}')
    assert tpl.render(x=None) == '—'
    tpl2 = env.from_string('{{ x | fmt_float }}')
    assert tpl2.render(x=float('nan')) == '—'
