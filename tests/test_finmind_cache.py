"""tests/test_finmind_cache.py
- 測試 lib.finmind 的 cache 行為（v3.0.2 cache 改這層管）
- 涵蓋: hit / partial hit / N 變動 / cache stale / 跨月 end_date 自動 fetch
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.finmind import FinMindClient, PRICE_CACHE_TTL_SECONDS


# ───────── Test fixtures ─────────
def _make_rows(start: str, end: str) -> list[dict]:
    """產生一段從 start 到 end 的假 daily price rows (含週末,filter 由 caller 處理)"""
    import pandas as pd
    dates = pd.bdate_range(start, end)
    out = []
    for i, d in enumerate(dates):
        out.append({
            'date': d.strftime('%Y-%m-%d'),
            'stock_id': '2330',
            'close': 100 + i * 0.1,
            'Trading_Volume': 1_000_000,
        })
    return out


def _write_fake_cache(cache_file: Path, stock_id: str, rows: list[dict], fetched_at_offset: float = 0):
    """直接寫一個假的 cache 檔"""
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'stock_id': stock_id,
        'fetched_at': time.time() + fetched_at_offset,
        'fetched_at_iso': datetime.now().isoformat(timespec='seconds'),
        'row_count': len(rows),
        'rows': rows,
    }
    cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


class MockFinMindNoFetch:
    """不真的去 fetch 的 mock — 只在 cache miss 時 raise,測試用來確認 cache 路徑"""
    def __init__(self, fail_on_fetch: bool = True):
        self.fail_on_fetch = fail_on_fetch
        self.fetch_calls: list[tuple] = []

    def query(self, dataset, params):
        self.fetch_calls.append((dataset, params))
        if self.fail_on_fetch:
            raise RuntimeError(f'測試不應 fetch — cache miss。dataset={dataset}, params={params}')
        return []


# ───────── Cache hit ─────────
def test_cache_full_hit_no_fetch(tmp_path):
    """cache 涵蓋整個 request range → 0 fetch"""
    rows = _make_rows('2020-01-01', '2024-12-31')
    cache_file = tmp_path / '2330.json'
    _write_fake_cache(cache_file, '2330', rows)

    cfg_client = type('Cfg', (), {'cache_dir': tmp_path, 'cache_ttl_seconds': PRICE_CACHE_TTL_SECONDS})
    client = FinMindClient.__new__(FinMindClient)
    client.cache_dir = tmp_path
    client.cache_ttl_seconds = PRICE_CACHE_TTL_SECONDS
    client._lock = __import__('threading').Lock()
    client._last_call_ms = 0
    client.rate_limit_ms = 0
    client.session = None  # 不會用到

    # 用 cache 全範圍
    start_dt = datetime(2021, 1, 1)
    end_dt = datetime(2024, 6, 1)
    out = client._get_stock_price_single('2330', start_dt, end_dt, use_cache=True)
    assert len(out) > 0, '應從 cache 拿到資料'
    # start 到 end 範圍內
    assert out[0]['date'] >= '2021-01-01'
    assert out[-1]['date'] <= '2024-06-01'


# ───────── Cache partial: 往前擴 ─────────
def test_cache_partial_extend_backward_triggers_fetch(tmp_path, monkeypatch):
    """cache 只有 [2021, 2024],request 要 [2020, 2024] → 應 fetch 補 2020 部分"""
    rows_existing = _make_rows('2021-01-01', '2024-12-31')
    _write_fake_cache(tmp_path / '2330.json', '2330', rows_existing)

    # finmind 現狀: query 拉整段 [start_dt, end_dt],再 merge 進 cache
    # (只補缺的優化是另一個 ticket, 本 test 只驗證 merge 行為)
    rows_fetched = _make_rows('2020-01-01', '2024-06-01')

    client = FinMindClient.__new__(FinMindClient)
    client.cache_dir = tmp_path
    client.cache_ttl_seconds = PRICE_CACHE_TTL_SECONDS
    client._lock = __import__('threading').Lock()
    client._last_call_ms = 0
    client.rate_limit_ms = 0
    client.session = None

    # monkeypatch query 讓它回傳 fetched rows
    def fake_query(dataset, params):
        return rows_fetched
    monkeypatch.setattr(client, 'query', fake_query)

    start_dt = datetime(2020, 1, 1)
    end_dt = datetime(2024, 6, 1)
    out = client._get_stock_price_single('2330', start_dt, end_dt, use_cache=True)

    # 應有 2020-2024 完整資料
    assert out[0]['date'] == '2020-01-01', f'應從 2020 開始, 實際 {out[0]["date"]}'
    # end_date 是 2024-06-01 (週六), bdate_range 跳到 2024-05-31 (週五)
    assert out[-1]['date'] == '2024-05-31', f'應到 2024-05-31 (最後交易日), 實際 {out[-1]["date"]}'

    # cache 應被 merge 並寫回 (應含舊 cache 的 2024-12-31 + 新 fetch 的 2020-01-01)
    merged = json.loads((tmp_path / '2330.json').read_text())
    merged_dates = [r['date'] for r in merged['rows']]
    assert '2020-01-01' in merged_dates
    assert '2024-12-31' in merged_dates, 'merge 應保留舊 cache 超出 request 的部分'


# ───────── Cache partial: 往後擴 (跨月 → 新 fetch) ─────────
def test_cache_partial_extend_forward_cross_month(tmp_path, monkeypatch):
    """模擬「下個月」情境: cache 到 2026-07-31, request 到 2026-08-31 → 補抓 8 月份"""
    rows_existing = _make_rows('2020-01-01', '2026-07-31')
    _write_fake_cache(tmp_path / '2330.json', '2330', rows_existing)

    rows_aug = _make_rows('2026-08-01', '2026-08-31')

    client = FinMindClient.__new__(FinMindClient)
    client.cache_dir = tmp_path
    client.cache_ttl_seconds = PRICE_CACHE_TTL_SECONDS
    client._lock = __import__('threading').Lock()
    client._last_call_ms = 0
    client.rate_limit_ms = 0
    client.session = None

    fetch_called = []
    def fake_query(dataset, params):
        fetch_called.append(params)
        return rows_aug
    monkeypatch.setattr(client, 'query', fake_query)

    start_dt = datetime(2020, 1, 1)
    end_dt = datetime(2026, 8, 31)  # 下個月最後一天
    out = client._get_stock_price_single('2330', start_dt, end_dt, use_cache=True)

    # 應 fetch 8 月部分
    assert len(fetch_called) == 1
    assert fetch_called[0]['end_date'] == '2026-08-31'
    assert out[-1]['date'] == '2026-08-31'


# ───────── N 變動不重抓 (核心需求) ─────────
def test_n_change_does_not_refetch(tmp_path, monkeypatch):
    """核心場景: cache 已有 10 年,改 N=5 不應重新抓取"""
    rows = _make_rows('2016-01-01', '2026-07-31')
    _write_fake_cache(tmp_path / '2330.json', '2330', rows)

    fetch_called = []
    def fake_query(dataset, params):
        fetch_called.append(params)
        return []
    monkeypatch.setattr(FinMindClient, 'query', fake_query)

    client = FinMindClient.__new__(FinMindClient)
    client.cache_dir = tmp_path
    client.cache_ttl_seconds = PRICE_CACHE_TTL_SECONDS
    client._lock = __import__('threading').Lock()
    client._last_call_ms = 0
    client.rate_limit_ms = 0
    client.session = None

    # 第一次: N=10, end_date=2026-07-31 (前一個月最後一天)
    out1 = client.get_stock_price('2330', '2016-01-01', '2026-07-31')
    assert len(out1) > 0
    assert len(fetch_called) == 0, '應從 cache 取得,不應 fetch'

    # 第二次: N=5 (start=2021-01-01), end_date=2026-07-31 不變
    out2 = client.get_stock_price('2330', '2021-01-01', '2026-07-31')
    assert len(out2) > 0
    assert len(fetch_called) == 0, 'N 變動應 0 fetch'


# ───────── TTL 30 天檢查 ─────────
def test_ttl_constant_is_30_days():
    """PRICE_CACHE_TTL_SECONDS 應為 30 天（配合「月度 cache」概念）"""
    assert PRICE_CACHE_TTL_SECONDS == 30 * 86400, (
        f'PRICE_CACHE_TTL_SECONDS 應為 30 天 ({30*86400}), 實際 {PRICE_CACHE_TTL_SECONDS}'
    )


def test_ttl_expired_triggers_refetch(tmp_path, monkeypatch):
    """cache 超過 30 天 → 即使 covers 也應 refetch"""
    rows = _make_rows('2020-01-01', '2024-12-31')
    cache_file = tmp_path / '2330.json'
    # 寫成 31 天前抓的
    _write_fake_cache(cache_file, '2330', rows, fetched_at_offset=-31 * 86400)

    rows_new = _make_rows('2024-01-01', '2024-06-30')

    client = FinMindClient.__new__(FinMindClient)
    client.cache_dir = tmp_path
    client.cache_ttl_seconds = PRICE_CACHE_TTL_SECONDS
    client._lock = __import__('threading').Lock()
    client._last_call_ms = 0
    client.rate_limit_ms = 0
    client.session = None

    fetch_called = []
    def fake_query(dataset, params):
        fetch_called.append(params)
        return rows_new
    monkeypatch.setattr(client, 'query', fake_query)

    start_dt = datetime(2021, 1, 1)
    end_dt = datetime(2024, 6, 1)
    client._get_stock_price_single('2330', start_dt, end_dt, use_cache=True)
    assert len(fetch_called) == 1, 'TTL 過期應 fetch'


# ───────── Cache merge 不會重複 ─────────
def test_cache_merge_dedup(tmp_path, monkeypatch):
    """merge 不應產生重複 rows"""
    rows_existing = _make_rows('2020-01-01', '2022-12-31')
    _write_fake_cache(tmp_path / '2330.json', '2330', rows_existing)

    # fetch 包含重疊日期
    rows_overlap = _make_rows('2022-06-01', '2024-12-31')

    client = FinMindClient.__new__(FinMindClient)
    client.cache_dir = tmp_path
    client.cache_ttl_seconds = PRICE_CACHE_TTL_SECONDS
    client._lock = __import__('threading').Lock()
    client._last_call_ms = 0
    client.rate_limit_ms = 0
    client.session = None

    monkeypatch.setattr(client, 'query', lambda d, p: rows_overlap)

    client._get_stock_price_single('2330', datetime(2020, 1, 1), datetime(2024, 12, 31), True)

    merged = json.loads((tmp_path / '2330.json').read_text())
    dates = [r['date'] for r in merged['rows']]
    assert len(dates) == len(set(dates)), f'merge 後應無重複日期, 實際 {len(dates)} != unique {len(set(dates))}'


# ───────── default_end_date() 測試詳見 test_app.py ─────────


# ───────── v3.0.3: match_tickers_batch ─────────
class FakeStockList:
    """Mock 24h-cached stock list,提供 get_stock_list() 用的固定清單"""

    def __init__(self, rows: list[dict]):
        self.rows = rows

    def __call__(self):
        return self.rows


@pytest.fixture
def fake_stock_list(monkeypatch):
    """塞一個假的 stock list 進 FinMindClient.get_stock_list,避免打真 API"""
    from lib import finmind as _finmind_mod
    rows = [
        {'stock_id': '0050', 'stock_name': '元大台灣50', 'industry_category': 'ETF', 'type': 'twse', 'date': '2026-08-27'},
        {'stock_id': '0056', 'stock_name': '元大高股息', 'industry_category': 'ETF', 'type': 'twse', 'date': '2026-08-27'},
        {'stock_id': '00631L', 'stock_name': '元大台灣50正2', 'industry_category': 'ETF', 'type': 'twse', 'date': '2026-08-27'},
        {'stock_id': '2002', 'stock_name': '中鋼', 'industry_category': '鋼鐵工業', 'type': 'twse', 'date': '2026-08-27'},
        {'stock_id': '2412', 'stock_name': '中華電', 'industry_category': '通信網路業', 'type': 'twse', 'date': '2026-08-27'},
        {'stock_id': '2891', 'stock_name': '中信金', 'industry_category': '金融保險業', 'type': 'twse', 'date': '2026-08-27'},
        {'stock_id': '6208', 'stock_name': '日揚', 'industry_category': '半導體業', 'type': 'tpex', 'date': '2026-08-27'},
        {'stock_id': '2330', 'stock_name': '台積電', 'industry_category': '半導體業', 'type': 'twse', 'date': '2026-08-27'},
    ]
    monkeypatch.setattr(_finmind_mod.FinMindClient, 'get_stock_list', lambda self, **kw: rows)
    return rows


def test_match_tickers_batch_basic(fake_stock_list):
    """happy path:多個 ticker 一次 match"""
    client = FinMindClient()
    result = client.match_tickers_batch(['50', '2002', '6208'])

    assert result['50']['stock_id'] == '0050'
    assert result['50']['source'] == 'padded'
    assert result['2002']['stock_id'] == '2002'
    assert result['2002']['source'] == 'exact'
    assert result['6208']['stock_id'] == '6208'
    assert result['6208']['source'] == 'exact'


def test_match_tickers_batch_unknown_returns_none(fake_stock_list):
    """找不到的 ticker 回 None(不 raise)"""
    client = FinMindClient()
    result = client.match_tickers_batch(['9999', '8888'])

    assert result == {'9999': None, '8888': None}


def test_match_tickers_batch_mixed_known_and_unknown(fake_stock_list):
    """已知 + 未知混雜"""
    client = FinMindClient()
    result = client.match_tickers_batch(['50', '9999', '2002', 'XXXX'])

    assert result['50']['stock_id'] == '0050'
    assert result['9999'] is None
    assert result['2002']['stock_id'] == '2002'
    assert result['XXXX'] is None


def test_match_tickers_batch_empty_list(fake_stock_list):
    """空 list → 空 dict,不呼叫 get_stock_list"""
    call_count = {'n': 0}
    original = FinMindClient.get_stock_list

    def counting(self, **kw):
        call_count['n'] += 1
        return original(self, **kw)

    import lib.finmind as _mod
    _mod.FinMindClient.get_stock_list = counting

    client = FinMindClient()
    result = client.match_tickers_batch([])

    assert result == {}
    assert call_count['n'] == 0


def test_match_tickers_batch_dedup(fake_stock_list):
    """重複 input 只 match 一次(match_ticker 只被呼叫 n_unique 次)"""
    call_count = {'n': 0}
    original = FinMindClient.match_ticker

    def counting(self, inp):
        call_count['n'] += 1
        return original(self, inp)

    import lib.finmind as _mod
    _mod.FinMindClient.match_ticker = counting

    client = FinMindClient()
    result = client.match_tickers_batch(['50', '50', '50', '2002', '2002'])

    # 2 unique inputs → match_ticker 被叫 2 次
    assert call_count['n'] == 2
    assert set(result.keys()) == {'50', '2002'}


def test_match_tickers_batch_strips_whitespace_and_empty(fake_stock_list):
    """空白字串 / None / ' ' 跳過,不進 result"""
    client = FinMindClient()
    result = client.match_tickers_batch(['', '  ', '50', None])

    # None 不會進去(沒 key)
    assert '' not in result
    assert '  ' not in result
    # 但 '50' 跟 '50' 會被 dedup 成 '50'
    assert result.get('50', {}).get('stock_id') == '0050'


def test_match_tickers_batch_already_canonical(fake_stock_list):
    """已經是 canonical 形式 → source='exact',stock_id 不變"""
    client = FinMindClient()
    result = client.match_tickers_batch(['0050', '00631L', '2412'])

    assert result['0050']['stock_id'] == '0050'
    assert result['0050']['source'] == 'exact'
    assert result['00631L']['stock_id'] == '00631L'
    assert result['00631L']['source'] == 'exact'
    assert result['2412']['stock_id'] == '2412'
    assert result['2412']['source'] == 'exact'


def test_match_tickers_batch_padded_short_to_long(fake_stock_list):
    """短數字 → 補 0 到 4/6 碼(對 ETF 來說是 4 碼)"""
    client = FinMindClient()
    result = client.match_tickers_batch(['50', '56', '631'])  # 631 找不到(無此 ETF)

    assert result['50']['stock_id'] == '0050'
    assert result['56']['stock_id'] == '0056'
    assert result['631'] is None  # 不存在


# ───────── first_trading_day cache (v3.0.4 fix) ─────────
def test_first_trading_day_cache_hit_after_first_fetch(tmp_path):
    """第一次 query FinMind, 第二次讀 cache 不再 query"""
    from unittest.mock import patch

    cache_dir = tmp_path / 'cache'
    client = FinMindClient(cache_dir=cache_dir)

    call_count = {'n': 0}

    def fake_query(self_or_dataset, dataset_or_params=None, params=None):
        # 容忍兩種呼叫形態 (instance 或 unbound)
        if params is None:
            params = dataset_or_params
            dataset = self_or_dataset
        else:
            dataset = self_or_dataset
        call_count['n'] += 1
        return [
            {'date': '2003-06-30', 'close': 37.0},
            {'date': '2024-01-01', 'close': 100.0},
        ]

    with patch.object(FinMindClient, 'query', side_effect=fake_query):
        d1 = client.get_first_trading_day('0050')
        d2 = client.get_first_trading_day('0050')

    assert d1 == '2003-06-30'
    assert d2 == '2003-06-30'
    assert call_count['n'] == 1, f'第二次應該走 cache, 但 query 被叫了 {call_count["n"]} 次'


def test_first_trading_day_cache_persists(tmp_path):
    """Cache 寫到磁碟, 新 client 實例讀得到"""
    cache_dir = tmp_path / 'cache'
    # 第一次建立 cache
    c1 = FinMindClient(cache_dir=cache_dir)
    c1._save_first_trading_day_entry('2330', '2000-01-04')

    # 新實例讀 (應該命中)
    c2 = FinMindClient(cache_dir=cache_dir)
    result = c2._load_first_trading_day_entry('2330')
    assert result == '2000-01-04'


def test_first_trading_day_cache_ttl_expired(tmp_path):
    """TTL 過期 → load 回 None"""
    cache_dir = tmp_path / 'cache'
    client = FinMindClient(cache_dir=cache_dir, cache_ttl_seconds=1)

    # 手寫一個「已過期」的 entry
    cache_file = cache_dir / 'first_trading_days.json'
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({
        'days': {
            '0050': {
                'date': '2003-06-30',
                'fetched_at': time.time() - 100,  # 100 秒前
            }
        }
    }), encoding='utf-8')

    assert client._load_first_trading_day_entry('0050') is None


def test_first_trading_day_corrupt_cache_returns_none(tmp_path):
    """Cache 檔壞掉 / 不是 dict → 不爆, 回 None"""
    cache_dir = tmp_path / 'cache'
    cache_dir.mkdir(parents=True)
    (cache_dir / 'first_trading_days.json').write_text('THIS IS NOT JSON', encoding='utf-8')

    client = FinMindClient(cache_dir=cache_dir)
    assert client._load_first_trading_day_entry('0050') is None


def test_first_trading_day_filters_zero_price_rows(tmp_path):
    """'close' <= 0.5 (FinMind 假資料) 應被過濾掉, 不會被誤判為 first_trading_day"""
    from unittest.mock import patch

    cache_dir = tmp_path / 'cache'
    client = FinMindClient(cache_dir=cache_dir)

    def fake_query(self, dataset, params=None):
        return [
            {'date': '2000-01-01', 'close': 0.01},   # 假資料
            {'date': '2000-01-02', 'close': 0.0},    # 假資料
            {'date': '2000-01-04', 'close': 178.0},  # 真資料
        ]

    with patch.object(FinMindClient, 'query', side_effect=fake_query):
        d = client.get_first_trading_day('2330')

    assert d == '2000-01-04'
