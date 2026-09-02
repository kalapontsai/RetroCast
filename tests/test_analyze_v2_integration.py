"""B4 Integration tests — `/api/analyze` returning v2 results (F1/F2/F3/F6)

驗證事項：
- /api/analyze 預設 enable_v2=True → response 含 monte_carlo / sequence_risk / risk_metrics
- /api/analyze enable_v2=False → 三個欄位都是 None
- v1 analyze 結果不破壞(向後相容)
- 個別 v2 失敗不破壞整體 analyze

股寶驗收流程：跑這個 test 看 /api/analyze 是否真的帶 F1/F2/F3/F6 結果。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


@pytest.fixture
def analyze_profile(tmp_path):
    """建立 kadela_stock 模擬 profile + daily prices"""
    profiles_dir = tmp_path / 'user_profile'
    profiles_dir.mkdir()
    rng = np.random.default_rng(99)
    n_days = 252 * 8
    dates = pd.bdate_range('2016-01-01', periods=n_days)
    tickers = ['2330', '2317', '2454', '2308', '2881', '2882', '2884', '2885', '2886']
    weights = np.array([0.20, 0.15, 0.12, 0.10, 0.10, 0.10, 0.08, 0.08, 0.07])
    target_total = 7_236_096
    shares = (target_total * weights / 100).astype(int)

    # holdings
    rows = []
    for ticker, sh in zip(tickers, shares):
        rows.append({
            'ticker': ticker,
            'date': dates[0].strftime('%Y-%m-%d'),
            'shares': int(sh),
            'cost': 100,
            'action': 'buy',
        })
    pd.DataFrame(rows).to_csv(profiles_dir / 'kadela_stock.csv', index=False)

    # daily prices
    daily_ret = rng.normal(0.0002, 0.018, (n_days, 9))
    price_rows = []
    for i, ticker in enumerate(tickers):
        prices = 100 * np.cumprod(1 + daily_ret[:, i])
        for d, p in zip(dates, prices):
            price_rows.append({'date': d.strftime('%Y-%m-%d'), 'ticker': ticker, 'close': p})
    pd.DataFrame(price_rows).to_csv(profiles_dir / 'kadela_stock_prices.csv', index=False)
    return profiles_dir


class MockFinMindAnalyze:
    """Mock 同時支援 TaiwanStockInfo + TaiwanStockPrice + StockList"""
    def __init__(self, profiles_dir):
        self.profiles_dir = profiles_dir
        self._stock_list = None

    def get_stock_list(self, use_cache=True, ttl=86400):
        if self._stock_list is None:
            # 從 holdings + 預設 industry_category 模擬
            df = pd.read_csv(self.profiles_dir / 'kadela_stock.csv', dtype={'ticker': str})
            self._stock_list = []
            for ticker in df['ticker']:
                self._stock_list.append({
                    'stock_id': str(ticker),
                    'stock_name': f'TEST_{ticker}',
                    'industry_category': 'TEST',
                    'type': '股票',
                    'source': 'mock',
                })
        return self._stock_list

    def match_ticker(self, user_input):
        user_input = str(user_input).strip()
        for s in self.get_stock_list():
            if s['stock_id'] == user_input:
                return {
                    'stock_id': s['stock_id'],
                    'stock_name': s['stock_name'],
                    'industry_category': s['industry_category'],
                    'type': s['type'],
                    'source': s['source'],
                }
        return None

    def get_first_trading_day(self, stock_id):
        # 用第一個日期作為 first_trading_day
        df = pd.read_csv(self.profiles_dir / 'kadela_stock_prices.csv', nrows=1)
        return df['date'].iloc[0]

    def get_stock_price(self, stock_id, start_date=None, end_date=None, use_cache: bool = True):
        df = pd.read_csv(self.profiles_dir / 'kadela_stock_prices.csv', dtype={'ticker': str})
        df = df[df['ticker'] == str(stock_id)].copy()
        if start_date:
            df = df[df['date'] >= start_date]
        if end_date:
            df = df[df['date'] <= end_date]
        return df[['date', 'ticker', 'close']].to_dict('records')


@pytest.fixture
def analyze_app(analyze_profile, monkeypatch):
    import app_config
    monkeypatch.setattr(app_config, 'USER_PROFILE_DIR', analyze_profile)
    import app as app_module
    flask_app = app_module.create_app()
    flask_app.config['TESTING'] = True
    mock = MockFinMindAnalyze(analyze_profile)
    monkeypatch.setattr(app_module, 'FinMindClient', lambda: mock)
    return flask_app


@pytest.fixture
def client(analyze_app):
    return analyze_app.test_client()


# ───────── enable_v2=True（預設）─────────────────────────────────────
def test_analyze_default_includes_v2(client):
    """預設 enable_v2=True → response 應含 F1/F2/F3/F6"""
    body = {
        'profile': 'kadela_stock',
        'n': 5,
        'pv': 7_236_096,
        'v2_n_simulations': 200,  # 加速
        'v2_horizon_years': 10,
    }
    res = client.post('/api/analyze', json=body)
    assert res.status_code == 200, f'got {res.status_code}: {res.get_json()}'
    data = res.get_json()

    # v1 結果仍在
    assert 'common' in data
    assert 'dynamic' in data
    assert 'full' in data
    assert 'nav_series' in data

    # v2 三個欄位都在
    assert 'monte_carlo' in data
    assert 'sequence_risk' in data
    assert 'risk_metrics' in data


def test_analyze_v2_monte_carlo_basic(client):
    """F1 MC 結果結構正確"""
    body = {
        'profile': 'kadela_stock',
        'n': 5,
        'pv': 7_236_096,
        'v2_n_simulations': 100,
    }
    res = client.post('/api/analyze', json=body)
    data = res.get_json()
    mc = data['monte_carlo']
    assert mc is not None
    assert 'summary' in mc
    assert 'median_final' in mc['summary']
    assert 'yearly_stats' in mc


def test_analyze_v2_sequence_risk_basic(client):
    """F2 Sequence Risk 結果結構正確"""
    body = {
        'profile': 'kadela_stock',
        'n': 5,
        'pv': 7_236_096,
        'v2_n_simulations': 100,
        'v2_withdrawal_monthly': 30_000,
    }
    res = client.post('/api/analyze', json=body)
    data = res.get_json()
    sr = data['sequence_risk']
    assert sr is not None
    assert 'survival_rate' in sr
    assert 0 <= sr['survival_rate'] <= 1


def test_analyze_v2_risk_metrics_basic(client):
    """F3+F6 risk metrics 結果結構正確"""
    body = {
        'profile': 'kadela_stock',
        'n': 5,
        'pv': 7_236_096,
        'v2_risk_free_rate': 0.015,
    }
    res = client.post('/api/analyze', json=body)
    data = res.get_json()
    rm = data['risk_metrics']
    assert rm is not None
    assert 'var_cvar' in rm
    assert 'sharpe' in rm
    assert 'sharpe_with_rf' in rm['sharpe']
    assert 'sharpe_rf_0' in rm['sharpe']


# ───────── enable_v2=False ─────────
def test_analyze_enable_v2_false(client):
    """enable_v2=False → 三個 v2 欄位都是 None,但 v1 不受影響"""
    body = {
        'profile': 'kadela_stock',
        'n': 5,
        'pv': 7_236_096,
        'enable_v2': False,
    }
    res = client.post('/api/analyze', json=body)
    assert res.status_code == 200
    data = res.get_json()
    assert data['monte_carlo'] is None
    assert data['sequence_risk'] is None
    assert data['risk_metrics'] is None
    # v1 仍在
    assert 'common' in data
    assert 'dynamic' in data


# ───────── 個別 v2 失敗不破壞整體 ─────────
def test_analyze_v2_partial_failure_continues(client, monkeypatch):
    """若某個 v2 失敗,其他 v2 + v1 仍應返回(用 None 標記失敗)"""
    body = {
        'profile': 'kadela_stock',
        'n': 5,
        'pv': 7_236_096,
        'v2_n_simulations': 100,  # F1 + F3 應成功
        'v2_withdrawal_monthly': -1,  # 故意壞掉 F2(< 0)
    }
    res = client.post('/api/analyze', json=body)
    # 即使 F2 失敗,整體仍應 200
    assert res.status_code == 200, f'got {res.status_code}: {res.get_json()}'
    data = res.get_json()
    # F2 應 None,F1/F3 應有值
    assert data['sequence_risk'] is None
    # F1 + F3 仍應跑出來
    assert data['monte_carlo'] is not None
    assert data['risk_metrics'] is not None


# ───────── v1 結果未受 v2 影響 ─────────
def test_analyze_v1_results_unchanged(client):
    """v1 analyze 的 modes / nav_series 不應被 v2 計算搞壞"""
    body = {
        'profile': 'kadela_stock',
        'n': 5,
        'pv': 7_236_096,
        'enable_v2': False,
    }
    res_v1_only = client.post('/api/analyze', json=body)
    data_v1 = res_v1_only.get_json()

    body2 = {**body, 'enable_v2': True, 'v2_n_simulations': 100}
    res_v1_v2 = client.post('/api/analyze', json=body2)
    data_v1_v2 = res_v1_v2.get_json()

    # v1 結果(common/dynamic/full + nav_series)在兩種情況應一致
    assert data_v1['common'] == data_v1_v2['common']
    assert data_v1['dynamic'] == data_v1_v2['dynamic']
    assert data_v1['full'] == data_v1_v2['full']
    assert data_v1['nav_series'] == data_v1_v2['nav_series']


# ───────── v3.0.3: normalize gate in _fetch_daily_portfolio_returns ─────────
# 用 standalone fixture,不依賴 analyze_app / client,避免 MockFinMindAnalyze
# 綁 kadela_stock 造成衝突。直接測 _fetch_daily_portfolio_returns 的 gate 行為。
@pytest.fixture
def normalize_gate_env(tmp_path, monkeypatch):
    """設置完整的 normalize gate 測試環境。
    注意：analyze_app fixture 會把 app.FinMindClient 換成 lambda: mock，
    雖然 monkeypatch 應該 revert，但某些情境下會漏(尤其跨模組的 from import)。
    這裡強制 setattr 回原始 class,確保我的測試拿到的是真實 FinMindClient。
    """
    import app_config
    import app as _app_mod
    from lib import finmind as _finmind_mod
    from lib import daily_prices as _dp_mod
    import pandas as pd

    # 先強制把 app.FinMindClient 設回原始 class (防 analyze_app 污染)
    monkeypatch.setattr(_app_mod, 'FinMindClient', _finmind_mod.FinMindClient)
    # 重點:app.py 用 `from app_config import USER_PROFILE_DIR` 拿到 module-level binding,
    # 所以要同時 patch app_config (原始) + app (已 import 的 binding) 才有效。
    monkeypatch.setattr(app_config, 'USER_PROFILE_DIR', tmp_path)
    monkeypatch.setattr(_app_mod, 'USER_PROFILE_DIR', tmp_path)

    rows = [
        {'stock_id': '0050', 'stock_name': '元大台灣50', 'industry_category': 'ETF', 'type': 'twse'},
        {'stock_id': '0056', 'stock_name': '元大高股息', 'industry_category': 'ETF', 'type': 'twse'},
        {'stock_id': '00631L', 'stock_name': '元大台灣50正2', 'industry_category': 'ETF', 'type': 'twse'},
        {'stock_id': '2002', 'stock_name': '中鋼', 'industry_category': '鋼鐵', 'type': 'twse'},
        {'stock_id': '2330', 'stock_name': '台積電', 'industry_category': '半導體', 'type': 'twse'},
    ]
    monkeypatch.setattr(
        _finmind_mod.FinMindClient, 'get_stock_list', lambda self, **kw: rows,
    )

    def mock_daily_prices_by_stock(client, symbols, config):
        idx = pd.bdate_range('2024-01-01', periods=10)
        known = {r['stock_id'] for r in rows}
        data = {s: [100.0 + i for i in range(10)] for s in symbols if s in known}
        return pd.DataFrame(data, index=idx)
    monkeypatch.setattr(_dp_mod, 'daily_prices_by_stock', mock_daily_prices_by_stock)
    return {'tmp_path': tmp_path, 'rows': rows}


def test_analyze_gate_unknown_ticker_raises_badinput(normalize_gate_env):
    """_fetch_daily_portfolio_returns on unknown-ticker CSV → _BadInput with code"""
    from app import _fetch_daily_portfolio_returns, _BadInput
    tmp = normalize_gate_env['tmp_path']
    (tmp / 'bad.csv').write_text('9999,100\n', encoding='utf-8')

    with pytest.raises(_BadInput) as exc_info:
        _fetch_daily_portfolio_returns('bad')
    assert exc_info.value.code == 'TICKER_NOT_FOUND'
    assert exc_info.value.details['failed'][0]['ticker'] == '9999'
    assert exc_info.value.details['profile'] == 'bad'


def test_analyze_gate_already_canonical_passes_through(normalize_gate_env):
    """冪等:已 canonical 的 CSV 直接 pass through,不重寫"""
    from app import _fetch_daily_portfolio_returns
    tmp = normalize_gate_env['tmp_path']
    p = tmp / 'good.csv'
    p.write_text('0050,100\n2002,500\n', encoding='utf-8')
    rets, meta = _fetch_daily_portfolio_returns('good')
    assert len(rets) > 0
    # 檔案未被改動
    assert p.read_text(encoding='utf-8-sig') == '0050,100\n2002,500\n'


def test_analyze_gate_normalizes_then_passes_through(normalize_gate_env):
    """50 → 0050 normalize 成功 → pass through + 寫回"""
    from app import _fetch_daily_portfolio_returns
    tmp = normalize_gate_env['tmp_path']
    p = tmp / 'normalize.csv'
    p.write_text('50,100\n2002,500\n', encoding='utf-8')
    rets, meta = _fetch_daily_portfolio_returns('normalize')
    assert len(rets) > 0
    content = p.read_text(encoding='utf-8-sig')
    assert content.startswith('0050,100')


def test_analyze_gate_malformed_csv_returns_badinput(normalize_gate_env):
    """malformed CSV → CSVLintError 轉 _BadInput(無 code)"""
    from app import _fetch_daily_portfolio_returns, _BadInput
    tmp = normalize_gate_env['tmp_path']
    (tmp / 'malformed.csv').write_text('50 100\n', encoding='utf-8')
    with pytest.raises(_BadInput) as exc_info:
        _fetch_daily_portfolio_returns('malformed')
    assert exc_info.value.code is None
    assert 'CSV 格式錯誤' in str(exc_info.value)


def test_analyze_gate_missing_profile_returns_badinput(normalize_gate_env):
    """profile 不存在 → 既有 _BadInput"""
    from app import _fetch_daily_portfolio_returns, _BadInput
    with pytest.raises(_BadInput, match='不存在'):
        _fetch_daily_portfolio_returns('nonexistent')
