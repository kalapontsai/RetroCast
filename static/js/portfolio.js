/* Portfolio Forecast — 前端邏輯 */
(function () {
  'use strict';

  // ────────── 工具 ──────────
  const $ = (id) => document.getElementById(id);

  // null-safe textContent setter (v3.0.2 加固)
  // 避免某個 id 不存在 → 'Cannot set properties of null' 拖垮整個 renderAll
  const setText = (id, val) => {
    const el = $(id);
    if (el) el.textContent = val;
  };
  const setHTML = (id, val) => {
    const el = $(id);
    if (el) el.innerHTML = val;
  };
  const fmtPct = (x) => {
    if (x == null || (typeof x === 'number' && isNaN(x))) return '—';
    return (x * 100).toFixed(2) + '%';
  };
  const fmtMoney = (x) => {
    if (x == null || (typeof x === 'number' && isNaN(x))) return '—';
    return Number(x).toLocaleString('zh-TW', { maximumFractionDigits: 0 });
  };
  const fmtFloat = (x, d = 3) => {
    if (x == null || (typeof x === 'number' && isNaN(x))) return '—';
    return Number(x).toFixed(d);
  };

  const parseSpecialExpenses = (value) => String(value || '').split(',')
    .map((part) => part.trim()).filter(Boolean).map((part) => {
      const [offset, amount] = part.split(':').map((v) => Number(v.trim()));
      if (!Number.isFinite(offset) || !Number.isFinite(amount) || offset < 0 || amount <= 0) return null;
      return { year_offset: Math.floor(offset), amount };
    }).filter(Boolean);

  // ────────── State ──────────
  let lastResult = null;
  let reportUrls = { forecast: null, rebalance: null };
  let navChart = null;
  let rollChart = null;
  let currentMode = 'common';

  // ────────── 啟動：載入 profiles ──────────
  async function loadProfiles() {
    try {
      const r = await fetch('/api/profiles');
      const d = await r.json();
      const sel = $('profileSel');
      sel.innerHTML = '';
      const profiles = d.profiles || [];
      if (profiles.length === 0) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = '（user_profile/ 沒有 CSV）';
        sel.appendChild(opt);
        sel.disabled = true;
        $('btnRun').disabled = true;
        return;
      }
      profiles.forEach((p) => {
        const opt = document.createElement('option');
        opt.value = p;
        opt.textContent = p + '.csv';
        sel.appendChild(opt);
      });
      // 預設選 liyu_stock
      if (profiles.includes('liyu_stock')) sel.value = 'liyu_stock';
      // 動態載入預覽
      sel.addEventListener('change', () => previewProfile(sel.value));
      previewProfile(sel.value);
    } catch (e) {
      setText('err', '載入名單失敗：' + e.message);
      $('err').classList.add('show');
    }
  }

  async function previewProfile(name) {
    if (!name) {
      setText('profileMeta', '');
      return;
    }
    try {
      const r = await fetch('/api/profile/' + encodeURIComponent(name));
      const d = await r.json();
      if (!r.ok) {
        setText('profileMeta', '⚠️ ' + (d.error || '讀不到'));
        return;
      }
      setText('profileMeta', `共 ${d.count} 檔股票`);
    } catch (e) {
      setText('profileMeta', '⚠️ ' + e.message);
    }
  }

  // ────────── 上傳 CSV 名單 ──────────
  async function uploadProfile(file) {
    const fd = new FormData();
    fd.append('file', file);
    const btn = $('btnUploadProfile');
    btn.disabled = true;
    btn.textContent = '⏳ 上傳中…';
    try {
      const r = await fetch('/api/upload_profile', { method: 'POST', body: fd });
      const d = await r.json();
      if (!r.ok) {
        showErr('上傳失敗：' + (d.error || 'unknown'), d);
        return;
      }
      clearErr();
      await loadProfiles();
      const sel = $('profileSel');
      sel.value = d.name;
      if (sel.value === d.name) {
        // 手動觸發 change 讓 preview 跑一次
        sel.dispatchEvent(new Event('change'));
      }
    } catch (e) {
      showErr('上傳失敗：' + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = '📁 上傳 CSV';
    }
  }

  function bindUpload() {
    const btn = $('btnUploadProfile');
    const input = $('fileUploadProfile');
    btn.addEventListener('click', () => input.click());
    input.addEventListener('change', () => {
      if (input.files.length === 0) return;
      const f = input.files[0];
      if (!f.name.toLowerCase().endsWith('.csv')) {
        showErr('只接受 .csv 檔案');
        input.value = '';
        return;
      }
      uploadProfile(f);
      // 清空 value 才能重複上傳同檔
      input.value = '';
    });
  }

  // ────────── 錯誤顯示 ──────────
  // v3.0.3:支援結構化 payload (TICKER_NOT_FOUND 等)
  // payload: {error, code, failed: [{line, ticker, reason}], changes, ...}
  function showErr(msg, payload) {
    const e = $('err');
    e.textContent = msg;
    e.classList.add('show');
    // 清除舊的 detail
    const old = document.getElementById('errDetail');
    if (old) old.remove();
    // 只有 v3.0.3 結構化錯誤才顯示 detail panel
    if (payload && payload.code === 'TICKER_NOT_FOUND' && Array.isArray(payload.failed) && payload.failed.length > 0) {
      const detail = document.createElement('div');
      detail.id = 'errDetail';
      detail.className = 'err-detail';
      const title = document.createElement('div');
      title.className = 'err-detail-title';
      title.textContent = `無法辨識的代號 (${payload.failed.length} 個)：`;
      const ul = document.createElement('ul');
      ul.className = 'err-detail-list';
      payload.failed.forEach((f) => {
        const li = document.createElement('li');
        const tickerSpan = document.createElement('span');
        tickerSpan.className = 'err-detail-ticker';
        tickerSpan.textContent = f.ticker;
        const reasonSpan = document.createElement('span');
        reasonSpan.className = 'err-detail-reason';
        reasonSpan.textContent = ` 第 ${f.line} 行 — ${f.reason}`;
        li.appendChild(tickerSpan);
        li.appendChild(reasonSpan);
        ul.appendChild(li);
      });
      detail.appendChild(title);
      detail.appendChild(ul);
      e.appendChild(detail);
    }
  }
  function clearErr() {
    const e = $('err');
    e.textContent = '';
    e.classList.remove('show');
    const old = document.getElementById('errDetail');
    if (old) old.remove();
  }

  // ────────── 主分析 ──────────
  async function runAnalyze(e) {
    e.preventDefault();
    clearErr();
    $('out').hidden = true;
    $('btnRun').disabled = true;
    $('btnExportHtml').disabled = true;
    $('btnRebalance').disabled = true;
    reportUrls = { forecast: null, rebalance: null };
    setText('status', '分析中（首次抓 FinMind 需 30~60 秒）...');

    const f = e.target;
    const body = {
      profile: f.profile.value,
      n: parseInt(f.n.value, 10),
      pv: f.pv.value ? parseFloat(f.pv.value) : null,
      weights: f.weights.value.trim() || null,
      benchmark: f.benchmark.value.trim() || null,
      fee_buy: parseFloat(f.fee_buy.value || 0) / 100,
      tax_sell: parseFloat(f.tax_sell.value || 0) / 100,
      slippage: parseFloat(f.slippage.value || 0) / 100,
      v2_current_age: parseInt(f.v2_current_age.value, 10),
      v2_retirement_age: parseInt(f.v2_retirement_age.value, 10),
      v2_retirement_end_age: parseInt(f.v2_retirement_end_age.value, 10),
      v2_n_simulations: parseInt(f.v2_n_simulations.value, 10),
      v2_withdrawal_monthly: parseFloat(f.v2_withdrawal_monthly.value || 0),
      v2_withdrawal_inflation: parseFloat(f.v2_withdrawal_inflation.value || 0) / 100,
      v2_pension_monthly: parseFloat(f.v2_pension_monthly.value || 0),
      v2_pension_inflation: parseFloat(f.v2_pension_inflation.value || 0) / 100,
      v2_special_expenses: parseSpecialExpenses(f.v2_special_expenses.value),
    };

    try {
      const r = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const d = await r.json();
      if (!r.ok) {
        showErr(d.error || '分析失敗', d);
        setText('status', '');
        return;
      }
      lastResult = d;
      // v3.0.3 N8: 同時拉 card ⑧ monthly returns
      loadMonthlyReturns(body.profile);
      try {
        renderAll(d);
      } catch (renderErr) {
        // v3.0.2: 拿掉 '網路錯誤' 誤稱,顯示真正錯誤 + stack,讓主人能 debug
        console.error('[renderAll] failed:', renderErr);
        showErr('渲染錯誤：' + renderErr.message + '（看 console）');
      }
      setText('status', '分析完成，正在產生兩份 HTML 報告…');
      reportUrls = await generateReports(d);
      $('btnExportHtml').disabled = !reportUrls.forecast;
      $('btnRebalance').disabled = !reportUrls.rebalance;
      setText('status', '✓ 完成（兩份報告已產生）');
    } catch (e) {
      // fetch / JSON parse 階段錯誤 (不是 render)
      console.error('[fetch] failed:', e);
      showErr('網路錯誤：' + e.message);
    } finally {
      $('btnRun').disabled = false;
    }
  }

  // ────────── 渲染：Ticker 驗證結果 ──────────
  function renderTickerMatch(d) {
    const wrap = $('tickerMatch');
    const ins = d.inputs;
    const tm = ins.ticker_match || {};
    const invalid = ins.invalid_tickers || [];
    const short = new Set(ins.short_history || []);

    const matchedRows = Object.values(tm)
      .sort((a, b) => a.stock_id.localeCompare(b.stock_id))
      .map((m) => {
        const isShort = short.has(m.stock_id);
        const tag = m.source === 'exact' ? '' : '<small class="hint">(原 ' + m.matched_from[0] + ')</small>';
        const shortWarn = isShort ? ' <b style="color:#b42318">⚠️ 歷史 < ' + (ins.n || 10) + ' 年</b>' : '';
        return `<tr>
          <td>${m.stock_id}${tag}</td>
          <td>${m.stock_name || '—'}</td>
          <td>${m.industry || '—'}</td>
          <td>${m.type || '—'}</td>
          <td>${m.matched_from.join(', ')}</td>
          <td>${shortWarn}</td>
        </tr>`;
      })
      .join('');

    let invalidHtml = '';
    if (invalid.length > 0) {
      invalidHtml = `<div class="err show" style="margin-top:12px">
        <b>⚠️ 以下代號在 FinMind TaiwanStockInfo 查無資料，會被略過：</b>
        <ul>${invalid.map(x => `<li>${x.user_input}${x.stock_id ? ' → ' + x.stock_id : ''}：${x.reason}</li>`).join('')}</ul>
      </div>`;
    }

    wrap.innerHTML = `
      <table>
        <thead><tr>
          <th>stock_id</th><th>名稱</th><th>產業</th><th>市場</th>
          <th>使用者原始輸入</th><th>備註</th>
        </tr></thead>
        <tbody>${matchedRows || '<tr><td colspan="6" class="hint">無有效 ticker</td></tr>'}</tbody>
      </table>
      ${invalidHtml}
    `;
  }

  // ────────── 渲染：組合起始市值 ──────────
  function renderMarketValue(d) {
    const wrap = $('mv');
    const ins = d.inputs;
    const mv = d.market_value || {};
    const per = mv.per_stock || [];
    const missing = mv.missing || [];

    const rows = per
      .sort((a, b) => b.value - a.value)
      .map((s) => {
        const pct = mv.total > 0 ? (s.value / mv.total * 100).toFixed(1) : '0.0';
        return `<tr>
          <td>${s.ticker}</td>
          <td>${fmtMoney(s.shares)}</td>
          <td>${fmtFloat(s.close, 2)}</td>
          <td>${fmtMoney(s.value)}</td>
          <td>${pct}%</td>
        </tr>`;
      })
      .join('');

    const pvSourceText = ins.pv_source === 'market_value'
      ? '（自動從收盤價 × 股數計算）'
      : '（使用者手動輸入）';

    wrap.innerHTML = `
      <div class="kpi" style="grid-template-columns: repeat(3, 1fr);">
        <div><small>估值日</small><b>${mv.as_of || '—'}</b></div>
        <div><small>組合市值（PV）</small><b style="color:#17365d">${fmtMoney(mv.total)}</b></div>
        <div><small>市值來源</small><b style="font-size:14px">${pvSourceText}</b></div>
      </div>
      <table style="margin-top:14px">
        <thead><tr><th>股票</th><th>股數</th><th>收盤價</th><th>市值</th><th>權重</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="5" class="hint">無資料</td></tr>'}</tbody>
      </table>
      ${missing.length > 0 ? `<p class="err">缺少價格資料：${missing.join(', ')}</p>` : ''}
    `;
  }

  // ────────── 渲染：歷史診斷（per-stock 加強版）──────────
  function renderHistory(d) {
    const wrap = $('hist');
    const per = d.history.per_stock || {};
    const ov = d.history.overview || {};
    const ins = d.inputs;
    const short = new Set(ins.short_history || []);

    const rows = Object.entries(per)
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([t, info]) => {
        const warn = short.has(t) ? ' <b style="color:#b42318">⚠️</b>' : '';
        return `<tr>
          <td>${t}${warn}</td>
          <td>${info.start || '—'}</td>
          <td>${info.end || '—'}</td>
          <td>${info.rows || 0}</td>
          <td>${(info.years || 0).toFixed(2)}</td>
          <td>${info.first_close != null ? fmtFloat(info.first_close, 2) : '—'}</td>
        </tr>`;
      })
      .join('');

    wrap.innerHTML = `
      <table>
        <thead><tr>
          <th>股票</th><th>第一天</th><th>最後一天</th>
          <th>資料點</th><th>歷史年數</th><th>首日收盤</th>
        </tr></thead>
        <tbody>${rows}</tbody>
        <tfoot>
          <tr><th>股票數</th><td colspan="2">${ov.stocks || 0}</td>
            <th>最短 / 中位 / 最長</th>
            <td colspan="2">${(ov.min_years || 0).toFixed(2)} / ${(ov.median_years || 0).toFixed(2)} / ${(ov.max_years || 0).toFixed(2)} 年</td></tr>
        </tfoot>
      </table>`;
  }

  // ────────── 渲染：KPI + NAV ──────────
  function renderMode(mode) {
    const r = lastResult[mode];
    if (!r) {
      $('kpi').innerHTML = '<div class="hint">此模式無結果</div>';
      return;
    }
    const m = r.metrics;
    const kpi = [
      ['開始', m.start || '—'],
      ['結束', m.end || '—'],
      ['年數', fmtFloat(m.years, 2)],
      ['Total Return', fmtPct(m.total_return)],
      ['CAGR', fmtPct(m.cagr)],
      ['MDD', fmtPct(m.mdd)],
      ['Volatility', fmtPct(m.volatility)],
      ['Sharpe', fmtFloat(m.sharpe)],
    ];
    $('kpi').innerHTML = kpi
      .map(([k, v]) => `<div><small>${k}</small><b>${v}</b></div>`)
      .join('');

    renderNavChart();
  }

  function renderNavChart() {
    const r = lastResult[currentMode];
    const series = r.nav || [];
    const labels = series.map((p) => p.date);
    const data = series.map((p) => p.nav);

    if (navChart) navChart.destroy();
    const ctx = document.getElementById('navChart');
    navChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Portfolio NAV (' + currentMode + ')',
          data,
          borderColor: '#17365d',
          backgroundColor: 'rgba(23, 54, 93, 0.08)',
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.1,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: true, position: 'top' } },
        scales: {
          x: { ticks: { maxTicksLimit: 8, autoSkip: true }, grid: { display: false } },
          y: { ticks: { maxTicksLimit: 6 } },
        },
      },
    });
  }

  // ────────── 渲染：Forecast ──────────
  function renderForecast(d) {
    const f = d.forecast;
    setText('fcBasis', f.basis || 'common');
    const tb = $('fcTable').querySelector('tbody');
    tb.innerHTML = (f.scenarios || [])
      .map((s) => {
        const isBase = s.label === 'Base';
        return `<tr class="${isBase ? 'highlight' : ''}">
          <td>${s.label}</td>
          <td>P${(s.quantile * 100) | 0}</td>
          <td>${fmtPct(s.cagr)}</td>
          <td>${fmtMoney(f.pv)}</td>
          <td><b>${fmtMoney(s.fv)}</b></td>
          <td>${fmtFloat(s.multiplier, 2)}x</td>
        </tr>`;
      })
      .join('');
    setText('rCount', f.r_count);
    const basisMap = { common: '全體共同期間', dynamic: '逐步加入模式', full: '各標的完整歷史' };
    const basisZh = basisMap[f.basis] || f.basis || '—';
    $('forecastNote').innerHTML = `取「<b>${basisZh}</b>」模式下所有 N 年持有期間的歷史收益分布，依分位數算出 5 個情境的終值。FV = 目前資產 × (1+r)^N。<b>不模擬未來逐年路徑</b>。` + (d.inputs.pv_cost_text ? ' ' + d.inputs.pv_cost_text : '');

    const rs = f.rolling || [];
    if (rollChart) rollChart.destroy();
    const ctx = document.getElementById('rollChart');

    // 主資料集：滾動 CAGR 時間序列
    const datasets = [{
      label: 'Rolling N-Year CAGR %',
      data: rs.map((x) => x.cagr * 100),
      borderColor: '#58a6ff',
      backgroundColor: 'rgba(88, 166, 255, 0.1)',
      borderWidth: 1.5,
      pointRadius: 2,
      tension: 0.1,
      fill: true,
    }];

    // 5 條水平分位線（從 f.percentiles 讀股寶已算好的）
    const pctColors = {
      Bear:         '#f85149',  // P10 紅
      Conservative: '#d29922',  // P25 橘
      Base:         '#58a6ff',  // P50 藍（同主線色但虚線區分）
      Optimistic:   '#3fb950',  // P75 綠
      Bull:         '#8957e5',  // P90 紫
    };
    (f.scenarios || []).forEach((s) => {
      const cagrPct = (s.cagr * 100).toFixed(2);
      datasets.push({
        label: `${s.label} (P${(s.quantile * 100) | 0}) ${cagrPct}%`,
        data: rs.map(() => s.cagr * 100),  // 水平線：每個點同值
        borderColor: pctColors[s.label] || '#888',
        borderDash: [5, 4],
        borderWidth: 1.2,
        pointRadius: 0,
        fill: false,
      });
    });

    rollChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: rs.map((x) => x.end),
        datasets,
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: true, position: 'top' } },
        scales: {
          x: { ticks: { maxTicksLimit: 8, autoSkip: true }, grid: { display: false } },
          y: { ticks: { maxTicksLimit: 6 } },
        },
      },
    });
  }

  // ────────── 渲染：⑤ 標題下的權重分配結果（v3.1.2）──────────
  function renderWeightsInfo(d) {
    const wrap = $('weightsContent');
    if (!wrap) return;
    const ew = d.effective_weights || {};
    const src = d.weights_source || 'unknown';
    const sourceMap = {
      'user': '使用者自訂',
      'market_cap': '市值加權總計為1',
      'equal': '等權重（fallback）',
    };
    const sourceText = sourceMap[src] || src;

    // v3.1.2 b: 格式 = 權重輸入框 (TICKER:0.XXX)；由大到小，去掉最小一筆（>= 2 才去）
    // 理由：3 個 decimal 四捨五入多檔會累加成 1.0001，去掉最小一筆把誤差藏起來
    const sorted = Object.entries(ew).sort((a, b) => b[1] - a[1]);
    const kept = sorted.length > 1 ? sorted.slice(0, -1) : sorted;
    const items = kept
      .map(([t, w]) => `<b style="color:#17365d">${t}</b>:${w.toFixed(3)}`)
      .join(', ');

    if (items) {
      wrap.innerHTML = `（${sourceText}） ${items}`;
    } else {
      wrap.innerHTML = `（${sourceText}） —`;
    }
  }

  // ────────── 全部渲染 ──────────
  function renderAll(d) {
    // v3.0.2: 每個 render step 各自 try/catch, 某個失敗不拖垮其他
    const steps = [
      ['tickerMatch', () => renderTickerMatch(d)],
      ['marketValue', () => renderMarketValue(d)],
      ['history', () => renderHistory(d)],
      ['weightsInfo', () => renderWeightsInfo(d)],
      ['mode', () => renderMode(currentMode)],
      ['forecast', () => renderForecast(d)],
      ['benchmark', () => renderBenchmark(d)],
      ['v2Sections', () => renderV2Sections(d)],
    ];
    for (const [name, fn] of steps) {
      try {
        fn();
      } catch (stepErr) {
        console.error(`[renderAll:${name}] failed:`, stepErr);
        throw stepErr;  // 統一交給上面 catch 顯示
      }
    }
    $('out').hidden = false;
  }

  // ────────── 渲染：B6 v2 sections (F1/F2/F3/F6) ──────────
  function renderV2Sections(d) {
    renderMonteCarloCard(d);
    renderRiskMetricsCard(d);
  }

  function renderMonteCarloCard(d) {
    const card = $('monteCarloCard');
    const mc = d.monte_carlo;
    const sr = d.sequence_risk;
    // 任一可用才顯示 card
    if ((mc == null || mc == undefined) && (sr == null || sr == undefined)) {
      card.hidden = true;
      return;
    }
    card.hidden = false;

    // F1 summary
    const mcTbody = $('mcTable').querySelector('tbody');
    if (mc && mc.summary) {
      const s = mc.summary;
      const nSims = mc.n_simulations;
      const horizon = mc.horizon_years;
      setText('mcMeta', `（n=${nSims} × ${horizon} 年 · 區塊 bootstrap）`);
      const rows = [
        ['中位終值', fmtMoney(s.median_final)],
        ['平均終值', fmtMoney(s.mean_final)],
        ['P10（養老規劃下限）', fmtMoney(s.p10_final)],
        ['P90（養老規劃上限）', fmtMoney(s.p90_final)],
        ['資產 ≥ 初始機率', fmtPct(s.prob_above_initial)],
        ['資產 ≤ 0 機率（破產）', fmtPct(s.prob_zero_or_negative)],
        ['存活到 horizon 機率', fmtPct(s.survival_to_horizon)],
      ];
      mcTbody.innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');
    } else {
      setText('mcMeta', '（F1 模擬未執行）');
      mcTbody.innerHTML = '<tr><td colspan="2" class="hint">F1 Monte Carlo 無資料（v2 關閉或計算失敗）</td></tr>';
    }

    // F2 Sequence Risk
    const srTbody = $('srTable').querySelector('tbody');
    if (sr && typeof sr.survival_rate === 'number') {
      const rate = sr.survival_rate;
      let color = '#1e8e3e';
      if (rate < 0.5) color = '#b42318';
      else if (rate < 0.7) color = '#b45309';
      const ageMap = sr.success_rate_by_age || {};
      const fmtAge = (age) => {
        const v = ageMap[String(age)];
        return v == null ? '—' : fmtPct(v);
      };
      const rows = [
        [`存活率（資產 > 0 機率）`, `<b style="color:${color};">${fmtPct(rate)}</b>`],
        ['中位終值餘額（NT$）', fmtMoney(sr.median_final_balance)],
        ['70 歲存活率', fmtAge(70)],
        ['75 歲存活率', fmtAge(75)],
        ['80 歲存活率', fmtAge(80)],
        ['85 歲存活率', fmtAge(85)],
        ['90 歲存活率', fmtAge(90)],
      ];
      srTbody.innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');
    } else {
      srTbody.innerHTML = '<tr><td colspan="2" class="hint">F2 Sequence Risk 無資料（v2 關閉或計算失敗）</td></tr>';
    }
  }

  function renderRiskMetricsCard(d) {
    const card = $('riskMetricsCard');
    const rm = d.risk_metrics;
    if (!rm) { card.hidden = true; return; }
    card.hidden = false;

    // F3 VaR / CVaR
    const varTbody = $('varTable').querySelector('tbody');
    const vc = rm.var_cvar || null;
    if (vc) {
      const fmtVc = (v) => (v == null) ? 'N/A' : fmtPct(v);
      const row = (label, k1, k21, k252) => `<tr><td>${label}</td><td>${fmtVc(vc[k1])}</td><td>${fmtVc(vc[k21])}</td><td>${fmtVc(vc[k252])}</td></tr>`;
      varTbody.innerHTML = [
        row('95% VaR', 'var_1d_95', 'var_21d_95', 'var_252d_95'),
        row('99% VaR', 'var_1d_99', 'var_21d_99', 'var_252d_99'),
        row('95% CVaR（條件損失）', 'cvar_1d_95', 'cvar_21d_95', 'cvar_252d_95'),
        row('99% CVaR', 'cvar_1d_99', 'cvar_21d_99', 'cvar_252d_99'),
      ].join('');
    } else {
      varTbody.innerHTML = '<tr><td colspan="4" class="hint">F3 VaR/CVaR 無資料</td></tr>';
    }

    // F6 Sharpe
    const sharpeTbody = $('sharpeTable').querySelector('tbody');
    const sh = rm.sharpe || null;
    if (sh && typeof sh.sharpe_with_rf === 'number') {
      const rfPct = fmtPct(sh.rf_used);
      setText('rfUsed', rfPct);
      sharpeTbody.innerHTML = [
        `<tr><td>Sharpe with Rf（使用 ${rfPct} 無風險利率）</td><td><b>${fmtFloat(sh.sharpe_with_rf, 3)}</b></td></tr>`,
        `<tr><td>Sharpe rf=0（對照組）</td><td>${fmtFloat(sh.sharpe_rf_0, 3)}</td></tr>`,
        `<tr><td>無風險利率來源</td><td>${sh.rf_used}（預設台灣 10Y 公債，可覆寫）</td></tr>`,
      ].join('');
    } else {
      setText('rfUsed', '—');
      sharpeTbody.innerHTML = '<tr><td colspan="2" class="hint">F6 Sharpe 無資料</td></tr>';
    }
  }

  function renderBenchmark(d) {
    const card = $('benchCard');
    const wrap = $('bench');
    const b = d.benchmark;
    if (!b || !b.metrics) { card.hidden = true; return; }
    card.hidden = false;
    const m = b.metrics;
    const baseMetrics = (d.dynamic && d.dynamic.metrics) || (d.common && d.common.metrics) || {};
    const rows = [
      ['年數', fmtFloat(m.years, 2), fmtFloat(baseMetrics.years, 2)],
      ['CAGR', fmtPct(m.cagr), fmtPct(baseMetrics.cagr)],
      ['MDD', fmtPct(m.mdd), fmtPct(baseMetrics.mdd)],
      ['Vol', fmtPct(m.volatility), fmtPct(baseMetrics.volatility)],
      ['Sharpe', fmtFloat(m.sharpe, 3), fmtFloat(baseMetrics.sharpe, 3)],
    ];
    const delta = (a, b) => (a - b);
    const diffClass = (bench, port) => {
      const d = bench - port;
      if (Math.abs(d) < 0.001) return '';
      return d > 0 ? ' style="color:#3fb950"' : ' style="color:#f85149"';
    };
    wrap.innerHTML = `
      <table>
        <thead><tr><th>指標</th><th>Benchmark ${b.ticker}</th><th>組合 (Dynamic)</th></tr></thead>
        <tbody>
          <tr><td>年數</td><td>${fmtFloat(m.years, 2)}</td><td>${fmtFloat(baseMetrics.years, 2)}</td></tr>
          <tr><td>CAGR</td><td${diffClass(m.cagr, baseMetrics.cagr)}>${fmtPct(m.cagr)}</td><td>${fmtPct(baseMetrics.cagr)}</td></tr>
          <tr><td>MDD</td><td${diffClass(baseMetrics.mdd, m.mdd)}>${fmtPct(m.mdd)}</td><td>${fmtPct(baseMetrics.mdd)}</td></tr>
          <tr><td>Vol</td><td>${fmtPct(m.volatility)}</td><td>${fmtPct(baseMetrics.volatility)}</td></tr>
          <tr><td>Sharpe</td><td${diffClass(m.sharpe, baseMetrics.sharpe)}>${fmtFloat(m.sharpe, 3)}</td><td>${fmtFloat(baseMetrics.sharpe, 3)}</td></tr>
        </tbody>
      </table>
      <p class="hint">差異以綠/紅標示：綠色 = 該指標 <b>正向優勢</b>（CAGR/Sharpe 越高越好；MDD 越接近 0 越好）</p>`;
  }

  // ────────── Tab 切換 ──────────
  function bindTabs() {
    document.querySelectorAll('.tab').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        currentMode = btn.dataset.mode;
        if (lastResult) renderMode(currentMode);
      });
    });
  }

  // ────────── 報告產生與開啟 ──────────
  async function createReport(reportType) {
    const r = await fetch('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        result: lastResult,
        format: 'html',
        report_type: reportType,
        profile_name: lastResult.inputs.profile,
      }),
    });
    const d = await r.json();
    if (!r.ok) {
      throw new Error(d.error || '報告產生失敗');
    }
    return d.url;
  }

  async function generateReports(result) {
    lastResult = result;
    const [forecast, rebalance] = await Promise.all([
      createReport('forecast'),
      createReport('rebalance'),
    ]);
    return { forecast, rebalance };
  }

  function openReport(type) {
    const url = reportUrls[type];
    if (url) window.open(url, '_blank');
  }

  // ────────── 綁定 ──────────
  document.addEventListener('DOMContentLoaded', () => {
    $('fAnalyze').addEventListener('submit', runAnalyze);
    $('btnExportHtml').addEventListener('click', () => openReport('forecast'));
    $('btnRebalance').addEventListener('click', () => openReport('rebalance'));
    bindTabs();
    bindUpload();
    loadProfiles();
  });
})();
// card ⑧ N8


// v3.0.3 N8: card ⑧ 歷史真實績效明細表
async function loadMonthlyReturns(profile) {
  const wrap = document.getElementById('monthlyReturns');
  if (!wrap) return;
  wrap.innerHTML = '<p class="muted">載入中…</p>';
  try {
    const r = await fetch('/api/v2/monthly_returns', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile }),
    });
    const d = await r.json();
    if (!r.ok) {
      wrap.innerHTML = `<p class="err show">${d.error || '載入失敗'}</p>`;
      return;
    }
    if (!d.tickers || d.tickers.length === 0) {
      wrap.innerHTML = '<p class="muted">無資料</p>';
      return;
    }
    // Render simple table per ticker (collapsible)
    wrap.innerHTML = d.tickers.map(t => {
      const years = Object.keys(t.data).sort();
      const headerCells = '<th>Ticker</th>' + Array.from({length: 12}, (_, i) => `<th>${i+1}月</th>`).join('') + '<th>年平均</th>';
      const rows = years.map(y => {
        const months = t.data[y];
        const cells = Array.from({length: 12}, (_, i) => {
          const v = months[String(i+1)];
          return `<td>${v === null || v === undefined ? '—' : (v*100).toFixed(2) + '%'}</td>`;
        }).join('');
        const avg = months.year_avg;
        const avgCell = `<td><b>${avg === null || avg === undefined ? '—' : (avg*100).toFixed(2) + '%'}</b></td>`;
        return `<tr><td>${y}</td>${cells}${avgCell}</tr>`;
      }).join('');
      return `<details class="monthly-ticker"><summary><b>${t.ticker}</b> (${t.first_year}–${t.last_year})</summary>
        <table class="monthly-table"><thead><tr>${headerCells}</tr></thead><tbody>${rows}</tbody></table>
      </details>`;
    }).join('');
  } catch (e) {
    wrap.innerHTML = `<p class="err show">網路錯誤:${e.message}</p>`;
  }
}
