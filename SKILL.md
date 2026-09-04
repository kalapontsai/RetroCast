# RetroCast Agent Skill

本文件是 agent 在 clone RetroCast 後的操作規範。它描述目前版本的 API、資料流、檔案責任與安全邊界；歷史決策請查閱 `CHANGELOG.md`。

## 1. Clone 後檢查

```bash
git clone https://github.com/kalapontsai/RetroCast.git
cd RetroCast
python -m pip install -r requirements.txt
python -m py_compile app.py lib/*.py
pytest -q
```

先確認：

1. `app.py` 是否可 import。
2. `user_profile/` 是否有持倉 CSV。
3. `data/price_cache/` 與 `data/reports/` 是否可寫入。
4. `GET /api/health` 與 `GET /api/v2/health` 的結果。
5. 是否存在 FinMind token；沒有 token 時不可宣稱已完成遠端資料分析。

啟動：

```bash
python app.py
```

預設網址：`http://127.0.0.1:5000`。

## 2. API 操作順序

標準 agent workflow：

```text
/api/profiles
  → /api/profile/<name>
  → /api/analyze
  → /api/export
```

若要更新持倉，先使用 `/api/upload_profile`，不要直接覆寫使用者 CSV。

### Health

```http
GET /api/health
GET /api/v2/health
```

`/api/v2/health` 檢查 Monte Carlo、Sequence Risk、Risk Metrics、Volatility Decay、Benchmark 與 FinMind 依賴。

### Profiles

```http
GET /api/profiles
GET /api/profile/<name>
```

`name` 是 `user_profile/<name>.csv` 的 stem。所有外部輸入都必須保留 path traversal 防護。

### Analyze

```json
{
  "profile": "kadela",
  "n": 10,
  "enable_v2": true,
  "v2_n_simulations": 1000,
  "v2_current_age": 55,
  "v2_retirement_age": 60,
  "v2_retirement_end_age": 110,
  "v2_withdrawal_monthly": 30000,
  "v2_withdrawal_inflation": 0.03,
  "v2_pension_monthly": 0
}
```

```http
POST /api/analyze
Content-Type: application/json
```

回傳重點：

- `history`：One.5 個別完整歷史與 One.6 N-Year 分類。
- `common`、`dynamic`、`full`：三種回測結果。
- `forecast`：歷史 N-Year rolling outcome，不是未來逐年預測。
- `optimization`：Evidence、Correlation、Covariance、Portfolio Risk、Target Weight、交易與 sensitivity。
- `monte_carlo`：未來路徑分布。
- `sequence_risk`：退休提款、年齡、wealth percentiles、depletion probability。
- `risk_metrics`：VaR、CVaR 與 Sharpe with Rf。
- `validation`：模型驗證與資料品質結果。

### Export

將完整 `/api/analyze` response 原樣放入 `result`：

```json
{
  "profile_name": "kadela",
  "report_type": "forecast",
  "format": "html",
  "result": {"inputs": {}, "history": {}, "optimization": {}}
}
```

```http
POST /api/export
Content-Type: application/json
```

`report_type` 可為 `forecast` 或 `rebalance`。輸出位於 `data/reports/`；不要把空或手工拼接的 result 當成正式報告來源。

## 3. v2 API

| Endpoint | 必要輸入 | 用途 |
|---|---|---|
| `POST /api/v2/monte_carlo` | `profile`、`initial_balance`、`horizon_years` | Block bootstrap 未來財富分布 |
| `POST /api/v2/sequence_risk` | `profile`、`initial_balance`、提款與年齡設定 | 退休 sequence risk |
| `POST /api/v2/risk_metrics` | `profile`、可選 risk-free 設定 | VaR/CVaR 與 Sharpe |
| `POST /api/v2/volatility_decay` | underlying / leveraged ticker | 槓桿 ETF 波動耗損 |
| `POST /api/v2/benchmark_compare` | `profile`、`benchmarks` | 多基準比較 |
| `POST /api/v2/monthly_returns` | `profile` | 個別資產月報酬 |

Sequence Risk 的年齡規則：

```text
YearsFromNow = TargetAge - CurrentAge
```

例如 `CurrentAge=55` 時，60/65/70/80/90/100/110 分別是 5/10/15/25/35/45/55 年。只有明確指定 Age 110 終點時才允許退休模擬超過既有 50 年一般上限。

## 4. 資料與計算不變量

- 不得以 `history_years < N` 作為排除條件。
- 個別資產指標使用各自完整有效歷史；Portfolio risk 使用共同日報酬。
- Portfolio Volatility 必須來自 `sqrt(w.T @ Sigma @ w)`。
- Portfolio MDD 必須來自 portfolio equity curve 與 running peak。
- 缺失值使用 `NA` / warning，不得偷偷填 0 或平均值。
- `EvidenceFactor = 0.70 + 0.30 * EvidenceScore` 只能降低過度自信，不能抹除短歷史候選。
- 最佳化必須檢查 `N * min_weight <= 1` 與 `N * max_weight >= 1`。
- 交易表必須區分理論 Target Weight 與整股後 Actual Weight。
- 權重差異小於 1% 使用 `HOLD / NO TRADE`。
- Sharpe、Sortino、Calmar 是比率，不乘以 100；只有百分比欄位才使用百分比格式。
- 不得使用未來資料決定過去權重，不得把 Rolling CAGR 當成 Monte Carlo。

## 5. 修改程式的 agent 規範

1. 先以 `rg` 搜尋現有實作與測試，再做最小必要修改。
2. 不重寫既有 pipeline，不刪除既有 API 或報告章節。
3. 修改 Python 後執行 `py_compile` 與相關 pytest。
4. 修改模板後至少 render 一份 forecast 與 rebalance HTML。
5. 修改資料、模型或輸出格式時更新 `CHANGELOG.md`；不要把歷史紀錄搬回 README。
6. 不直接刪除 price cache、持倉 CSV 或報告；需要清理時先確認精確目標並採可恢復方式。
7. 不能取得可靠資料時回報 `NA`、`Not Available` 或 Data Quality Warning，不虛構數字。

## 6. 常見驗證命令

```bash
python -m py_compile app.py lib/*.py
pytest -q tests/test_portfolio_optimization.py tests/test_sequence_risk.py tests/test_risk_metrics.py
git diff --check
```

完整 pipeline 的最低驗證內容：

- `optimization.status == SUCCESS` 或有明確不可行原因。
- 權重總和接近 1，且每個權重通過上下限。
- Portfolio Volatility / MDD 不是個股風險加權。
- HTML 可離線開啟，且包含 Requested N、Actual Common Period、Evidence、交易成本與退休風險結果。
- CurrentAge=55 時，Age 60、65、70、80、90、100、110 的 Years From Now 正確。

## 7. 安全邊界

- 不把報告結果當成投資建議或保證。
- 不在未獲授權下交易、修改券商帳戶或傳送外部訊息。
- 不提交 secrets、FinMind token、私人持倉資料或大型 cache。
- API 輸入保持 JSON 型別驗證、檔名驗證與 path traversal 防護。
