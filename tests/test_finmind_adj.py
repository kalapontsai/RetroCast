"""
tests/test_finmind_adj.py
- Phase 3 驗收:get_stock_price_adj (TaiwanStockPriceAdj 還原除權息)
- 驗證項:
    1. get_stock_price_adj 走 TaiwanStockPriceAdj dataset
    2. cache 寫到 {stock_id}.adj.json (獨立於 .json)
    3. .json 跟 .adj.json 互不污染
    4. ticker variants 也支援 (0050 → 0050)
    5. backward-compat:get_stock_price (TaiwanStockPrice) 行為不變
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

from lib.finmind import FinMindClient


# ───────── Test fixtures ─────────
def _fake_response(dataset: str, params: dict) -> list[dict]:
    """模擬 FinMind API 回傳"""
    import pandas as pd
    stock_id = params['data_id']
    start = params['start_date']
    end = params['end_date']
    # Phase 3 修正:回傳完整區間的 dates,否則 _cache_covers 會誤判 cache miss
    dates = pd.bdate_range(start, end)
    return [
        {'date': d.strftime('%Y-%m-%d'), 'stock_id': stock_id,
         'close': 100.0 + i, 'Trading_Volume': 1_000_000}
        for i, d in enumerate(dates)
    ]


def _make_client(tmp_path: Path, fetch_dataset_log: list[str]) -> FinMindClient:
    """產生 FinMindClient 但 _fetch / query 走 fake,記錄被呼叫的 dataset"""
    from lib.finmind import FINMIND_API_BASE
    client = FinMindClient(token='fake-test-token', cache_dir=tmp_path, cache_ttl_seconds=86400)

    def fake_query(dataset, params):
        fetch_dataset_log.append(dataset)
        return _fake_response(dataset, params)

    # 攔截 query 跟 _fetch,避免真的打 FinMind API
    client.query = fake_query
    return client


# ─────── 1. get_stock_price_adj 走 TaiwanStockPriceAdj ───────
def test_get_stock_price_adj_uses_adj_dataset(tmp_path):
    log: list[str] = []
    client = _make_client(tmp_path, log)
    rows = client.get_stock_price_adj('2330', start_date='2024-01-01', end_date='2024-01-05')
    assert log == ['TaiwanStockPriceAdj'], f'應呼叫 TaiwanStockPriceAdj,got {log}'
    # 2024-01-01 ~ 2024-01-05 = 5 個 bdate
    assert len(rows) == 5, f'應 5 筆 (2024-01-01 ~ 01-05 為 5 bdays),got {len(rows)}'
    assert rows[0]['close'] == 100.0


# ─────── 2. get_stock_price (raw) 走 TaiwanStockPrice ───────
def test_get_stock_price_uses_raw_dataset(tmp_path):
    log: list[str] = []
    client = _make_client(tmp_path, log)
    rows = client.get_stock_price('2330', start_date='2024-01-01', end_date='2024-01-05')
    assert log == ['TaiwanStockPrice'], f'應呼叫 TaiwanStockPrice,got {log}'


# ─────── 3. cache 寫到不同檔名 ───────
def test_adj_cache_separate_from_raw(tmp_path):
    log: list[str] = []
    client = _make_client(tmp_path, log)

    # 兩種都抓一次
    client.get_stock_price('2330', start_date='2024-01-01', end_date='2024-01-05')
    client.get_stock_price_adj('2330', start_date='2024-01-01', end_date='2024-01-05')

    # 應有 2 個 cache file:2330.json + 2330.adj.json
    raw_cache = tmp_path / '2330.json'
    adj_cache = tmp_path / '2330.adj.json'
    assert raw_cache.is_file(), 'raw cache 應寫入 2330.json'
    assert adj_cache.is_file(), 'adj cache 應寫入 2330.adj.json'

    # 內容應為 raw vs adj 兩套獨立 JSON
    raw_data = json.loads(raw_cache.read_text(encoding='utf-8'))
    adj_data = json.loads(adj_cache.read_text(encoding='utf-8'))
    assert raw_data['rows'][0]['close'] == 100.0
    assert adj_data['rows'][0]['close'] == 100.0   # fake 一樣,但檔案獨立


# ─────── 4. ticker variants 在 adj 也支援 ───────
def test_adj_supports_ticker_variants(tmp_path):
    log: list[str] = []
    client = _make_client(tmp_path, log)
    # 0050 → finmind data_id 為 '0050'
    rows = client.get_stock_price_adj('0050', start_date='2024-01-01', end_date='2024-01-05')
    assert len(rows) == 5, f'應 5 筆,got {len(rows)}'
    assert all(r['stock_id'] == '0050' for r in rows)


# ─────── 5. backward-compat:get_stock_price 不變 ───────
def test_get_stock_price_signature_unchanged(tmp_path):
    """確認原始 get_stock_price 仍然使用 TaiwanStockPrice,且 cache file 仍是 .json"""
    log: list[str] = []
    client = _make_client(tmp_path, log)
    rows = client.get_stock_price('2330', start_date='2024-01-01', end_date='2024-01-05')
    assert log == ['TaiwanStockPrice']
    # cache file 沒 .adj 後綴
    assert (tmp_path / '2330.json').is_file()
    assert not (tmp_path / '2330.adj.json').is_file()


# ─────── 6. cache 互不污染:adj 寫了不影響 raw ───────
def test_adj_cache_does_not_pollute_raw(tmp_path):
    log: list[str] = []
    client = _make_client(tmp_path, log)
    # 先抓 raw
    client.get_stock_price('2330', start_date='2024-01-01', end_date='2024-01-05')
    raw_calls_before = log.count('TaiwanStockPrice')
    # 再抓 adj
    client.get_stock_price_adj('2330', start_date='2024-01-01', end_date='2024-01-05')
    # 再抓 raw (應從 cache 命中,不應再 fetch)
    client.get_stock_price('2330', start_date='2024-01-01', end_date='2024-01-05')
    raw_calls_after = log.count('TaiwanStockPrice')
    assert raw_calls_after == raw_calls_before, 'raw 第二次應走 cache,不應多 fetch'
