#!/usr/bin/env bash
# 一鍵 deploy + pre-flight + repro 整合腳本
# 主人 2026-08-31 13:53 SOP 自動化：
#   1. repo → /mnt/d/stock/retrocast 同步
#   2. 清 pycache (Windows + WSL 兩端)
#   3. 跑 6 個 repro
#   4. 跑 pre-flight (黃金逐檔法)

set -e

REPO="${HOME}/.openclaw/workspace-two/repos/retrocast"
WEB="/mnt/d/stock/retrocast"

echo "========================================"
echo "🚀 deploy_and_verify.sh"
echo "  repo: $REPO"
echo "  web:  $WEB"
echo "========================================"
echo

# 1) 同步
echo "📁 [1/4] 同步 repo → web root..."
for f in \
    lib/portfolio.py \
    lib/finmind.py \
    app.py \
    templates/report.html
do
    if [ -f "$REPO/$f" ]; then
        cp "$REPO/$f" "$WEB/$f"
        echo "  ✓ $f"
    fi
done

# 同步所有 repro / pre-flight 腳本
echo "  ...同步 scripts/"
mkdir -p "$WEB/scripts"
for f in "$REPO"/scripts/*.py; do
    [ -f "$f" ] && cp "$f" "$WEB/scripts/$(basename $f)"
done

echo

# 2) 清 pycache
echo "🧹 [2/4] 清 pycache..."
find "$WEB" -name "*.pyc" -delete 2>/dev/null || true
find "$WEB" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
echo "  ✓ 清乾淨"

echo

# 3) 跑 6 個 repro
echo "🧪 [3/4] 跑 6 個 repro..."
cd "$WEB"
REPROS=(
    repro_common_mode_cross_listing
    repro_per_stock_history
    repro_zero_sentinel_filter
    repro_dividend_split_adjustment
    repro_per_stock_n_year
    repro_fund_v3_total_return
    repro_mdd_detail_uses_full_mode
)
for s in "${REPROS[@]}"; do
    echo "  → $s"
    python3 scripts/$s.py 2>&1 | grep -E "^OK|^ERROR|^Assertion|通過|FAIL" | head -6
done

echo

# 4) Pre-flight (黃金逐檔法)
echo "🛫 [4/4] Pre-flight Check (主人 13:47 黃金逐檔法)..."
echo "  → fund profile (預設)"
python3 scripts/preflight_total_return.py fund 2>&1 | grep -E "✅|❌|PASS|FAIL" | tail -7
echo
echo "  → kadela_stock profile"
python3 scripts/preflight_total_return.py kadela_stock 2>&1 | grep -E "✅|❌|PASS|FAIL" | tail -10

echo
echo "========================================"
echo "✅ deploy + verify 全部完成"
echo ""
echo "⚠️  記得：Windows 端 Flask 必須手動重啟才會生效！"
echo "    (debug=False 不會自動 reload)"
echo "========================================"
