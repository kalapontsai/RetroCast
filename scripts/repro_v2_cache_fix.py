"""
repro: 確認 /api/v2/volatility_decay (F4) 和 /api/v2/benchmark_compare (F5)
修完後,同一天內連續呼叫兩次會用 cache,不會打 FinMind。

測試方法:
  1. monkey-patch FinMindClient.query,計數呼叫次數
  2. 透過 Flask test client 打兩次 endpoint
  3. 確認: (a) 兩次 endpoint 都被呼叫 (b) FinMindClient.query 只被呼叫 0 次
     (因為 cache 已經在 data/price_cache/ 內)

執行: python3 scripts/repro_v2_cache_fix.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# 把現有 price_cache 備份,測完還原(避免污染)
BACKUP_DIR = Path(tempfile.mkdtemp(prefix='repro_v2_cache_'))
PRICE_CACHE = Path('/mnt/d/stock/retrocast/data/price_cache')


def stash_cache() -> None:
    import shutil
    if PRICE_CACHE.exists():
        shutil.copytree(PRICE_CACHE, BACKUP_DIR / 'price_cache')
        shutil.rmtree(PRICE_CACHE)


def restore_cache() -> None:
    import shutil
    if PRICE_CACHE.exists():
        shutil.rmtree(PRICE_CACHE)
    restored = BACKUP_DIR / 'price_cache'
    if restored.exists():
        shutil.copytree(restored, PRICE_CACHE)


def setup_seed_cache() -> None:
    """在 price_cache 內放兩個看起來合法、涵蓋 default_end_date() 的 cache 檔案,
    這樣 cache hit 才有可能成立。"""
    PRICE_CACHE.mkdir(parents=True, exist_ok=True)
    # 抓 default_end_date() 看一下「前一個月最後一天」到底是哪天
    from datetime import date
    today = date.today()
    if today.month == 1:
        last_month_end = date(today.year - 1, 12, 31)
    else:
        first_of_this_month = date(today.year, today.month, 1)
        from datetime import timedelta
        last_month_end = first_of_this_month - timedelta(days=1)

    end_str = last_month_end.strftime('%Y-%m-%d')
    last_date = last_month_end.isoformat()

    # 0050 給上市日 2003-06-30 ~ end_str 的隨便結構(只需欄位對)
    seed_rows_0050 = [
        {
            'date': '2003-06-30',
            'stock_id': '0050',
            'close': 37.08,
            'open': 37.0, 'max': 37.5, 'min': 36.5, 'Trading_Volume': 1000,
        },
        {
            'date': last_date,
            'stock_id': '0050',
            'close': 100.0,
            'open': 99.0, 'max': 101.0, 'min': 98.0, 'Trading_Volume': 1000,
        },
    ]

    import time as _t
    payload = {
        'stock_id': '0050',
        'fetched_at': _t.time(),
        'fetched_at_iso': '2026-08-28T00:00:00',
        'fetched_start_date': '2003-06-30',
        'row_count': len(seed_rows_0050),
        'rows': seed_rows_0050,
    }
    (PRICE_CACHE / '0050.json').write_text(
        json.dumps(payload, ensure_ascii=False), encoding='utf-8'
    )

    seed_rows_00631L = [
        {
            'date': '2014-10-31',
            'stock_id': '00631L',
            'close': 20.20,
            'open': 20.0, 'max': 20.5, 'min': 19.8, 'Trading_Volume': 1000,
        },
        {
            'date': last_date,
            'stock_id': '00631L',
            'close': 50.0,
            'open': 49.0, 'max': 51.0, 'min': 48.0, 'Trading_Volume': 1000,
        },
    ]
    payload_631 = {
        'stock_id': '00631L',
        'fetched_at': _t.time(),
        'fetched_at_iso': '2026-08-28T00:00:00',
        'fetched_start_date': '2014-10-31',
        'row_count': len(seed_rows_00631L),
        'rows': seed_rows_00631L,
    }
    (PRICE_CACHE / '00631L.json').write_text(
        json.dumps(payload_631, ensure_ascii=False), encoding='utf-8'
    )

    # 006208 benchmark_compare 也會用到
    payload_6208 = {
        'stock_id': '006208',
        'fetched_at': _t.time(),
        'fetched_at_iso': '2026-08-28T00:00:00',
        'fetched_start_date': '2014-01-01',
        'row_count': 2,
        'rows': [
            {'date': '2014-01-01', 'stock_id': '006208', 'close': 20.0,
             'open': 19.5, 'max': 20.5, 'min': 19.0, 'Trading_Volume': 1000},
            {'date': last_date, 'stock_id': '006208', 'close': 80.0,
             'open': 79.0, 'max': 81.0, 'min': 78.0, 'Trading_Volume': 1000},
        ],
    }
    (PRICE_CACHE / '006208.json').write_text(
        json.dumps(payload_6208, ensure_ascii=False), encoding='utf-8'
    )

    # kadela_stock profile cache (給 benchmark_compare)
    payload_kadela = {
        'stock_id': '2330',  # 範例 ticker
        'fetched_at': _t.time(),
        'fetched_at_iso': '2026-08-28T00:00:00',
        'fetched_start_date': '2000-01-04',
        'row_count': 2,
        'rows': [
            {'date': '2000-01-04', 'stock_id': '2330', 'close': 178.0,
             'open': 178.0, 'max': 178.0, 'min': 178.0, 'Trading_Volume': 1000},
            {'date': last_date, 'stock_id': '2330', 'close': 600.0,
             'open': 595.0, 'max': 605.0, 'min': 590.0, 'Trading_Volume': 1000},
        ],
    }
    (PRICE_CACHE / '2330.json').write_text(
        json.dumps(payload_kadela, ensure_ascii=False), encoding='utf-8'
    )

    # kadela_stock.csv holdings (要讓 _get_profile_nav 成功)
    profile_csv = Path('/mnt/d/stock/retrocast/user_profile/kadela_stock.csv')
    if profile_csv.exists():
        print(f'  使用既有 profile: {profile_csv.name}')
    else:
        profile_csv.parent.mkdir(parents=True, exist_ok=True)
        profile_csv.write_text('ticker,shares\n2330,1000\n0050,8000\n', encoding='utf-8')
        print(f'  建立 stub profile: {profile_csv.name}')

    print(f'  種子 cache 涵蓋到 {end_str}')


def main() -> int:
    stash_cache()
    try:
        setup_seed_cache()
        print()

        sys.path.insert(0, '/mnt/d/stock/retrocast')
        from app import create_app
        from lib.finmind import FinMindClient

        app = create_app()
        client = app.test_client()

        # 計數 FinMindClient.query 被呼叫幾次
        call_count = {'n': 0}

        original_query = FinMindClient.query

        def counting_query(self, dataset, params=None):
            call_count['n'] += 1
            print(f'  [FinMind call #{call_count["n"]}] dataset={dataset} params={params}')
            return original_query(self, dataset, params)

        with patch.object(FinMindClient, 'query', counting_query):
            # === Test 1: F4 volatility_decay ===
            print('\n=== Test 1: /api/v2/volatility_decay (連打兩次) ===')
            body = json.dumps({
                'ticker_underlying': '0050',
                'ticker_leveraged': '00631L',
                'initial_date': '2014-10-31',
            })
            r1 = client.post('/api/v2/volatility_decay', data=body, content_type='application/json')
            print(f'  1st call: status={r1.status_code} (cache hit, 不該打 FinMind)')
            n_after_t1_first = call_count['n']

            r2 = client.post('/api/v2/volatility_decay', data=body, content_type='application/json')
            print(f'  2nd call: status={r2.status_code}')
            n_after_t1_second = call_count['n']

            t1_fetched = n_after_t1_second - n_after_t1_first
            print(f'  F4 第二次端點呼叫後,新增 FinMindClient.query 呼叫: {t1_fetched} 次')

            # === Test 2: F5 benchmark_compare ===
            print('\n=== Test 2: /api/v2/benchmark_compare (連打兩次) ===')
            body2 = json.dumps({
                'profile': 'kadela_stock',
                'benchmarks': ['0050', '006208'],
            })
            r3 = client.post('/api/v2/benchmark_compare', data=body2, content_type='application/json')
            print(f'  1st call: status={r3.status_code}')
            n_after_t2_first = call_count['n']

            r4 = client.post('/api/v2/benchmark_compare', data=body2, content_type='application/json')
            print(f'  2nd call: status={r4.status_code}')
            n_after_t2_second = call_count['n']

            t2_fetched = n_after_t2_second - n_after_t2_first
            print(f'  F5 第二次端點呼叫後,新增 FinMindClient.query 呼叫: {t2_fetched} 次')

            print()
            print('=== 結論 ===')
            print(f'  F4 兩次呼叫,後一次新增 FinMind 呼叫: {t1_fetched}')
            print(f'  F5 兩次呼叫,後一次新增 FinMind 呼叫: {t2_fetched}')
            print()
            if t1_fetched == 0 and t2_fetched == 0:
                print('  ✅ PASS: F4/F5 第二次呼叫都用 cache,沒有重抓 FinMind')
                return 0
            else:
                print('  ❌ FAIL: cache 沒生效,還在打 FinMind')
                return 1
    finally:
        restore_cache()


if __name__ == '__main__':
    sys.exit(main())
