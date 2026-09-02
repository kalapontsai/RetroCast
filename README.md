# RetroCast

RetroCast 是以 Flask、Pandas 與 NumPy 建立的投資組合歷史分析與退休決策工具。它將目前持倉依序轉換為：

```text
Asset History → Portfolio Backtest → Portfolio Risk → Optimization
→ Rebalancing → Rolling Outcomes → Monte Carlo → Sequence Risk
→ Retirement Sustainability
```

本專案提供歷史情境分析，不是股價預測器，也不保證未來報酬。閱讀報告時，必須同時注意資料期間、資料品質、交易成本、敏感度與 Survivorship Bias。

## 功能

### 歷史資料與回測

- 從 FinMind 取得台股／ETF 歷史價格，使用本地 cache 降低重複請求。
- 使用 raw close 搭配股利與分割資料建立 total-return adjusted close。
- 支援 `common`、`dynamic`、`full` 三種歷史回測模式。
- One.5 使用每個資產自己的完整可用歷史，不因歷史少於 10 年自動排除。
- One.6 將資產分類為 `Full N-Year`、`Partial N-Year`、`Short History`，並顯示 Requested N 與 Actual Common Period。
- 個別資產提供 History Start、History End、History Years、Data Points、CAGR、Volatility、MDD、Sharpe、Sortino、Calmar。

### Portfolio-level risk

- 使用共同日報酬建立 Correlation Matrix 與 Covariance Matrix。
- Portfolio Volatility 使用 `sqrt(w.T @ covariance @ w)`。
- Portfolio MDD 使用每日 equity curve 與 running peak，不使用個股 MDD 加權。
- Portfolio Sharpe、Sortino、Calmar、VaR、CVaR 均使用組合日報酬計算。
- 報告包含 equity curve、drawdown、相關性、集中度與前後比較。

### Evidence-aware optimization

每個資產會計算：

```text
HistoryLengthScore
MarketRegimeCoverage
DrawdownEvidence
ObservationScore
EvidenceScore
EvidenceFactor = 0.70 + 0.30 * EvidenceScore
AdjustedScore = RawScore * EvidenceFactor
```

短歷史資產仍保留在候選池；若報酬與證據分數足夠，會標記為 `Emerging Quality Candidate`，而不是直接刪除。

最佳化同時考慮報酬、Sharpe、風險、MDD、Tracking Penalty、Concentration Penalty、Covariance risk penalty 與 Transaction Cost Penalty。預設單一資產權重限制為 `2%–15%`；數學上不可行時會回報原因，不產生虛假配置。

### Rebalancing

- 顯示 Current Weight、Target Weight、Weight Difference、Current Value、Target Value、Trade Value。
- 依整股計算 Target Shares、Actual Value、Actual Weight 與 Cash Residual。
- 權重差異小於 `1%` 標記為 `HOLD / NO TRADE`。
- 支援 commission、slippage、sell tax，且交易成本會進入最佳化目標。
- 提供 Conservative、Balanced、Growth sensitivity 與 `Optimization Sensitivity High` 警示。

### 退休分析

- Monte Carlo：以歷史日報酬 block bootstrap 模擬未來路徑。
- Sequence Risk：逐日模擬年初提款、通膨、退休金與一次性支出；歸零路徑不會復活。
- `CurrentAge` 與 `retirement_age` 分開處理，`YearsFromNow = TargetAge - CurrentAge`。
- 可分析 Age 70、80、90、100、110 的 depletion probability 與 P10/P25/P50/P75/P90 wealth。
- 資料不足的 Walk-forward、Point-in-Time 或下市資產分析會標示不可用，不虛構結果。

## 專案結構

```text
RetroCast/
├── app.py                         # Flask API 與主分析 pipeline
├── app_config.py                  # 路徑與預設設定
├── lib/
│   ├── portfolio.py               # 回測、NAV、個股歷史
│   ├── portfolio_optimization.py  # Evidence、Portfolio Risk、最佳化、再平衡
│   ├── monte_carlo.py             # F1 Monte Carlo
│   ├── sequence_risk.py           # F2 退休提款與 sequence risk
│   ├── risk_metrics.py            # F3 VaR/CVaR 與 F6 Sharpe with Rf
│   ├── volatility_decay.py        # F4 槓桿 ETF 波動耗損
│   ├── benchmarks.py              # F5 基準比較
│   ├── finmind.py                 # FinMind client 與 cache
│   └── exporter.py                # HTML / SVG 報告
├── templates/                    # 主分析與再平衡 HTML
├── static/                       # JavaScript / CSS
├── user_profile/                 # 持倉 CSV
├── data/price_cache/              # 本地價格 cache
├── data/reports/                 # HTML 報告輸出
├── tests/                        # 單元與整合測試
├── SKILL.md                      # agent clone 後的操作指引
└── CHANGELOG.md                  # 完整歷史變更紀錄
```

## 安裝與啟動

需要 Python 3.10 或更新版本。

```bash
git clone https://github.com/kalapontsai/RetroCast.git
cd RetroCast
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

開啟 `http://127.0.0.1:5000`。FinMind token 依 `lib/finmind.py` 的既有設定方式提供；沒有 token 時，離線單元測試仍可執行，但遠端資料分析會回報資料錯誤。

## 持倉 CSV

`user_profile/kadela.csv` 對應 API 的 `"profile": "kadela"`。最小格式：

```csv
ticker,shares
2330,1000
0050,8000
00631L,10000
```

上傳 API 會驗證並標準化 ticker。未知代號不會寫入正式 profile，並回傳 `TICKER_NOT_FOUND` 與失敗明細。

## API

### 基本 API

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/health` | 基本健康檢查 |
| GET | `/api/profiles` | 列出 profile |
| GET | `/api/profile/<name>` | 預覽持倉 |
| POST | `/api/upload_profile` | 上傳、驗證、標準化 CSV |
| POST | `/api/analyze` | 完整分析與最佳化 |
| POST | `/api/export` | 匯出 forecast 或 rebalance HTML |
| POST | `/api/v2/monthly_returns` | 個別資產月報酬表 |

### 主分析

```bash
curl -X POST http://127.0.0.1:5000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"profile":"kadela","n":10,"enable_v2":true,"v2_n_simulations":1000,"v2_current_age":55,"v2_retirement_age":60,"v2_retirement_end_age":110}'
```

常用欄位：`profile` 必填；`n` 為 Rolling / Forecast 年數；`pv` 未提供時取持倉最後有效 raw close × shares；`weights` 可傳 dict 或 `2330:0.4,0050:0.6` 字串；`start_date`、`end_date` 可覆寫資料範圍；`fee_buy`、`fee_sell`、`tax_sell`、`slippage` 為交易成本率；`enable_v2=false` 可關閉嵌入式 v2；`v2_current_age`、`v2_retirement_age`、`v2_retirement_end_age` 控制退休年齡模型。

主要回傳欄位包括 `inputs`、`history`、`common`、`dynamic`、`full`、`forecast`、`optimization`、`monte_carlo`、`sequence_risk`、`risk_metrics` 與 `validation`。

### v2 API

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/v2/health` | F1–F6 依賴檢查 |
| POST | `/api/v2/monte_carlo` | 未來路徑與財富分布 |
| POST | `/api/v2/sequence_risk` | 退休提款與資產耗盡機率 |
| POST | `/api/v2/risk_metrics` | VaR、CVaR、Sharpe with Rf |
| POST | `/api/v2/volatility_decay` | underlying、leveraged、再平衡策略比較 |
| POST | `/api/v2/benchmark_compare` | 0050、006208 等基準比較 |

除 `/api/v2/health` 外，v2 分析端點通常需要 JSON `profile`。各 endpoint 的欄位以 `app.py` route 與對應 `lib/` dataclass 為準。

### 匯出 HTML

先取得 `/api/analyze` JSON，再把完整結果作為 `result` 傳給 `/api/export`：

```bash
curl -X POST http://127.0.0.1:5000/api/export \
  -H "Content-Type: application/json" \
  -d '{"profile_name":"kadela","report_type":"forecast","format":"html","result":{}}'
```

實際使用時，將 `{}` 換成完整分析結果。輸出位於 `data/reports/`，可直接離線開啟。

## 驗證

```bash
python -m py_compile app.py lib/*.py
pytest -q
```

若 Windows pytest 暫存目錄沒有掃描權限，整合測試可能在 fixture setup 階段失敗；請先修正 `TEMP` / `TMP` 權限再判讀結果。

## 研究限制與開發原則

- 目前 profile 可能只包含仍存在的資產，因此歷史結果存在 Survivorship Bias。
- 非 Point-in-Time 持倉會帶來 hindsight bias；不可用的資料不得虛構。
- Monte Carlo 與 Sequence Risk 受歷史樣本、block size、seed、通膨與提款假設影響。
- 最佳化解不是唯一答案；應閱讀 sensitivity、Evidence 與 Transaction Cost，不只看 CAGR。
- P10/P50/P90 是歷史或模擬情境分布，不是未來保證，也不構成投資建議。
- 保留既有 API 與報告相容性；歷史與設計決策寫入 `CHANGELOG.md`，本 README 只描述目前版本。
