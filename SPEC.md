# RetroCast — 退休決策 v2 / v3 — SPEC

> 規格基線：v1.0（2026-08-22） · 目前實作：v3.1.2（2026-09-01） · owner：股寶（分析）→ 二寶（實作）→ 股寶（驗收）
> 來源：股寶讀完 GPT 對 `portfolio_forecast_20260821_152502_d3e8eb5d-gpt.pdf` 的 26 頁分析，整理出 6 項建議，落地為本 SPEC
> 目標專案位置：`/mnt/d/stock/retrocast/`（clone 自 `stock_portfolio_forecast_flask/`，2026-08-26 改名 RetroCast）
> GitHub：`https://github.com/kalapontsai/RetroCast`

> **實作狀態（2026-09-02）**：本文件原先描述的 F1–F6 已整合至 Flask 主分析與 v2 API。Phase 6 的 13 項驗收修正、可調整退休條件與起始市值權重也已完成；本文件中的歷史規劃、測試案例與決策紀錄保留作為設計追溯，不代表尚未實作。

---

## 0. 為什麼做這版

股寶 2026-08-22 跑的 kadela_stock 10Y 回測（Common CAGR 10.52% / P10 Bear 6.95%），
GPT 在另一份 26 頁分析報告中批評「Bear 不像熊市 / 缺 Monte Carlo / 缺退休提款模擬 / 缺 VaR」。
股寶 + Kadela 同意：對 55 歲、準備退休的 Kadela 而言，**退休決策需要的不只是 CAGR，而是資產撐到 110 歲的機率**。

本 SPEC 把 GPT 6 項建議轉成可實作 features + 可驗收 criteria。

---

## 1. 範圍（Scope）

### 1.1 In-Scope（本版必做）

| 編號 | Feature | 優先 | 工時估 |
|---|---|---|---|
| F1 | Monte Carlo block bootstrap | 🔴 P0 | ✅ 已完成 |
| F2 | Sequence Risk 退休提款模擬 | 🔴 P0 | ✅ 已完成 |
| F3 | VaR / CVaR 95% / 99% | 🟡 P2 | ✅ 已完成 |
| F4 | 00631L 波動耗損獨立評估 | 🟢 P1 | ✅ 已完成 |
| F5 | 多 Benchmark 比較（0050 + 006208） | 🟢 P1 | ✅ 已完成 |
| F6 | Sharpe with Risk-Free Rate | 🟡 P2 | ✅ 已完成 |

### 1.2 Out-of-Scope（暫不做，留下版次）

- R&D 等級全套報告（30-40 頁、AI 持股建議） → v3
- 股利現金流獨立模組 → v3
- 2008 + 2022 重演壓力測試 → v3
- 個股集中度自動減碼建議 → v3

---

## 2. Features 細節

### F1. Monte Carlo 10,000 次模擬 🔴 P0

**目的**：以歷史日報酬的 mean / std / skew / kurt 為基礎，蒙地卡羅模擬 10,000 條未來軌跡，
給出「資產在 N 年後的分布」與「資產存活到 T 年的機率」。

**Inputs**：
```json
{
  "profile": "kadela_stock",
  "initial_balance": 7236096,        // NT$
  "horizon_years": 30,               // 預設 30（55 歲到 85 歲）
  "n_simulations": 10000,            // 預設 10,000
  "annual_withdrawal": 0,            // 預設 0（純成長）；F2 啟用時填月提款
  "withdrawal_inflation": 0.03,      // 3% 通膨調整
  "rebalance": "buy_and_hold",       // buy_and_hold / annual / quarterly
  "block_bootstrap": true,           // 用區塊 bootstrap 保留序列相關性（避免樣本獨立假設）
  "block_size_days": 21              // 區塊大小（月）
}
```

**Outputs**：
```json
{
  "summary": {
    "median_final": <NT$>,
    "p10_final": <NT$>,
    "p90_final": <NT$>,
    "mean_final": <NT$>,
    "prob_above_initial": 0.xx,
    "prob_zero_or_negative": 0.xx,
    "survival_to_horizon": 0.xx     // 資產 > 0 機率
  },
  "yearly_stats": [
    {"year": 1, "median": ..., "p10": ..., "p90": ...},
    ...
  ],
  "percentile_bands": [
    {"percentile": 5, "year": 1, "value": ...},
    ...
  ]
}
```

**Acceptance Criteria**：
- ✅ 重複執行同 inputs → 結果變動 < 0.5%（用 seed 控制）
- ✅ 跑 10,000 次 < 60 秒（單 thread，numpy vectorized）
- ✅ 邊界：initial_balance <= 0 或 horizon > 50 → 回 400
- ✅ 所有 NT$ 數字四捨五入到整數
- ✅ 報告含 P5/P25/P50/P75/P95 五條 percentile band（圖）

**Test Cases**：
- T1.1：以 kadela_stock（Common 11.81y 歷史）跑 n=10,000、horizon=10 → median_final 應落在 NT$ 14-18M（對應 CAGR ~7-10%）
- T1.2：block_bootstrap=False vs True → 結果不應完全相同（True 保留序列結構）
- T1.3：horizon_years=50、n_simulations=10000 → 完成時間 < 60s

**依賴**：numpy / pandas（已裝）

---

### F2. Sequence Risk 退休提款模擬 🔴 P0

**目的**：證明「同 CAGR、不同起點 → 結果差很大」。
模擬退休時每月提領 NT$ X（依通膨調整），給出 25 年的存活率。

**Inputs**：
```json
{
  "profile": "kadela_stock",
  "initial_balance": 7236096,
  "retirement_age": 60,
  "withdrawal_monthly": 30000,       // NT$ 30K/月（基本生活費）
  "withdrawal_inflation": 0.03,
  "n_simulations": 10000,
  "horizon_years": 30,               // 60→90 歲
  "block_bootstrap": true
}
```

**Outputs**：
```json
{
  "survival_rate": 0.xx,             // 資產 > 0 機率
  "median_final_balance": <NT$>,
  "ruin_age_distribution": [60, 62, 75, ...],   // 破產年齡分布
  "scenario_examples": [
    {"year": 1, "balance_p50": ..., "withdrawal": ...},
    ...
  ],
  "success_rate_by_age": {           // 各年齡還活著且有錢的機率
    "70": 0.xx,
    "75": 0.xx,
    "80": 0.xx,
    "85": 0.xx,
    "90": 0.xx
  }
}
```

**Acceptance Criteria**：
- ✅ 跑 10,000 次 < 90 秒
- ✅ 月提款轉年提款後，與手算驗證誤差 < 1%
- ✅ 通膨調整後月提款逐年增加
- ✅ 提款 > 資產時，該路徑立即標記 ruin

**Test Cases**：
- T2.1：withdrawal=30K/月、horizon=25 → 對 **kadela_stock** 應有 > 70% 存活率；fixture 下 > 0.0(sanity, 2026-08-24 Kadela 拍板,詳 CHANGELOG v2.1.1)
- T2.2：withdrawal=80K/月、horizon=25 → 存活率應掉到 < 60%
- T2.3：withdrawal=0 → 應等同 F1（純成長模擬）
- T2.4：withdrawal=200K/月、horizon=25、inflation=3% → 極端提款壓力下存活率應 < 0.5
  （驗證程式在高提款壓力下行為正確,_fixture 期望 < 0.5,真實 portfolio 數字可能更高,
   重點在公式對而非數字貼近現實 — 2026-08-23 Kadela 決策 F）

> **🧪 2026-08-23 規格微調 v2.1.0 — Cross-Validation 對照測試（F 路線）**：
> 主人 11:40 拍板「優先驗證程式/公式是否寫對」,新增 3 個 deterministic fixture
> 對照代數解,直接驗證公式正確性（不依賴 fixture 期望）:
>
> | ID | 測試 | 代數解 | 容差 | 結果 |
> |---|---|---|---|---|
> | CV1 | F1 + 0 vol + 已知 drift | `initial × (1+daily_drift)^(252×years)` | < 1e-6 | ✅ 綠(F1 公式寫對) |
> | CV2 | F2 + 0 vol + 0 drift + 固定提款 | `initial - years×12×monthly` | < 1% | 🚨 **紅(偏 31.5%)** |
> | CV3 | F2 + 提款 > initial | survival = 0 | exact | 🚨 **紅(survival 1.0)** |
>
> **🔴 F2 withdrawal 公式 bug（2026-08-23 CV2 reproducer）**:
> - 症狀:100M 起始 + 200K/月×10y → 預期扣 24M,實際只扣 9.5K (per_day × 1 cell)
> - 根因:`_apply_withdrawals_and_track` 每個 cell 只被扣一次 `per_day`,
>   而非 `w_y`(全年提款總額) — 程式邏輯把「一年的提款」分散到 252 cells,
>   但每 cell 只減一次導致整 horizon 只減一天的提款金額
> - 影響:T1.1 F1 OK、F2 全線結果失真(包括 T2.1/T2.2/T2.4 fixture 數字不可信)
> - 修法建議:把 `nav[:, start:end] -= per_day` 改為在 year 起始扣整年提款
>   （`nav[:, start] -= w_y` 或更精確的每月月底扣 `monthly × (1+infl)^m`）
> - 決策者:Kadela 11:40,工程派工給二寶修

**依賴**：F1（共用模擬引擎）+ F2 withdrawal 公式修正

> **📝 2026-08-23 規格微調**：T2.2 期望從 `< 50%` 放寬到 `< 60%`。
> 理由：80K/月 × 25y 通膨提款屬「相對溫和」（首年提領率 960K/7.24M = 13.3%），
> 在台股歷史 40% 波動、2.5% drift 假設下實測存活率 **0.5574**（age 85），
> 與 `< 50%` 閾值差距 5.74pp，閾值過嚴。
> 替代方案（未來可另開 T2.4）：
> 1. block bootstrap 改用「2000-2008」歷史區間（熊市偏誤 bootstrap）
> 2. 或假設 drift = 1% 模擬長期停滯情境
> 3. 或混 2000/2008 真實跌市進抽樣池
> 決策者：Kadela，2026-08-23 11:02 Asia/Taipei。

**依賴**：F1（共用模擬引擎）

---

### F3. VaR / CVaR 95% / 99% 🟡 P2

**目的**：在 1 個月 / 1 年的持有期下，給出最大可能損失的統計量。

**Inputs**：
```json
{
  "profile": "kadela_stock",
  "confidence_levels": [0.95, 0.99],
  "horizon_days": [1, 21, 252]      // 日 / 月 / 年
}
```

**Outputs**：
```json
{
  "var_1d_95": -0.0234,             // 1 日 95% VaR（負 = 損失）
  "var_1d_99": -0.0389,
  "cvar_1d_95": -0.0312,            // 1 日 95% CVaR（條件風險值，超過 VaR 部分的平均）
  "var_21d_95": -0.0845,
  "cvar_21d_99": -0.1421,
  "var_252d_95": -0.2103,
  "method": "historical"            // historical / parametric（先做 historical）
}
```

**Acceptance Criteria**：
- ✅ 歷史法（直接取日報酬 percentile）
- ✅ CVaR 用條件平均（超過 VaR 的部分平均）
- ✅ 多 horizon（1d / 21d / 252d）平行計算

**Test Cases**：
- T3.1：kadela_stock 1d 95% VaR 應為負、絕對值約 1-2%（依歷史波動）
- T3.2：cvar_95 < var_95（CVaR 永遠 ≥ VaR 絕對值）

---

### F4. 00631L 波動耗損獨立評估 🟢 P1

**目的**：模擬「0050 持有 10 年」vs「0050正2 持有 10 年」vs「0050 + 0050正2 各半」三條長期軌跡，
量化槓桿 ETF 在反覆震盪下的實際損耗。

**Inputs**：
```json
{
  "ticker_underlying": "0050",
  "ticker_leveraged": "00631L",
  "initial_date": "2014-10-31",     // 00631L 上市日
  "initial_balance": 348400,          // 您現有 00631L 市值
  "compare_strategies": [
    "all_underlying",                // 100% 0050
    "all_leveraged",                 // 100% 00631L
    "50_50_rebalance_quarterly"      // 50/50 季度再平衡
  ]
}
```

**Outputs**：
```json
{
  "strategies": {
    "all_underlying": {"final": ..., "cagr": ..., "mdd": ...},
    "all_leveraged": {"final": ..., "cagr": ..., "mdd": ..., "decay_loss": ...},
    "50_50_rebalance_quarterly": {"final": ..., "cagr": ..., "mdd": ...}
  },
  "decay_analysis": {
    "theory": "0050 +10% 然後 -10% → 0050正2 應是 +20%/-20% 但因 daily rebalance 損耗，淨損 ~4%",
    "actual_decay_pct": -0.04,
    "recommendation": "保留 vs 轉 0050 評估..."
  }
}
```

**Acceptance Criteria**：
- ✅ 用 FinMind TaiwanStockPrice 取 0050 與 00631L 上市以來日 K
- ✅ 三策略對齊同起始日同初始資金
- ✅ 含手續費與稅假設（0.1425% + 0.3% 證交稅）
- ✅ decay 量化：實際年化 vs 理論年化（0050 兩倍）的差距

**Test Cases**：
- T4.1：0050 2014-10 ~ 2026-08（~12 年）應與已知 ~23% CAGR 接近
- T4.2：all_leveraged CAGR 應 < (1 + 0050_CAGR)^2 - 1（因 daily rebalance 損耗）
- T4.3：50_50 再平衡 vs all_leveraged → MDD 應顯著降低

---

### F5. 多 Benchmark 比較 🟢 P1

**目的**：同時對標 0050、006208 兩檔市值型 ETF 作為「大盤代理基準」，
讓使用者看到自組 portfolio 在「原型 ETF」vs「高股息」下的相對位置。

**為何不用 ^TWII 加權指數**: FinMind v3.0.2 為止沒提供 TAIEX 日價 stock-compatible API
(沒 `TaiwanStockPrice data_id=TAIEX`,也沒 `TaiwanIndices` 這 dataset 名)。
原來的 ^TWII 預設在 2026-08-27 移除。
使用者手動可加其他「含 TAIEX」 ETF(如 006208、0050) 作為市場代理。

**Inputs**：
```json
{
  "profile": "kadela_stock",
  "benchmarks": ["0050", "006208"],
  "n_years": 10
}
```

**Outputs**：
```json
{
  "benchmarks": {
    "0050":    {"cagr": ..., "sharpe": ..., "mdd": ...},
    "006208":  {"cagr": ..., "sharpe": ..., "mdd": ...}
  },
  "vs_kadela": {
    "alpha_vs_0050": <%>,
    "alpha_vs_006208": <%>
  }
}
```

**Acceptance Criteria**：
- ✅ 每個 benchmark 獨立計算 metrics
- ✅ 若 benchmark 資料不足（如 006208 在 2017-09-12 前是 phantom data），自動 trim
- ✅ 若 benchmark 在 FinMind 抓不到 → 進 `skipped`,不 break 整體 analyze
- ✅ 報告含疊圖（kadela vs 2 benchmarks NAV 曲線）

**Test Cases**：
- T5.1：006208 2014-01-01 應自動 trim 到 2017-09-12 起（已知 phantom data）
- T5.2：(已取消) 原本驗證 ^TWII 2014-2026 應可取得 — v3.0.2 拿掉
- T5.3：alpha 計算 = kadela_CAGR - benchmark_CAGR

---

### F6. Sharpe with Risk-Free Rate 🟡 P2

**目的**：讓 Sharpe 可比較（扣無風險利率）。
預設用台灣 10 年期公債殖利率（年化 1.5%），
可在 request 覆寫。

**Inputs**：
```json
{
  "profile": "kadela_stock",
  "risk_free_rate": 0.015,           // 預設 1.5%（台灣 10Y 公債近似）
  "risk_free_source": "tw_10y_bond"  // tw_10y_bond / custom
}
```

**Outputs**：
```json
{
  "sharpe_with_rf": 0.65,            // 現有 0.77 扣 1.5% 後
  "sharpe_rf_0": 0.77,               // 對照（rf=0）
  "rf_used": 0.015,
  "rf_source": "tw_10y_bond（手動輸入，可從 FinMind TaiwanGovernmentBondYield 取）"
}
```

**Acceptance Criteria**：
- ✅ 預設用 1.5% 但允許 custom override
- ✅ 報告明確標示 rf 值與來源
- ✅ Sharpe with rf 永遠 ≤ Sharpe rf=0

**Test Cases**：
- T6.1：rf=0.015 應比 rf=0 結果低
- T6.2：custom rf=0.05 應比 rf=0.015 結果更低

---

## 3. 檔案結構（目前）

```
retrocast/
├── app.py                       # Flask UI、v1/v2 API
├── app_config.py                # 修改：新增 config
├── requirements.txt             # 不變
├── README.md                    # 使用說明與研究限制
├── SPEC.md                      # 本檔
├── CHANGELOG.md                 # 版本變更紀錄
│
├── lib/
│   ├── __init__.py              # 不變
│   ├── csv_loader.py            # 不變
│   ├── exporter.py              # 修改：支援 v2 新 reports
│   ├── finmind.py               # 修改：cache hotfix + F1/F2/F3/F6 logging (v3.0.2)
│   ├── forecast.py              # 沿用（v1 報告）
│   ├── i18n.py                  # 不變
│   ├── portfolio.py             # 不變
│   ├── monte_carlo.py           # ★ 新增（F1 + F2 共用引擎）
│   ├── sequence_risk.py         # ★ 新增（F2）
│   ├── risk_metrics.py          # ★ 新增（F3 + F6）
│   ├── benchmarks.py            # ★ 新增（F5）
│   └── volatility_decay.py      # ★ 新增（F4）
│
├── user_profile/                # 不變（沿用 v1 的 kadela_stock.csv 等）
│
├── tests/
│   ├── test_csv_loader.py       # 不變
│   ├── test_exporter.py         # 不變
│   ├── test_forecast.py         # 不變
│   ├── test_portfolio.py        # 不變
│   ├── test_portfolio_extras.py # 不變
│   ├── test_monte_carlo.py      # ★ 新增
│   ├── test_sequence_risk.py    # ★ 新增
│   ├── test_risk_metrics.py     # ★ 新增
│   ├── test_benchmarks.py       # ★ 新增
│   ├── test_volatility_decay.py # ★ 新增
│   └── test_integration_v2.py   # ★ 新增（end-to-end Flask 測試）
│
├── templates/                   # 分析與再平衡報告
├── static/                      # 不變
└── scripts/                     # cache migration、驗證與啟動工具
```

---

## 4. 新增 API Endpoints

| Method | Path | 功能 | 對應 Feature |
|---|---|---|---|
| POST | `/api/v2/monte_carlo` | 跑 10,000 次模擬 | F1 |
| POST | `/api/v2/sequence_risk` | 退休提款存活率 | F2 |
| POST | `/api/v2/risk_metrics` | VaR / CVaR | F3 + F6 |
| POST | `/api/v2/volatility_decay` | 槓桿 ETF 損耗 | F4 |
| POST | `/api/v2/benchmark_compare` | 多基準對比 | F5 |
| GET | `/api/v2/health` | v2 健康檢查（依賴檢查） | — |

**舊 v1 endpoints 全部保留**（向後相容）。

目前另外提供：`GET /api/health`、`GET /api/profiles`、`GET /api/profile/<name>`、`POST /api/upload_profile`、`POST /api/export`、`POST /api/v2/monthly_returns`。`POST /api/analyze` 會回傳 v1 結果及 F1/F2/F3/F6；F4/F5 由各自的 v2 endpoint 執行。

---

## 5. 驗收流程（Verification Process）

由股寶（agent-stock）逐項驗收：

### 5.1 程式碼驗收

```bash
cd /mnt/d/stock/retrocast

# 1. 所有測試必須綠
pytest tests/ -v

# 2. coverage 應 >= 80% on 新模組
pytest tests/ --cov=lib --cov-report=term

# 3. lint（PEP 8 + type hints）
flake8 lib/ app.py --max-line-length=100
mypy lib/ --ignore-missing-imports

# 4. 啟動 Flask
python app.py
# 確認 /api/v2/health 回 200
curl http://127.0.0.1:5000/api/v2/health
```

### 5.2 業務驗收（股寶跑實際情境）

每個 Feature 用 kadela_stock 真實數據跑一次，確認：

- **F1**：n=10,000、horizon=10、initial=7.24M → median_final 落在 [NT$ 14M, NT$ 18M]
- **F2**：30K/月 × 25 年 → 存活率 > 70%
- **F3**：1d 95% VaR 應為負、絕對值 < 5%
- **F4**：all_leveraged CAGR < 2 × 0050_CAGR（確認有 decay）
- **F5**：0050 + 006208 兩基準都能跑出 CAGR (v3.0.2 起 ^TWII 拿掉,FinMind 無 TAIEX 支援)
- **F6**：Sharpe with rf=1.5% < Sharpe with rf=0

### 5.3 報告驗收

跑一個 end-to-end demo，產出 v2 退休決策報告（含 SVG / Chart.js），
股寶開啟後確認：
- ✅ 圖表正確
- ✅ 數字與 F1-F6 結果一致
- ✅ 中文排版沒掉字
- ✅ 報告可在瀏覽器單獨開啟（離線）

---

## 6. 紅線（Red Lines）

- ❌ 不寫「該買」「該賣」字眼（沿用 v1 規範）
- ❌ 不混 FinMind 與 yfinance 資料（006208 / 0050 baseline 已用 yfinance cache 的不動，新功能用 FinMind）
- ❌ 不刪除 v1 endpoints（向後相容）
- ❌ 不直接覆寫交易紀錄 / 持股 CSV
- ❌ 任何含 PII 的 log 一律先過 redact_pii.sh

---

## 7. 歷史時程（已完成）

> **⏰ 變更紀錄（2026-08-22 15:03 Kadela 拍板）**：原本 4 天 plan 改為 5hr blocks。理由：模型每 5hr 重設 limit，跨太久會丟上下文。每個 block 結束前必須有可驗收交付物 + 股寶驗收 + 進度回報給 Kadela。

| Block | 時間 | Step | 交付物 |
|---|---|---|---|
| **B1** | 15:00 - 20:00 (08-22) | F1 + F2 | Monte Carlo 引擎 + Sequence Risk + 單元測試；kadela_stock 跑 10,000 次 < 60s；T1/T2 test cases 綠 |
| **B2** | 20:00 - 01:00 (08-23) | F5 + F4 | 多基準比較（0050 + 006208）+ 00631L 波動耗損對照；T5/T4 test cases 綠 (v3.0.2 起 ^TWII 拿掉) |
| **B3** | 01:00 - 06:00 (08-23) | F3 + F6 | VaR/CVaR（95/99）× 多 horizon + Sharpe with Rf；T3/T6 test cases 綠 |
| **B4** | 06:00 - 11:00 (08-23) | 整合 | Flask 6 個 v2 routes + reports 樣板 + end-to-end demo；產出第一份 v2 HTML 報告 |
| **B5** | 11:00 - 16:00 (08-23) | 修整 + 全驗收 | 股寶逐項驗收 F1-F6 → 全部通過 → 正式退休決策報告 |

### 每個 Block SOP

1. **開工前**：二寶讀 thread + SPEC + 上次進度（從 memory/2026-08-22.md 看）
2. **過程中**：每完成一個 feature → append thread section（frontmatter 更新 last_actor/last_action_at/status=awaiting-acceptance）
3. **Block 結束前 30 分鐘**：二寶 push 「可驗收」通知到 thread（附執行 log + 測試結果）
4. **股寶立即驗收**：跑對應 T1-T6 test cases，用 kadela_stock 真實數據對照 → thread append 驗收結果
5. **回報 Kadela**：股寶 push Telegram 簡訊「Block N 完成：F1 ✅ / F2 ✅ / 等」
6. **進入下一個 Block**：股寶重新觸發二寶（或二寶自己看到 thread append 自動接）

### Block 邊界策略

- 如果某 Block 提前完成 → 立馬接下一個 Block（不卡時間）
- 如果某 Block 超時 → Kadela 拍板決定：跳過 P2 / 拆解任務 / 延後到下個 5hr cycle
- **關鍵**：每個 Block 結束前必須有「可獨立運作的 code commit」→ 這樣下次 session 重啟不會全丟

### 第一個檢查點
**B1 結束前（20:00 前）**：F1 跑完先告訴股寶（即使其他未完成），股寶會先用 kadela_stock 跑 10,000 次驗證數字合理性。

---

## 8. 目前實作補充

### 8.1 權重決策

若沒有提供 `weights`：

1. 有 `shares` 時，使用每支股票「最後一個有效日 raw close × 股數」所得的起始市值權重。
2. 沒有 `shares` 時，為向後相容使用等權重 fallback。

同一組有效權重會供 UI、主分析與 HTML 報告使用，並以 `effective_weights`、`weights_source` 回傳。

### 8.2 退休模型輸入

F2 支援 `current_age`、`retirement_age`、`retirement_end_age`、`v2_n_simulations`、月提款、提款通膨、月年金、年金通膨與一次性支出。退休 horizon 與未來 N 年 forecast horizon 分開計算；資產歸零後不會重新恢復。

### 8.3 驗收基線

- Phase 6 checklist：13/13 項完成。
- 測試涵蓋 F1–F6、CSV/ticker 標準化、cache migration、報告匯出與 v2 整合。
- 執行驗證：`pytest tests/ -q`；需要 `data/price_cache` 或 FinMind 可用時，整合測試才可重現完整結果。

## 9. 變更紀錄（CHANGELOG）

| 日期 | 版本 | 變更 |
|---|---|---|
| 2026-08-22 | v1.0 | 初版立約（股寶） |

---

*股寶 · 2026-08-22 14:56 Asia/Taipei · 立約*
