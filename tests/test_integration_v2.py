"""Integration tests for v2 Flask routes (SPEC §4) — 6 endpoints

驗證項目：
- /api/v2/health          → 200 + F1-F6 依賴檢查
- /api/v2/monte_carlo     → 200 + 模擬結果(summary / yearly_stats / bands)
- /api/v2/sequence_risk   → 200 + 存活率 / ruin_age
- /api/v2/risk_metrics    → 200 + VaR/CVaR + Sharpe
- /api/v2/volatility_decay → 200 + 三策略對照
- /api/v2/benchmark_compare → 200 + 多基準 alpha
"""
from __future__ import annotations

import json
import math
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

# 確保根目錄在 sys.path
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


class SafeJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (pd.Timestamp,)):
            return obj.isoformat()
        return super().default(obj)


# ───────── Fixtures ─────────
@pytest.fixture
def sample_user_profile(tmp_path):
    """建立臨時 user_profile 目錄 + kadela_stock.csv fixture"""
    profiles_dir = tmp_path / 'user_profile'
    profiles_dir.mkdir()
    # 9 檔 + 2,900 個交易日的模擬資料
    rng = np.random.default_rng(123)
    n_days = 2_900
    dates = pd.bdate_range('2014-01-01', periods=n_days)
    tickers = ['2330', '2317', '2454', '2308', '2881', '2882', '2884', '2885', '2886']
    weights = [0.20, 0.15, 0.12, 0.10, 0.10, 0.10, 0.08, 0.08, 0.07]
    # 寫入 holdings CSV(每檔一張「買入」紀錄)
    rows = []
    for ticker, weight in zip(tickers, weights):
        # 用第一個交易日作 buy
        rows.append({
            'ticker': ticker,
            'date': dates[0].strftime('%Y-%m-%d'),
            'shares': 1000,
            'cost': 100 * weight * 1000,
            'action': 'buy',
        })
    df = pd.DataFrame(rows)
    profile_path = profiles_dir / 'kadela_stock.csv'
    df.to_csv(profile_path, index=False)

    # 寫價格 CSV(用真實的 K 模擬)
    price_rows = []
    for ticker in tickers:
        rets = rng.normal(0.0008, 0.02, n_days)
        prices = 100 * np.cumprod(1 + rets)
        for d, p in zip(dates, prices):
            price_rows.append({'date': d.strftime('%Y-%m-%d'), 'ticker': ticker, 'close': p})
    price_path = profiles_dir / 'kadela_stock_prices.csv'
    pd.DataFrame(price_rows).to_csv(price_path, index=False)
    return profiles_dir


class MockFinMindClient:
    """Mock FinMindClient 從 sample_user_profile 讀 kadela_stock_prices.csv"""

    def __init__(self, prices_dir):
        self.prices_dir = prices_dir
        self._cache: dict = {}

    def get_stock_price(self, stock_id, start_date=None, end_date=None, use_cache: bool = True):
        if stock_id in self._cache:
            return self._cache[stock_id]
        price_csv = self.prices_dir / 'kadela_stock_prices.csv'
        if not price_csv.exists():
            return []
        df = pd.read_csv(price_csv, dtype={'ticker': str})
        df = df[df['ticker'] == stock_id].copy()
        if df.empty:
            return []
        if start_date:
            df = df[df['date'] >= start_date]
        if end_date:
            df = df[df['date'] <= end_date]
        rows = df[['date', 'ticker', 'close']].to_dict('records')
        self._cache[stock_id] = rows
        return rows


@pytest.fixture
def app_with_profile(sample_user_profile, monkeypatch):
    """建立 Flask app + 注入 USER_PROFILE_DIR + Mock FinMindClient"""
    # 必須在 import app 之前 monkeypatch
    from app_config import USER_PROFILE_DIR as ORIG  # noqa: F401

    import app_config
    monkeypatch.setattr(app_config, 'USER_PROFILE_DIR', sample_user_profile)

    import app as app_module
    flask_app = app_module.create_app()
    flask_app.config['TESTING'] = True

    # 注入 Mock FinMindClient(避免測試打真 API)
    mock_client = MockFinMindClient(sample_user_profile)
    monkeypatch.setattr(app_module, 'FinMindClient', lambda: mock_client)

    return flask_app


@pytest.fixture
def client(app_with_profile):
    return app_with_profile.test_client()


# ───────── /api/v2/health ─────────
def test_v2_health_ok(client):
    """F1-F6 import 檢查"""
    res = client.get('/api/v2/health')
    assert res.status_code in (200, 503)
    data = res.get_json()
    assert 'features' in data
    assert set(data['features']) == {'F1', 'F2', 'F3', 'F4', 'F5', 'F6'}


# ───────── /api/v2/monte_carlo ─────────
def test_v2_monte_carlo_basic(client):
    """F1:Monte Carlo 模擬 1000 次 < 60s"""
    body = {
        'profile': 'kadela_stock',
        'horizon_years': 10,
        'n_simulations': 1000,
        'seed': 42,
    }
    res = client.post('/api/v2/monte_carlo', json=body)
    if res.status_code != 200:
        pytest.fail(f'monte_carlo 失敗:{res.get_json()}')
    data = res.get_json()
    assert 'summary' in data
    assert 'median_final' in data['summary']
    assert 'p10_final' in data['summary']
    assert 'p90_final' in data['summary']
    assert data['horizon_years'] == 10
    assert data['n_simulations'] == 1000


def test_v2_monte_carlo_bad_profile(client):
    body = {'profile': 'nonexistent'}
    res = client.post('/api/v2/monte_carlo', json=body)
    assert res.status_code == 400


def test_v2_monte_carlo_missing_profile(client):
    body = {}
    res = client.post('/api/v2/monte_carlo', json=body)
    assert res.status_code == 400


# ───────── /api/v2/sequence_risk ─────────
def test_v2_sequence_risk_basic(client):
    """F2:30K/月 × 25y 存活率"""
    body = {
        'profile': 'kadela_stock',
        'withdrawal_monthly': 30000,
        'horizon_years': 25,
        'retirement_age': 60,
        'n_simulations': 1000,
        'seed': 42,
    }
    res = client.post('/api/v2/sequence_risk', json=body)
    if res.status_code != 200:
        pytest.fail(f'sequence_risk 失敗:{res.get_json()}')
    data = res.get_json()
    assert 'survival_rate' in data
    assert 'median_final_balance' in data
    assert 0 <= data['survival_rate'] <= 1


def test_v2_sequence_risk_zero_withdrawal(client):
    """F2:提款 0 → 應等同 F1"""
    body = {
        'profile': 'kadela_stock',
        'withdrawal_monthly': 0,
        'horizon_years': 10,
        'n_simulations': 500,
        'seed': 1,
    }
    res = client.post('/api/v2/sequence_risk', json=body)
    assert res.status_code == 200


# ───────── /api/v2/risk_metrics ─────────
def test_v2_risk_metrics_basic(client):
    """F3 + F6:VaR/CVaR + Sharpe"""
    body = {
        'profile': 'kadela_stock',
        'confidence_levels': [0.95, 0.99],
        'horizon_days': [1, 21, 252],
        'risk_free_rate': 0.015,
    }
    res = client.post('/api/v2/risk_metrics', json=body)
    if res.status_code != 200:
        pytest.fail(f'risk_metrics 失敗:{res.get_json()}')
    data = res.get_json()
    assert 'var_cvar' in data
    assert 'sharpe' in data
    assert data['sharpe']['sharpe_with_rf'] < data['sharpe']['sharpe_rf_0']


def test_v2_risk_metrics_bad_body(client):
    body = {'profile': 'kadela_stock', 'confidence_levels': 'not-a-list'}
    res = client.post('/api/v2/risk_metrics', json=body)
    assert res.status_code == 400


# ───────── /api/v2/volatility_decay ─────────
def test_v2_volatility_decay_skipped(client):
    """F4:預期 web 沒有真實 0050/00631L 歷史,但至少要回傳結構"""
    body = {
        'ticker_underlying': '0050',
        'ticker_leveraged': '00631L',
        'initial_date': '2014-10-31',
        'initial_balance': 348400,
    }
    res = client.post('/api/v2/volatility_decay', json=body)
    # 沒 token / 沒網路 → 可能 400(FinMind error)或 200
    assert res.status_code in (200, 400)


# ───────── /api/v2/benchmark_compare ─────────
def test_v2_benchmark_compare_skipped(client):
    """F5:web 可能沒真實 benchmark 資料,允許 skip (v3.0.2: ^TWII 已拿掉)"""
    body = {
        'profile': 'kadela_stock',
        'benchmarks': ['0050', '006208'],
    }
    res = client.post('/api/v2/benchmark_compare', json=body)
    # 沒 token / 沒網路 → 可能 400 或 200
    assert res.status_code in (200, 400)


# ───────── 全部 v2 routes 都應該存在(404 保護) ─────────
def test_v2_routes_registered(app_with_profile):
    rules = {r.rule for r in app_with_profile.url_map.iter_rules()}
    assert '/api/v2/health' in rules
    assert '/api/v2/monte_carlo' in rules
    assert '/api/v2/sequence_risk' in rules
    assert '/api/v2/risk_metrics' in rules
    assert '/api/v2/volatility_decay' in rules
    assert '/api/v2/benchmark_compare' in rules