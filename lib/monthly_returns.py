"""
lib/monthly_returns.py
v3.0.3 N8: 計算每個 ticker 的逐月逐年報酬表,給 card ⑥ 「歷史真實績效明細表」用。

資料來源:card ⑤ 算過的 daily_returns(每個 ticker 一個 pd.Series,
index=date, name=ticker canonical stock_id)。

演算法(主人 16:02 拍板 Q2=b):
- 月欄位 = 月總報酬: (1 + daily_returns_of_that_month).prod() - 1
- 年平均欄位 = 該年 12 個月報酬的算術平均(arithmetic mean)
- 空資料(月內無交易) = None → 渲染為 '—'

設計:純函式,不做 IO,給 web + html export 共用。
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def compute_monthly_returns_by_ticker(
    daily_returns_by_ticker: Dict[str, pd.Series],
) -> dict:
    """輸入:dict[ticker_canonical → pd.Series of daily returns]
    輸出:{
        'tickers': [
            {
                'ticker': '0050',
                'first_year': 2003,
                'last_year': 2026,
                'data': {
                    2003: {'1': 0.0234, '2': 0.0156, ..., 'year_avg': 0.0123},
                    ...
                },
            },
            ...
        ],
    }

    注意:
    - 每個 ticker 自己的歷史範圍(從 cache 拉到最新;不做 union)
    - 沒資料的 cell → None(渲染為 '—')
    - 年平均 = 12 個月報酬的 arithmetic mean(若有 None 跳過)
    """
    result_tickers = []

    for ticker, daily_rets in daily_returns_by_ticker.items():
        if daily_rets is None or len(daily_rets) == 0:
            continue
        # 過濾 NaN
        clean = daily_rets.dropna()
        if len(clean) == 0:
            continue

        # 轉成 (year, month) 分組,算月總報酬
        # monthly_total = (1 + r).prod() - 1
        try:
            # groupby 對 datetime index
            groups = clean.groupby([clean.index.year, clean.index.month])
            monthly_totals = groups.apply(lambda x: (1 + x).prod() - 1)
        except Exception:
            # 相容 string index
            try:
                idx = pd.to_datetime(clean.index)
                groups = clean.groupby([idx.year, idx.month])
                monthly_totals = (1 + groups).prod() - 1
            except Exception:
                continue

        # 整理成 nested dict
        data: dict[int, dict] = {}
        for (year, month), val in monthly_totals.items():
            year = int(year)
            month = int(month)
            if year not in data:
                data[year] = {}
            v = float(val) if np.isfinite(val) else None
            data[year][str(month)] = v

        # 補齊年平均 (arithmetic mean of 12 monthly returns, skip None)
        for year, months in data.items():
            valid = [v for v in months.values() if v is not None]
            if valid:
                months['year_avg'] = float(np.mean(valid))
            else:
                months['year_avg'] = None

        if not data:
            continue

        first_year = min(data.keys())
        last_year = max(data.keys())

        result_tickers.append({
            'ticker': ticker,
            'first_year': first_year,
            'last_year': last_year,
            'data': data,
        })

    # 排序:ticker 字母序
    result_tickers.sort(key=lambda x: x['ticker'])

    return {'tickers': result_tickers}
