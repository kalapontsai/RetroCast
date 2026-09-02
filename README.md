# RetroCast — 股票組合歷史回測 + 退休決策工具

> **📌 專案原名**：retirement_decision_v2（2026-08-26 改名為 **RetroCast**）
> 歷史 commit 維持原樣，新 commit 走新 repo。
> **🚀 目前版本**：v3.1.2（2026-09-01）。已整合 Monte Carlo、Sequence Risk、VaR/CVaR、多基準比較、波動耗損、Sharpe with Rf、退休年齡模型與報告驗收修正。
> 📋 詳細 spec：`SPEC.md` · 變更紀錄：`CHANGELOG.md`
> 🔗 GitHub：`https://github.com/kalapontsai/RetroCast`

## 1. 專案目的

本工具用於分析「一籃子股票」的歷史總報酬，並以歷史資料中的 **N-Year Rolling CAGR 分布**建立未來 N 年後的情境估計。

核心定位不是逐年預測股價，也不是聲稱可以精準預測未來，而是回答：

> 如果目前這一籃子股票在未來持有 N 年，歷史上相同長度的投資期間曾經出現什麼樣的報酬結果？

因此 Forecast 只輸出 **N 年後的終值情境**，不建立未來每一年的模擬路徑。

---

## 2. 分析架構

```text
CSV 股票價格資料
        │
        ▼
資料清理 / 日期排序 / 股票代號整理
        │
        ▼
三種歷史回測模式
 ┌──────────────┬────────────────┬──────────────────┐
 │ Common       │ Dynamic Entry  │ Full Available   │
 │ Period       │                │ History          │
 └──────────────┴────────────────┴──────────────────┘
        │
        ▼
Portfolio Daily Return
        │
        ▼
Portfolio NAV
        │
        ├── Total Return
        ├── CAGR
        ├── MDD
        ├── Volatility
        └── Sharpe
        │
        ▼
Historical N-Year Rolling CAGR
        │
        ▼
P10 / P25 / P50 / P75 / P90
        │
        ▼
Future N-Year Terminal Value
```

---

## 3. 三種歷史回測模式

### 3.1 Common Period

找出所有股票共同具有有效價格資料的期間，只在共同期間內進行組合回測。

用途：

- 公平比較不同股票
- 避免某些股票因歷史資料較短而取得額外時間優勢
- 最適合做「一籃子股票歷史績效」的主要比較

公式：

\[
R_{p,t}=\sum_i w_iR_{i,t}
\]

\[
NAV_t=NAV_{t-1}(1+R_{p,t})
\]

預設使用等權重；如果指定權重，則對有效股票權重重新標準化。

---

### 3.2 Dynamic Entry

每一支股票從其第一個有效價格開始加入組合。

某一天只有部分股票有報酬資料時，只對當天可觀測股票重新正規化權重，**並設上限 cap = 1.5 / N_total**（避免 1 檔被放大為 100% weight 造成 early period MDD 被蓋大）。

**v2 改動 (2026-08-21)**：加上 cap 以避免早期股票被放大。N=9 股票時:
- 1 stock active: 上限 16.7% (原本 100%)
- 2 stocks active: 上限 16.7% each (total 33.3%)
- 4+ stocks active: normal 運作

用途：

- 模擬股票逐步進入資料集合的情境
- 分析不同股票歷史長度對組合績效的影響

注意：這是一種研究定義，不代表真實交易一定會採用完全相同的進場規則。

---

### 3.3 Full Available History

每支股票從自己最早資料日開始計入。**Fixed weights + fillna(0)** — 未上市股票視為 0% return（不算進 portfolio），不重新正規化權重。

**v2 改動 (2026-08-21)**：原本 = dynamic (重新正規化) → 改為 fixed weights + fillna(0)。差別:
- dynamic: dropna + renormalize (cap 1.5/N)
- full: fillna(0) + fixed weights (從第一天就以原重計入)

用途：

- 個股歷史資料診斷
- 觀察整個股票池在「各自可觀測期間」下的表現

不應直接把這個結果解讀成嚴格的 Point-in-Time 歷史投資策略。

**注意**：v2 之後 full 的 MDD 比 dynamic 低（因為不重新正規化）。兩者差異會隨 N 股票上市後越來越小。

---

## 4. 股票歷史長度問題

本工具假設：

> 股票池中的股票本身都屬於研究對象；問題只有歷史資料長短不同。

因此：

- 尚未出現資料的日期不是 0% 報酬
- 不會將不存在的歷史資料填成 0%
- 不會把短期報酬強制外推成完整歷史
- 不會因為歷史短就自動刪除股票

報表會顯示：

- 股票數
- 最短歷史年數
- 中位數歷史年數
- 最長歷史年數

---

## 5. 未來 N 年 Forecast

### 5.1 基本概念

使用歷史 Portfolio NAV 建立所有可取得的 N-Year rolling periods。

例如：

```text
N = 10

2010 → 2020
2011 → 2021
2012 → 2022
2013 → 2023
...
```

每一段計算：

\[
CAGR_N=
\left(\frac{NAV_{end}}{NAV_{start}}\right)^{1/years}-1
\]

再將全部歷史 N-Year CAGR 排序，取得：

- P10：Bear
- P25：Conservative
- P50：Base
- P75：Optimistic
- P90：Bull

---

### 5.2 N 年後終值

使用：

\[
FV_N=PV(1+r_N)^N
\]

其中：

- \(PV\)：目前資產
- \(r_N\)：歷史 N-Year CAGR 對應分位數
- \(N\)：使用者指定的未來年數

例如目前資產為 10,000,000，N=10：

```text
P10 CAGR → Bear
P25 CAGR → Conservative
P50 CAGR → Base
P75 CAGR → Optimistic
P90 CAGR → Bull
```

---

## 6. 為什麼不直接使用個股 CAGR 平均？

不採用：

\[
Portfolio\ CAGR=
\frac{CAGR_1+CAGR_2+\cdots+CAGR_n}{n}
\]

原因是 CAGR 不是可以直接做算術平均後代表組合 CAGR 的每日報酬量。

本工具先：

```text
個股價格
→ 個股報酬
→ Portfolio Daily Return
→ Portfolio NAV
→ Portfolio CAGR
```

再從 Portfolio NAV 建立 N-Year rolling outcome。

這樣比較符合「一籃子股票總報酬」的定義。

---

## 7. CSV 格式

最少需要三個欄位：

```csv
Date,Ticker,Adj_Close
2020-01-02,2330,332.5
2020-01-02,2317,78.2
2020-01-02,2454,334.0
```

支援欄位名稱：

### 日期

- Date
- Datetime
- Time

### 股票代號

- Ticker
- Symbol
- Code
- Stock

### 價格

- Adj_Close
- Adjusted_Close
- Close
- Price

正式回測建議優先使用 **Adjusted Close / Total Return Price**，以避免除權息與股票分割造成錯誤。

---

## 8. 權重

若未輸入 `weights`，且持股資料包含 `shares`，預設使用「起始市值權重」：每支股票以**自己最後一個有效日的 raw close × 股數**計算市值，再將市值 normalize。

```text
起始市值權重（與 UI 顯示的組合起始市值同源）
```

跟 `compute_market_value()` 演算法一致 — 二、歷史真實績效 跟 〇、組合起始市值 用**同一組權重**，讓 UI 顯示的權重比例 = 回測用的權重比例。

權重優先序：
1. **使用者自訂** — `weights=2330:0.3,2317:0.7`，sum 不一定要 1，會自動 normalize
2. **起始市值權重（預設）** — `compute_market_value()` 結果 normalize（與 〇 同源）
3. **等權重 fallback** — 若 caller 沒給 weights 也沒給 shares（向後相容 / 單元測試用）

例如 2 支股票（2330 × 1000 股 @ 500 元 + 2317 × 2000 股 @ 80 元，「最後一個有效日」仍維持該價）：

```text
500 × 1000 = 500,000 → 500,000 / 580,000 ≈ 86.2%
80  × 2000 = 160,000 → 160,000 / 580,000 ≈ 13.8%
```

也可以指定：

```text
2330:0.3,2317:0.7
```

> 主人 2026-08-31 18:45 更正：原本「buy & hold 假設」用「第一個交易日」close × 股數 → 改為「最後一個有效日」raw close × 股數，與 〇、組合起始市值同源。
> 理由：避免 UI 顯示權重 跟 回測用權重 不一致，造成「我看到 86% / 14% 但報告用 62% / 38% 算」的混淆。

---

## 9. 安裝

需要 Python 3.10+。

```bash
pip install -r requirements.txt
```

啟動：

```bash
python app.py
```

瀏覽器：

```text
http://127.0.0.1:5000
```

---

## 10. API

### 主要端點

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/health` | v1 健康檢查 |
| GET | `/api/profiles` | 列出可用持股 CSV |
| GET | `/api/profile/<name>` | 預覽持股檔 |
| POST | `/api/upload_profile` | 上傳並驗證持股 CSV |
| POST | `/api/analyze` | 主分析、forecast 與 F1/F2/F3/F6 |
| POST | `/api/export` | 匯出 HTML 報告 |
| POST | `/api/v2/monthly_returns` | 歷史月報酬明細 |

### POST `/api/analyze`

輸入：

- `file`: CSV
- `mode`: common / dynamic / full
- `n`: 未來 N 年
- `initial_value`: 目前資產
- `weights`: 選填

輸出 JSON：

```text
metrics
forecast
rolling_count
history
nav
rolling
```

### v2 專用端點

`POST /api/v2/monte_carlo`、`/api/v2/sequence_risk`、`/api/v2/risk_metrics`、`/api/v2/volatility_decay`、`/api/v2/benchmark_compare` 與 `GET /api/v2/health` 分別對應 F1–F6。需要 profile 的端點以 JSON 傳入 `profile`；模擬端點預設 `n_simulations=10000`，主分析內嵌的 v2 擴充則預設 1000 次以縮短互動等待時間。

---

## 11. v2 / v3 擴充分析

主分析 `/api/analyze` 預設會附帶以下結果；可用 `enable_v2=false` 關閉擴充計算：

- **F1 Monte Carlo**：以歷史日報酬進行 block bootstrap，輸出 P5/P10/P25/P50/P75/P90/P95、平均、標準差與年度 percentile bands。
- **F2 Sequence Risk**：逐年、逐日模擬退休提款，支援提款通膨、月年金、年金通膨與一次性支出，並輸出存活率、破產年齡與年齡存活曲線。
- **F3 VaR / CVaR**：歷史法計算 1 日、21 日、252 日的 95% / 99% 風險值。
- **F4 波動耗損**：比較 underlying、leveraged ETF 與季度再平衡策略。
- **F5 Benchmark**：支援 0050、006208 等 ETF 基準比較；資料不足的基準會 trim 或 skip，不會讓整體分析失敗。
- **F6 Sharpe with Rf**：預設以 1.5% 台灣 10 年期公債殖利率近似，可用 request 覆寫。

## 12. 目前版本的研究限制

本版本已包含 F1–F6，但仍有以下研究限制：

- 手續費
- 稅費
- 滑價
- 股利現金流的獨立拆解
- Point-in-Time 股票池
- 下市股票資料
- ETF 成分股歷史還原
- 股票分割與除權息資料品質驗證
- 交易再平衡成本（僅部分策略模型納入）
- 多幣別
- Bootstrap / Monte Carlo 的結果仍受歷史樣本、block size、seed 與分布假設影響
- 信賴區間與樣本不確定性校正
- 手續費、稅費與滑價不是所有歷史回測模式都會套用；請依報告中的模型說明解讀

因此輸出的未來 N 年結果應視為：

> **歷史情境參考，而非精準的未來價格預測。**

---

## 13. 建議的研究解讀方式

如果：

```text
P10 = 3%
P50 = 10%
P90 = 18%
```

不要解讀成：

> 未來一定介於 3%～18%。

正確解讀應為：

> 在目前歷史樣本中，具有相同 N 年長度的 rolling periods，其 CAGR 分布約落在這個範圍。

這個差異非常重要。

---

## 14. 建議的正式驗證流程

建議至少比較：

1. Common Period
2. Dynamic Entry
3. Full Available History

並比較：

- CAGR
- Total Return
- MDD
- Sharpe
- N-Year rolling CAGR distribution
- P10 / P25 / P50 / P75 / P90

如果不同方法得到的結論一致，結果可信度相對較高。

---

## 15. 專案定位

本工具應定位為：

**Portfolio Historical Backtest + Historical N-Year Outcome Scenario Tool**

而不是：

**Stock Price Prediction Engine**

核心目標是：

> 用歷史資料回答「這個投資組合在相同投資期間曾經發生什麼」，再將結果轉換成 N 年後的情境終值。

---

## 16. v3.0.2 改動摘要（2026-08-27）

### 15.1 回測 end_date 預設為「前一個月最後一天」

```
今天 = 2026-08-27  →  end_date 預設 = 2026-07-31
今天 = 2026-09-01  →  end_date 預設 = 2026-08-31
今天 = 2026-01-15  →  end_date 預設 = 2025-12-31   (1 月跨年)
```

**為什麼**：歷史回測不需要當下價格，月度更新資料即可。同一個月內多次執行 end_date 固定 → 0 抓取；跨月第一次執行 → 自動推進一格 → 補抓一個月 → merge。

**手動覆蓋**：`POST /api/analyze` body 帶 `end_date` 仍優先。

### 15.2 FinMind 快取改為「單一檔 per ticker」

| 屬性 | 舊（已移除） | 新（v3.0.2） |
|------|-------------|-------------|
| 檔名 | `daily_prices_{ticker}_{start}_{end}.parquet` | `{ticker}.json` |
| TTL | 無（靠檔名涵蓋）| 30 天 |
| N 變動影響 | 每次都 cache miss | 0 fetch（cache 涵蓋整段）|
| Partial hit | 不支援 | 自動算出缺段，只補抓那段 |
| 層級 | `lib/daily_prices.py`（死碼）| `lib/finmind.py` |

**回應衍生問題**：「cache 已抓 10 年，下次執行 N=5 還需要重新抓取嗎？」
**答：不需要。** Cache 已是單一檔 per ticker，內含 [2016-01-01, 2026-07-31] 完整範圍。改 N=5 只是把 start 從 2016 推到 2021，cache 涵蓋整段 → 0 fetch。

### 15.3 Windows Flask Log 集中

三個 log 通道：

| 檔案 | 等級 | 用途 |
|------|------|------|
| `logs/debug.log` | DEBUG+ | 全部 log（append）|
| `logs/app.log`   | ERROR+ | 主人快速看「今天炸了什麼」|
| console (stdout)| DEBUG | 開發用 |

**修法**：FileHandler 改掛 root logger（不再只掛 `portfolio_forecast`），`app.logger.error(...)` 也會進檔。

---

## 17. 已知限制

### 16.1 finmind query 拉整段而非只補缺

`lib/finmind.py` 的 partial hit 實作：cache 涵蓋 [2021-2024]，request 要 [2020-2024]，會呼叫 query(start=2020, end=2024) 拉整段，再 merge 進 cache。

更優化是只補 `[2020-01-01, 2020-12-31]` 這段（API 端也有 start 限制）。但 finmind API 對小範圍查詢 rate limit 沒差別，且 merge 邏輯已正確，目前不優化。

### 16.2 Cache 不區分 environment

同一個 `data/price_cache/` 目錄可能被多個 instance 共用。如果主人多開 Flask 實驗不同分支，且其中一個正在 partial hit 寫入，可能 race condition。目前 `FinMindClient` 用 `threading.Lock()` 保護單一 process 內的 cache 寫入，跨 process 未保護。低流量場景下（單主人單 Flask）不會遇到。

---

## 18. v3.0.3 改動摘要（2026-08-27）

**動機**：主人回饋「跑 kadela_stock.csv 時，6 個 ticker 找不到 (`holdings_weights 有 symbol 不在 prices`）」。根因：CSV 寫口語代號 (`50`, `2002`)，但 FinMind API 回傳的 column 是 canonical (`0050`, `02002`)，對不上。

### 17.1 Ticker 標準化管道

- **上傳時 gate**：`/api/upload_profile` 跑 `normalize_profile_csv`，對 FinMind match 寫回 canonical form
- **analyze 時 gate**（冪等）：`_fetch_daily_portfolio_returns` 與 `_run_analyze` 每次跑前 normalize
- **失敗語意**：任一 ticker 對不上 → 400 + `code=TICKER_NOT_FOUND` + `failed: [{line, ticker, reason}]`
- **前端 detail panel**：`showErr(msg, payload)` 收到 TICKER_NOT_FOUND 時動態渲染 detail list

### 17.2 Cache migration

```bash
# 1. 先看會動到哪些
python3 scripts/migrate_price_cache_to_canonical.py --dry-run

# 2. 確認後實跑(trash 舊 cache,讓 API 重抓)
python3 scripts/migrate_price_cache_to_canonical.py
```

### 17.3 範圍
- `lib/finmind.py` + `lib/csv_loader.py` + `app.py` + `static/js/portfolio.js` + `static/css/style.css`
- 新檔：`tests/test_upload_profile.py`、`tests/test_migrate_price_cache.py`、`scripts/migrate_price_cache_to_canonical.py`
- 既有 152 pytest 維持不退步，新加 46 個 regression test

---

## 19. Phase 6 驗收 checklist 對照表（2026-08-28）

主人針對 `/mnt/d/temp/checklist.txt` 13 條驗收項目逐項檢查，發現多項不符合。本節列出 Phase 6 5 個 commit 對應修復。

| # | Checklist 條目 | 修法 | Commit |
|---|----------------|------|--------|
| 1 | 歷史明細表僅包含 N 年資料 | `_get_monthly_tickers` 用 `data_max - N years` cutoff slice | 42ee0c0 |
| 2 | 明細表標註實際起訖、年數、N 參數 | template heading 加 `N=X 年 · 2010~2024 · 14.5 年` annotation | 42ee0c0 |
| 3 | 樣本有效性統計（有效/排除/最短最長持有年數） | `lib/forecast.py:rolling_sample_stats()` + template 明細表 heading | b6daab6 |
| 4 | 圖表 X 軸定義標註 | template rolling chart heading 加「X 軸 = 持有期間結束日」「不是時間序列」 | b6daab6 |
| 5 | F1 指標 P5/P10/P25/P50/P75/P90/P95/平均/標準差 | `_compute_summary` 加 p5/p25/p75/p95/std_final + template F1 表格 +6 列 | b6daab6 |
| 6 | 提款時點定義（年初/年末）固定 | template F2 heading 加「提款時點：年初」+ cashflow 順序說明 | 42ee0c0 |
| 7 | F2 最早破產年齡摘要 | `SequenceRiskResult` 加 `earliest_ruin_age` + `ruin_rate`，template F2 表格 +2 列 | b6daab6 |
| 8 | retirement_inputs header（current_age/retirement_age/end_age） | `_compute_v2_extensions` 回傳 dict + `_run_analyze` 單次呼叫 | 42ee0c0 |
| 9 | F1/F2 拆分視覺呈現 | card 五 heading 加「【雙軌模型】」+ F1 藍/F2 橘 badge | 2271d15 |
| 10 | 存活率曲線 vs 年齡 | 新 `lib/survival_chart.py` + SVG X軸=年齡/Y軸=存活率 | 2271d15 |
| 11 | MDD 詳細（Peak/Trough/Recovery Date + 回撤天數） | `lib/portfolio.py:_compute_mdd_detail` + template 獨立 card 六 | 2271d15 |
| 12 | 交易成本統一 3 位小數 | `fmt_pct(decimals=3)` + F2 文字統一 | 42ee0c0 |
| 13 | Pre-flight 6 條 model validation（§六 完整化） | `lib/model_validator.py` 加 6 條 check + `check_gt` helper | 876e95d |

**Tests**: 152 → 180 tests passed（+28 regression test 涵蓋 Phase 6 全部項目）
**Files changed**: 11 modified, 1 new (`lib/survival_chart.py`)
**Push**: `42ee0c0 → b6daab6 → 876e95d → 2271d15` 全 push 成功
