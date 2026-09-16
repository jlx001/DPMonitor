// Report page errors back to the Python host for diagnostics.
window.onerror = function(msg, src, line, col, err) {
  try {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.log_js) {
      window.pywebview.api.log_js(String(msg) + ' @' + line + ':' + col);
    }
  } catch (ignore) {}
  return false;
};
window.addEventListener('unhandledrejection', function(event) {
  try {
    var reason = event.reason;
    var text = reason && reason.message ? reason.message : String(reason);
    if (window.pywebview && window.pywebview.api && window.pywebview.api.log_js) {
      window.pywebview.api.log_js('promise: ' + text);
    }
  } catch (ignore) {}
});

// ===== DeepSeek Usage Monitor =====
var api = null;

function initWhenReady() {
  if (window.pywebview && window.pywebview.api) { api = window.pywebview.api; setupApp(); }
  else { setTimeout(initWhenReady, 50); }
}
document.addEventListener('DOMContentLoaded', function() { initWhenReady(); });

function setupApp() {

var I = {
  download: '<polyline points="8 17 12 21 16 17"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.88 18.09A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.29"/>',
  target: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
  activity: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
  zap: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
};
function S(name, s) {
  s = s || 14;
  return '<svg width="'+s+'" height="'+s+'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'+(I[name]||I.activity)+'</svg>';
}
function K(n) { if (n==null||isNaN(n)) return '--'; if (n>=1e9) return (n/1e9).toFixed(1)+'B'; if (n>=1e6) return (n/1e6).toFixed(1)+'M'; if (n>=1e4) return (n/1e3).toFixed(1)+'K'; return n.toLocaleString(); }
function M(n) { return (n==null||isNaN(n))?'--':'￥'+n.toFixed(2); }
// Show the platform's own model names; the slug only keys DOM ids.
function modelLabel(name) { return name || ''; }
// A model the platform reports no usage for today stays off the panel.
function modelUsedToday(entry) {
  if (!entry) return false;
  if (Number(entry.cost||0) > 0) return true;
  return Number(entry.input_tokens_cache_hit||0) > 0
    || Number(entry.input_tokens_cache_miss||0) > 0
    || Number(entry.output_tokens||0) > 0;
}
function modelIds(names) {
  var ids = [], seen = {};
  for (var i=0;i<names.length;i++) {
    var slug = String(names[i]).replace(/[^a-zA-Z0-9]+/g,'_');
    if (seen[slug]) slug = slug+'_'+i;
    seen[slug] = true;
    ids.push(slug);
  }
  return ids;
}
// Today's totals come from the platform's per-model day rows, so the panel
// and the platform's own usage page agree on both tokens and requests.
function renderTodayUsage(todayModels) {
  var tokensBox = document.getElementById('todayTokens');
  var requestsBox = document.getElementById('todayRequests');
  if (!tokensBox || !requestsBox) return;
  if (!todayModels) {
    tokensBox.textContent = '--';
    requestsBox.textContent = '--';
    return;
  }
  var tokenTotal = 0, requestTotal = 0;
  for (var name in todayModels) {
    var entry = todayModels[name] || {};
    tokenTotal += (entry.input_tokens_cache_hit||0)
      + (entry.input_tokens_cache_miss||0) + (entry.output_tokens||0);
    requestTotal += entry.requests||0;
  }
  tokensBox.textContent = K(tokenTotal);
  requestsBox.textContent = String(requestTotal);
}

// Model names are whatever the platform reports; only hidden ones are kept
// here so renamed or newly added models show up on their own.
var hiddenModels = [];
var allModelNames = [];
var chart = null, timer = null;
var allChartData = [];
var chartMode = 'week';
var activeSkId = null;
var skListCache = [];
var recentTimer = null, clearArmed = false, clearResetTimer = null;

function showPanel(name) {
  document.getElementById('mainPanel').style.display = name==='main'?'block':'none';
  document.getElementById('settingsPanel').style.display = name==='settings'?'block':'none';
  document.getElementById('skPanel').style.display = name==='sk'?'block':'none';
  if (name==='settings') loadForm();
  if (name==='sk') loadSkPanel();
}
window.showPanel = showPanel;

// ===== Data =====
function fetchWebData() {
  api.get_usage_data().then(function(d) {
    if (!d) return renderAll({});
    if (d.error && d.error==='no_token') return renderAll({});
    renderAll(d);
  }).catch(function(){ renderAll({}); });
  refreshRecentConversations();
}

function refreshRecentConversations() {
  api.get_conversations().then(renderRecentConversations)
    .catch(function(){});
}

function startRecentTimer(sec) {
  if (recentTimer) clearInterval(recentTimer);
  recentTimer = setInterval(refreshRecentConversations,
                            (sec || 5) * 1000);
}

function refreshData() {
  if (activeSkId!==null && !isMainSk(activeSkId)) {
    // The SK view reads its balance and today's totals from the pool call and
    // its model detail from the detail call, so refresh the pool first.
    var skId = activeSkId;
    renderSkTabs(function(){ loadSkDetail(skId); });
    return;
  }
  fetchWebData();
  renderSkTabs();
}
window.refreshData = refreshData;

function renderAll(d) {
  var b = d.balance || {}, u = d.usage || {};

  var el = document.getElementById('balanceValue');
  var v = b.total_balance;
  el.textContent = b.error ? '--' : M(v);
  el.className = 'overview-balance' + (v<10?' danger':v<50?' warning':'');
  document.getElementById('dailyCost').textContent = M(u.daily_cost);
  document.getElementById('monthlyCost').textContent = M(u.monthly_cost);
  renderTodayUsage(u.today_models);

  var models = u.models || {}, todayModels = u.today_models || {};
  allModelNames = [];
  for (var name in models) allModelNames.push(name);
  var shownModels = [];
  for (var si=0;si<allModelNames.length;si++) {
    var candidate = allModelNames[si];
    if (hiddenModels.indexOf(candidate)>=0) continue;
    if (!modelUsedToday(todayModels[candidate])) continue;
    shownModels.push(candidate);
  }
  var savedToggles = {};
  document.querySelectorAll('.mtg.active').forEach(function(b){savedToggles[b.dataset.mid]=b.dataset.mode});
  var shownIds = modelIds(shownModels);
  var h = '';
  for (var i=0;i<shownModels.length;i++) {
    var mk = shownModels[i];
    var ms = models[mk] || {}, ts = todayModels[mk] || {};
    var lbl = modelLabel(mk);
    var mid = shownIds[i];
    h += '<div class="card model-card">';
    h += '<div class="model-name-row">';
    h += '<span class="model-name-title">'+S('zap',18)+' '+esc(lbl)+'</span>';
    h += '<div class="chart-toggle">';
    h += '<button class="chart-tg mtg active" data-mid="'+mid+'" data-mode="today">今日</button>';
    h += '<button class="chart-tg mtg" data-mid="'+mid+'" data-mode="month">本月</button>';
    h += '</div></div>';
    h += '<div class="model-panel" id="mp_'+mid+'_month" style="display:none">';
    h += '<div class="model-grid">';
    h += '<div class="token-item"><div class="token-label">'+S('download',12)+' 输入·缓存命中</div><div class="token-value">'+K(ms.input_tokens_cache_hit)+'</div></div>';
    h += '<div class="token-item"><div class="token-label">'+S('download',12)+' 输入·缓存未命中</div><div class="token-value">'+K(ms.input_tokens_cache_miss)+'</div></div>';
    h += '</div><div class="model-full">';
    h += '<div class="token-item"><div class="token-label">'+S('activity',12)+' 输出 token</div><div class="token-value">'+K(ms.output_tokens)+'</div></div>';
    h += '<div class="token-item"><div class="token-label">'+S('target',12)+' 缓存命中率</div><div class="token-value"><span class="hit-badge '+(ms.hit_rate>=80?'high':(ms.hit_rate>=50?'mid':''))+'">'+S('target',14)+' '+(ms.hit_rate||0)+'%</span></div></div>';
    h += '</div></div>';
    var tTotal = (ts.input_tokens_cache_hit||0) + (ts.input_tokens_cache_miss||0);
    var tRate = tTotal>0 ? Math.round((ts.input_tokens_cache_hit||0)/tTotal*1000)/10 : 0;
    h += '<div class="model-panel" id="mp_'+mid+'_today">';
    h += '<div class="model-grid">';
    h += '<div class="token-item"><div class="token-label">'+S('download',12)+' 输入·缓存命中</div><div class="token-value">'+K(ts.input_tokens_cache_hit)+'</div></div>';
    h += '<div class="token-item"><div class="token-label">'+S('download',12)+' 输入·缓存未命中</div><div class="token-value">'+K(ts.input_tokens_cache_miss)+'</div></div>';
    h += '</div><div class="model-full">';
    h += '<div class="token-item"><div class="token-label">'+S('activity',12)+' 输出 token</div><div class="token-value">'+K(ts.output_tokens)+'</div></div>';
    h += '<div class="token-item"><div class="token-label">'+S('target',12)+' 缓存命中率</div><div class="token-value"><span class="hit-badge '+(tRate>=80?'high':(tRate>=50?'mid':''))+'">'+S('target',14)+' '+tRate+'%</span></div></div>';
    h += '</div></div>';
    h += '</div>';
  }
  if (!shownModels.length) {
    h = '<div class="card"><div class="sk-hint">今日暂无模型用量记录——'+
        '有调用后自动出现。</div></div>';
  }
  document.getElementById('modelCards').innerHTML = h;
  for (var mid in savedToggles) {
    var mode = savedToggles[mid];
    var monthPanel = document.getElementById('mp_'+mid+'_month');
    var todayPanel = document.getElementById('mp_'+mid+'_today');
    if (!monthPanel || !todayPanel) continue;
    monthPanel.style.display = mode==='month'?'block':'none';
    todayPanel.style.display = mode==='today'?'block':'none';
    document.querySelectorAll('.mtg[data-mid="'+mid+'"]').forEach(function(b){b.classList.remove('active')});
    var tb = document.querySelector('.mtg[data-mid="'+mid+'"][data-mode="'+mode+'"]');
    if (tb) tb.classList.add('active');
  }
  document.querySelectorAll('.mtg').forEach(function(btn){
    btn.addEventListener('click', function(){
      var mid = this.dataset.mid;
      var mode = this.dataset.mode;
      var monthPanel = document.getElementById('mp_'+mid+'_month');
      var todayPanel = document.getElementById('mp_'+mid+'_today');
      if (!monthPanel || !todayPanel) return;
      monthPanel.style.display = mode==='month'?'block':'none';
      todayPanel.style.display = mode==='today'?'block':'none';
      document.querySelectorAll('.mtg[data-mid="'+mid+'"]').forEach(function(b){b.classList.remove('active')});
      this.classList.add('active');
    });
  });

  allChartData = u.daily_breakdown || [];
  window.__chartData = allChartData;
  renderChart();
}

// ===== Per-SK tabs =====
function isMainSk(skId) {
  if (!skListCache.length) return true;
  var mainId = null;
  for (var i=0;i<skListCache.length;i++) {
    if (skListCache[i].is_platform) { mainId = skListCache[i].id; break; }
  }
  if (mainId===null && skListCache.length) mainId = skListCache[0].id;
  return skId===mainId;
}

function mainSkId() {
  if (!skListCache.length) return null;
  for (var i=0;i<skListCache.length;i++) {
    if (skListCache[i].is_platform) return skListCache[i].id;
  }
  return skListCache[0].id;
}

function renderSkTabs(afterRefresh) {
  api.get_sk_pool().then(function(list){
    skListCache = list||[];
    buildSkTabs();
    if (afterRefresh) afterRefresh();
  }).catch(function(){
    document.getElementById('skTabs').innerHTML =
      '<button class="sk-tab" onclick="retrySkTabs()">SK 加载失败，点击重试</button>';
  });
}
window.retrySkTabs = renderSkTabs;

function buildSkTabs() {
  var h = '';
  if (!skListCache.length) {
    h = '<button class="sk-tab active" data-sk="">主账号</button>';
    activeSkId = null;
  } else {
    if (activeSkId===null) activeSkId = mainSkId();
    for (var j=0;j<skListCache.length;j++) {
      var s = skListCache[j];
      var cls = 'sk-tab' + (activeSkId===s.id ? ' active' : '');
      var badge = isMainSk(s.id) ? '<span class="sk-tab-badge">主</span>' : '';
      h += '<button class="'+cls+'" data-sk="'+esc(s.id)+'">'+
           esc(s.name||s.id)+badge+'</button>';
    }
  }
  document.getElementById('skTabs').innerHTML = h;
  document.querySelectorAll('.sk-tab').forEach(function(btn){
    btn.addEventListener('click', function(){
      activeSkId = this.dataset.sk || null;
      document.querySelectorAll('.sk-tab').forEach(function(b){b.classList.remove('active')});
      this.classList.add('active');
      applySkView();
    });
  });
  applySkView();
}

var _currentView = 'main';

function applySkView() {
  var platform = (activeSkId===null) || isMainSk(activeSkId);
  document.getElementById('platformView').style.display =
    platform ? 'block' : 'none';
  document.getElementById('skDetailView').style.display =
    platform ? 'none' : 'block';
  var viewKey = platform ? 'main' : ('sk:'+activeSkId);
  if (viewKey === _currentView) return;
  _currentView = viewKey;
  if (platform) refreshData();
  else loadSkDetail(activeSkId);
}

function skStatusHtml(s) {
  if (s.suspended) return '<span class="status-badge error">熔断</span>';
  if (!s.enabled) return '<span class="status-badge info">停用</span>';
  if (s.balance!=null && !s.is_available) {
    return '<span class="status-badge error">余额不足</span>';
  }
  return '<span class="status-badge success">正常</span>';
}

function loadSkDetail(skId) {
  var sk = null;
  for (var i=0;i<skListCache.length;i++) {
    if (skListCache[i].id===skId) { sk = skListCache[i]; break; }
  }
  if (!sk) return;
  document.getElementById('skDetailName').textContent = esc(sk.name||sk.id);
  document.getElementById('skDetailBalance').textContent =
    sk.balance==null ? '--' : '￥'+Number(sk.balance).toFixed(2);
  document.getElementById('skDetailToday').textContent =
    '￥'+(sk.today_cost||0).toFixed(2);
  document.getElementById('skDetailMonth').textContent =
    '￥'+(sk.month_cost||0).toFixed(2);
  document.getElementById('skDetailTokens').textContent = K(sk.today_tokens||0);
  document.getElementById('skDetailRequests').textContent =
    String(sk.today_requests||0);
  document.getElementById('skDetailStatus').innerHTML = skStatusHtml(sk);
  api.get_sk_detail(skId).then(function(d){
    if (!d) return;
    var bal = d.balance || {};
    var text = '余额：';
    if (bal.balance!=null) {
      text += '￥'+Number(bal.balance).toFixed(2);
      if (bal.topped_up_balance!=null || bal.granted_balance!=null) {
        text += '（充值 ￥'+(bal.topped_up_balance||0).toFixed(2)+
                ' / 赠金 ￥'+(bal.granted_balance||0).toFixed(2)+'）';
      }
    } else {
      text += '--（等待首次余额轮询，约 10 分钟内；或点顶部刷新）';
    }
    document.getElementById('skBalanceDetail').textContent = text;
    renderSkModelBreakdown(d.model_today||[]);
    renderSkMonthTotals(d.model_month||[]);
    renderSkConversations(d.conversations||[]);
  });
  var weightSum = 0;
  for (var j=0;j<skListCache.length;j++) {
    weightSum += parseInt(skListCache[j].weight)||0;
  }
  var target = weightSum>0 ? Math.round(((parseInt(sk.weight)||0)/weightSum)*100) : 0;
  document.getElementById('skDetailMeta').textContent =
    '权重 '+sk.weight+'（目标约占 '+target+'%）| 上限 日￥'+(sk.daily_cost_cap||0)+
    ' / 月￥'+(sk.monthly_cost_cap||0)+
    (sk.time_windows&&sk.time_windows.length?' | 时段 '+sk.time_windows.join(';'):'')+
    ' | 费用按价格表估算，余额为实时查询';
  api.get_sk_daily_series(skId).then(function(series){ renderSkChart(series||[]); });
}

function renderSkModelBreakdown(models) {
  var h = '';
  if (!models.length) {
    h = '<div class="sk-hint">今日暂无网关用量记录——Codex 接入网关并产生对话后，这里会显示按模型的实时用量。</div>';
  }
  for (var i=0;i<models.length;i++) {
    var m = models[i];
    var label = modelLabel(m.model);
    var miss = Math.max((m.input_tokens||0)-(m.cached_tokens||0), 0);
    h += '<div class="model-card" style="margin-bottom:6px;">';
    h += '<div class="model-name-row"><span class="model-name-title">'+esc(label)+
         '</span><span class="status-badge info">￥'+Number(m.cost||0).toFixed(2)+'</span></div>';
    h += '<div class="model-grid">';
    h += '<div class="token-item"><div class="token-label">输入·缓存命中</div>'+
         '<div class="token-value">'+K(m.cached_tokens||0)+'</div></div>';
    h += '<div class="token-item"><div class="token-label">输入·缓存未命中</div>'+
         '<div class="token-value">'+K(miss)+'</div></div>';
    h += '</div><div class="model-full">';
    h += '<div class="token-item"><div class="token-label">输出 token</div>'+
         '<div class="token-value">'+K(m.output_tokens||0)+'</div></div>';
    h += '<div class="token-item"><div class="token-label">命中率</div><div class="token-value">'+
         '<span class="hit-badge '+(m.hit_rate>=80?'high':(m.hit_rate>=50?'mid':''))+'">'+
         (m.hit_rate||0)+'%</span></div></div>';
    h += '</div></div>';
  }
  document.getElementById('skModelBreakdown').innerHTML = h;
}

function renderSkMonthTotals(monthModels) {
  var h = '';
  for (var i=0;i<monthModels.length;i++) {
    var m = monthModels[i];
    var label = modelLabel(m.model);
    h += esc(label)+' ￥'+Number(m.cost||0).toFixed(2)+'（'+K(m.tokens_total||0)+
         ' token）';
    if (i < monthModels.length-1) h += '　';
  }
  if (!h) return;
  document.getElementById('skMonthTotals').textContent = '本月合计：' + h;
}

function renderSkConversations(convs) {
  var h = '';
  if (!convs || !convs.length) {
    h = '<div class="sk-hint">暂无对话记录——网关产生流量后显示。</div>';
  }
  for (var i=0;i<convs.length;i++) {
    var c = convs[i];
    h += '<div class="sk-row">';
    h += '<div class="sk-row-head"><span class="sk-name">'+esc(c.title||c.fingerprint)+
         '</span><span>￥'+Number(c.cost||0).toFixed(4)+'</span></div>';
    h += '<div class="sk-meta">'+K(c.tokens||0)+' token | '+c.requests+
         ' 次 | '+esc(c.last_seen||'')+'</div>';
    h += '</div>';
  }
  document.getElementById('skConvList').innerHTML = h;
}

function renderRecentConversations(convs) {
  var el = document.getElementById('recentConvList');
  if (!el) return;
  var h = '';
  if (!convs || !convs.length) {
    h = '<div class="sk-hint">暂无对话记录——网关产生流量后显示。</div>';
  }
  var items = (convs || []).slice(0, 8);
  for (var i=0;i<items.length;i++) {
    var c = items[i];
    h += '<div class="sk-row">';
    h += '<div class="sk-row-head"><span class="sk-name">'+esc(c.title||c.fingerprint)+
         '</span><span>￥'+Number(c.cost||0).toFixed(4)+'</span></div>';
    h += '<div class="sk-meta">SK '+esc(c.sk_id)+' | '+K(c.tokens||0)+
         ' token | '+c.requests+' 次 | '+esc(c.last_seen||'')+'</div>';
    h += '</div>';
  }
  el.innerHTML = h;
}

function ensureClearConvsButton() {
  if (document.getElementById('btnClearConvs')) return;
  var list = document.getElementById('recentConvList');
  if (!list || !list.closest) return;
  var card = list.closest('.card');
  if (!card) return;
  var header = card.querySelector('.card-header');
  if (!header) return;
  var btn = document.createElement('button');
  btn.type = 'button';
  btn.id = 'btnClearConvs';
  btn.className = 'conv-clear-btn';
  btn.textContent = '清空';
  btn.addEventListener('click', onClearConvsClick);
  header.appendChild(btn);
}

function resetClearConvsButton() {
  clearArmed = false;
  if (clearResetTimer) {
    clearTimeout(clearResetTimer);
    clearResetTimer = null;
  }
  var btn = document.getElementById('btnClearConvs');
  if (btn) {
    btn.classList.remove('armed');
    btn.textContent = '清空';
  }
}

function onClearConvsClick() {
  var btn = document.getElementById('btnClearConvs');
  if (!clearArmed) {
    clearArmed = true;
    if (btn) {
      btn.classList.add('armed');
      btn.textContent = '再点一次清空';
    }
    clearResetTimer = setTimeout(resetClearConvsButton, 3000);
    return;
  }
  resetClearConvsButton();
  api.clear_conversations().then(function() {
    refreshRecentConversations();
    if (btn) {
      btn.textContent = '已清空';
      setTimeout(function(){ if (btn) btn.textContent = '清空'; }, 2000);
    }
  }).catch(function() {
    resetClearConvsButton();
  });
}

function renderSkChart(series) {
  var cvs = document.getElementById('skChartCanvas');
  if (!cvs) return;
  if (window.__skChart) { window.__skChart.destroy(); window.__skChart = null; }
  var labels = series.map(function(d){return d.day;});
  var values = series.map(function(d){return d.cost;});
  window.__skChart = new Chart(cvs, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        data: values,
        backgroundColor: values.map(function(v){
          return v>0.01 ? 'rgba(79,107,237,0.7)' : 'rgba(79,107,237,0.2)';
        }),
        borderColor: 'rgba(79,107,237,0.8)',
        borderWidth: 1,
        borderRadius: 4,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {display: false},
        tooltip: {
          backgroundColor: 'rgba(12,14,22,0.96)',
          titleColor: '#e4e8f0',
          bodyColor: '#b0b8cc',
          cornerRadius: 10,
          displayColors: false,
          callbacks: {label: function(ctx){return '￥'+ctx.raw.toFixed(4);}},
        },
      },
      scales: {
        x: {ticks: {color: '#6b6b80', font: {size: 10}}, grid: {display: false}, border: {display: false}},
        y: {
          ticks: {color: '#6b6b80', font: {size: 10}, callback: function(v){return '￥'+v;}},
          grid: {color: 'rgba(255,255,255,0.04)'},
          border: {display: false},
          beginAtZero: true,
        },
      },
    },
  });
}

function renderChart() {
  var cvs = document.getElementById('chartCanvas');
  if (!cvs) return;
  if (chart) { chart.destroy(); chart = null; }
  var full = window.__chartData || allChartData || [];
  var data;
  if (chartMode === 'week') {
    var today = new Date();
    var dow = today.getDay() || 7;
    var mon = new Date(today); mon.setDate(today.getDate() - dow + 1);
    var monStr = mon.toISOString().slice(5,10);
    var sun = new Date(mon); sun.setDate(mon.getDate() + 6);
    var sunStr = sun.toISOString().slice(5,10);
    data = full.filter(function(d){return d.date >= monStr && d.date <= sunStr});
  } else {
    data = full.slice();
  }
  var labels=[], values=[], modelData=[];
  for (var i=0;i<data.length;i++) { labels.push(data[i].date); values.push(data[i].cost); modelData.push(data[i].models||{}); }
  if (labels.length===0) {
    for (var k=6;k>=0;k--) { var dd=new Date(); dd.setDate(dd.getDate()-k); labels.push(('0'+(dd.getMonth()+1)).slice(-2)+'-'+('0'+dd.getDate()).slice(-2)); values.push(0); modelData.push({}); }
  }
  function pad(s,l){while(s.length<l)s+=' ';return s;}
  function modelLines(dayModels) {
    var longest = 0, mk;
    for (mk in dayModels) {
      if (!dayModels[mk]) continue;
      if (mk.length>longest) longest = mk.length;
    }
    var lines = [];
    for (mk in dayModels) {
      if (!dayModels[mk]) continue;
      lines.push(pad(mk+' ', longest+2)+'￥'+Number(dayModels[mk]).toFixed(4));
    }
    return lines;
  }
  var tickStep = Math.max(1, Math.ceil(data.length / 10));
  var showTicks = {};
  for (var ti=0; ti<data.length; ti+=tickStep) showTicks[ti] = true;
  showTicks[data.length-1] = true;
  chart = new Chart(cvs,{
    type:'bar',data:{labels:labels,datasets:[{data:values,backgroundColor:values.map(function(v){return v>0.5?'rgba(79,107,237,0.7)':'rgba(79,107,237,0.2)'}),borderColor:'rgba(79,107,237,0.8)',borderWidth:1,borderRadius:4,borderSkipped:false}]},
    options:{
      responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
      plugins:{legend:{display:false},tooltip:{backgroundColor:'rgba(12,14,22,0.96)',titleColor:'#e4e8f0',bodyColor:'#b0b8cc',borderColor:'rgba(79,107,237,0.35)',borderWidth:1,cornerRadius:10,padding:14,titleFont:{size:14,weight:'600'},bodyFont:{size:12,family:'"Segoe UI","Microsoft YaHei",monospace'},displayColors:false,callbacks:{title:function(ctx){return ctx[0].label},label:function(ctx){return ['合计 ￥'+ctx.raw.toFixed(4)].concat(modelLines(modelData[ctx.dataIndex]||{}))}}}},
      scales:{x:{ticks:{color:'#6b6b80',font:{size:10},autoSkip:false,callback:function(v){return showTicks[v]?(data[v]?data[v].date:''):''}},grid:{display:false},border:{display:false}},y:{ticks:{color:'#6b6b80',font:{size:10},callback:function(v){return '￥'+v}},grid:{color:'rgba(255,255,255,0.04)'},border:{display:false},beginAtZero:true}},
    },
  });
}

function startTimer(min) {
  if(timer)clearInterval(timer);
  timer=setInterval(refreshData,(min||10)*60000);
}

// ===== Single timer for all effects =====
var effectTimer = null;

function stopEffects() {
  if (effectTimer) { clearInterval(effectTimer); effectTimer = null; }
  // Remove all effect elements from both panels
  var all = document.querySelectorAll('.petal,.matrix-drop');
  for (var i=0;i<all.length;i++) { if(all[i].parentNode) all[i].parentNode.removeChild(all[i]); }
}

function startEffects() {
  stopEffects();
  var theme = document.body.className.replace('theme-','');
  if (theme === 'geek') {
    var app = document.getElementById('mainPanel').querySelector('#app');
    if (!app) return;
    var pool = 'async await const let var function return import export default class extends new try catch throw if else for while switch case break continue this super static get set map filter reduce find some every push pop shift unshift slice splice sort reverse split join replace match test exec then catch finally resolve reject all race'.split(' ');
    function snip() { var len=3+Math.floor(Math.random()*6);var p=[];for(var i=0;i<len;i++)p.push(pool[Math.floor(Math.random()*pool.length)]);return p.join(' ')+(Math.random()>0.5?'();':' {'); }
    function add() {
      var d = document.createElement('div'); d.className = 'matrix-drop';
      d.textContent = snip(); d.style.left = (2+Math.random()*86)+'%';
      d.style.animationDuration = (10+Math.random()*14)+'s';
      app.appendChild(d);
      setTimeout(function(){if(d.parentNode)d.remove()}, 26000);
    }
    for (var i=0;i<8;i++) { setTimeout(function(){add()}, i*600); }
    effectTimer = setInterval(add, 1500+Math.random()*2500);
  }
  if (theme === 'cute') {
    var app2 = document.getElementById('mainPanel').querySelector('#app');
    if (!app2) return;
    var colors = ['#e8849a','#f08ca8','#e8708a','#f598b0','#e87890','#f4849e'];
    function addPetal() {
      var p = document.createElement('div'); p.className = 'petal';
      var size = 5+Math.random()*8;
      p.style.cssText = 'width:'+size+'px;height:'+size+'px;background:'+colors[Math.floor(Math.random()*colors.length)]+';border-radius:50% 0 50% 0;left:'+Math.random()*92+'%;animation-duration:'+(7+Math.random()*10)+'s;animation-delay:0s';
      app2.appendChild(p);
      setTimeout(function(){if(p.parentNode)p.remove()}, 18000);
    }
    for (var i=0;i<12;i++) { setTimeout(function(){addPetal()}, i*400+Math.random()*600); }
    effectTimer = setInterval(addPetal, 1200+Math.random()*1500);
  }
}

// ===== Drag =====
var drag = {active:false,sx:0,sy:0,wx:0,wy:0,init:false};
document.addEventListener('mousedown',function(e){
  if(!e.target.closest('.titlebar'))return;
  if(e.target.closest('button')||e.target.closest('.titlebar-actions'))return;
  if(!drag.init){api.get_window_pos().then(function(p){if(p){drag.wx=p.x;drag.wy=p.y;drag.init=true}})}
  drag.active=true;drag.sx=e.screenX;drag.sy=e.screenY;e.preventDefault();
});
document.addEventListener('mousemove',function(e){
  if(!drag.active)return;
  var dx=e.screenX-drag.sx,dy=e.screenY-drag.sy;
  drag.sx=e.screenX;drag.sy=e.screenY;drag.wx+=dx;drag.wy+=dy;
  api.move_to(drag.wx,drag.wy);
});
document.addEventListener('mouseup',function(){drag.active=false});

// ===== Chart toggle =====
document.querySelectorAll('.ctg').forEach(function(el){
  el.addEventListener('click',function(){
    document.querySelectorAll('.ctg').forEach(function(b){b.classList.remove('active')});
    this.classList.add('active');
    chartMode = this.dataset.mode;
    document.getElementById('chartTitle').textContent = chartMode==='month'?'本月用量':'近七天用量';
    renderChart();
  });
});

// ===== Theme =====
function setTheme(name) {
  document.body.className = 'theme-'+name;
  document.querySelectorAll('.theme-opt').forEach(function(el){el.classList.toggle('active',el.dataset.theme===name)});
  startEffects();
}
window.setTheme = setTheme;

// ===== Buttons =====
function manualRefresh() {
  refreshData();
}
window.manualRefresh = manualRefresh;
document.getElementById('btnRefresh').addEventListener('click',manualRefresh);
document.getElementById('btnSettings').addEventListener('click',function(){showPanel('settings')});
document.getElementById('btnClose').addEventListener('click',function(){api.hide_window()});
document.querySelectorAll('.theme-opt').forEach(function(el){el.addEventListener('click',function(){setTheme(this.dataset.theme)})});

// ===== SK Management =====
var SK_MASK = '********';
var editingSkId = null;
var skPoolCache = [];

function esc(s) {
  return String(s==null?'':s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}

function showSkStatus(msg, type) {
  document.getElementById('skStatus').innerHTML =
    '<span class="status-badge '+type+'">'+msg+'</span>';
}

function loadSkPanel() {
  loadGatewayStatus();
  loadSkList();
  loadGlobalForm();
  loadConversations();
  loadEvents();
}

function loadGatewayStatus() {
  api.get_gateway_status().then(function(s){
    if(!s) return;
    var cx = s.codex || {};
    var hint = document.getElementById('codexStatus');
    if (!cx.exists) {
      hint.innerHTML = '<span class="status-badge error">未找到 Codex 配置</span>';
    } else if (cx.mode === 'gateway') {
      hint.innerHTML = '<span class="status-badge success">已接入网关</span> base_url: '+esc(cx.base_url)
        + (cx.backup ? '<br>备份: '+esc(cx.backup) : '');
    } else {
      hint.innerHTML = '<span class="status-badge info">当前直连</span> base_url: '+esc(cx.base_url||'');
    }
    document.getElementById('gatewayStatus').innerHTML =
      '运行: ' + (s.running
        ? '<span class="status-badge success">运行中</span>'
        : '<span class="status-badge error">未启动</span>')
      + ' 端口: ' + esc(s.port||s.gateway_port||'-')
      + ' 单对话阈值: ￥' + esc(s.conversation_cost_limit||0);
  });
}

function loadSkList() {
  api.get_sk_pool().then(function(list){
    skPoolCache = list||[];
    var h = '';
    if (!skPoolCache.length) h = '<div class="sk-hint">尚未添加 SK。</div>';
    for (var i=0;i<skPoolCache.length;i++) {
      var s = skPoolCache[i];
      var status = skStatusHtml(s);
      h += '<div class="sk-row">';
      h += '<div class="sk-row-head"><span class="sk-name">'+esc(s.name||s.id)+'</span><span>'+
           (s.is_default?'<span class="status-badge info">默认</span>':'')+
           (s.is_platform?'<span class="status-badge info">主</span>':'')+
           status+'</span></div>';
      h += '<div class="sk-meta">权重 '+esc(s.weight)+' | 今日 ￥'+(s.today_cost||0).toFixed(2)+
           ' | 余额 '+(s.balance==null?'--':'￥'+Number(s.balance).toFixed(2))+'</div>';
      h += '<div class="sk-meta">上限 日￥'+(s.daily_cost_cap||0)+' / 月￥'+(s.monthly_cost_cap||0)+
           (s.time_windows&&s.time_windows.length?' | 时段 '+esc(s.time_windows.join(';')):'')+'</div>';
      h += '<div class="sk-actions">';
      h += '<button class="btn btn-secondary btn-sm" onclick="editSk(\''+esc(s.id)+'\')">编辑</button>';
      h += '<button class="btn btn-secondary btn-sm" onclick="toggleSk(\''+esc(s.id)+'\')">'+
           (s.enabled?'停用':'启用')+'</button>';
      h += '<button class="btn btn-secondary btn-sm" id="del-'+esc(s.id)+'" '+
           'onclick="deleteSk(\''+esc(s.id)+'\')">删除</button>';
      h += '</div></div>';
    }
    document.getElementById('skList').innerHTML = h;
  });
}

function toggleSk(id) {
  for (var i=0;i<skPoolCache.length;i++) {
    if (skPoolCache[i].id===id) { skPoolCache[i].enabled = !skPoolCache[i].enabled; break; }
  }
  api.save_sk_pool(JSON.stringify(skPoolCache)).then(function(){
    loadSkList();
    renderSkTabs();
  });
}
window.toggleSk = toggleSk;

function deleteSk(id) {
  var btn = document.getElementById('del-'+id);
  if (!btn || btn.dataset.confirm !== '1') {
    if (btn) {
      btn.dataset.confirm = '1';
      btn.textContent = '确认删除';
    }
    setTimeout(function(){
      if (btn) { btn.dataset.confirm = '0'; btn.textContent = '删除'; }
    }, 3000);
    return;
  }
  var remaining = [];
  for (var i=0;i<skPoolCache.length;i++) {
    if (skPoolCache[i].id !== id) remaining.push(skPoolCache[i]);
  }
  api.save_sk_pool(JSON.stringify(remaining)).then(function(){
    showSkStatus('已删除 '+id,'success');
    if (activeSkId === id) activeSkId = null;
    loadSkList();
    renderSkTabs();
  });
}
window.deleteSk = deleteSk;

function editSk(id) {
  var s = null;
  for (var i=0;i<skPoolCache.length;i++) {
    if (skPoolCache[i].id===id) { s = skPoolCache[i]; break; }
  }
  if (!s) return;
  editingSkId = id;
  document.getElementById('skFormTitle').textContent = '编辑 SK：'+s.name;
  document.getElementById('skName').value = s.name||'';
  document.getElementById('skApiKey').value = s.api_key||'';
  document.getElementById('skWeight').value = s.weight||1;
  document.getElementById('skDailyCap').value = s.daily_cost_cap||'';
  document.getElementById('skMonthlyCap').value = s.monthly_cost_cap||'';
  document.getElementById('skWindows').value = (s.time_windows||[]).join('; ');
  document.getElementById('skDefault').checked = !!s.is_default;
  document.getElementById('skPlatform').checked = !!s.is_platform;
  document.getElementById('skEnabled').checked = s.enabled!==false;
  document.getElementById('skFormCard').style.display = 'block';
}
window.editSk = editSk;

function addSk() {
  editingSkId = null;
  document.getElementById('skFormTitle').textContent = '新增 SK';
  ['skName','skApiKey','skDailyCap','skMonthlyCap','skWindows'].forEach(function(id){
    document.getElementById(id).value = '';
  });
  document.getElementById('skWeight').value = 1;
  document.getElementById('skDefault').checked = false;
  document.getElementById('skPlatform').checked = false;
  document.getElementById('skEnabled').checked = true;
  document.getElementById('skFormCard').style.display = 'block';
}

function saveSk() {
  var name = document.getElementById('skName').value.trim();
  var rawKey = document.getElementById('skApiKey').value.trim();
  if (!name) { showSkStatus('请填写名称','error'); return; }
  var entry = {
    id: editingSkId || ('sk-' + Date.now().toString(36)),
    name: name,
    api_key: rawKey,
    weight: parseInt(document.getElementById('skWeight').value)||1,
    daily_cost_cap: parseFloat(document.getElementById('skDailyCap').value)||0,
    monthly_cost_cap: parseFloat(document.getElementById('skMonthlyCap').value)||0,
    time_windows: document.getElementById('skWindows').value
      .split(';').map(function(t){return t.trim();}).filter(Boolean),
    is_default: document.getElementById('skDefault').checked,
    is_platform: document.getElementById('skPlatform').checked,
    enabled: document.getElementById('skEnabled').checked,
  };
  if (editingSkId) {
    for (var i=0;i<skPoolCache.length;i++) {
      if (skPoolCache[i].id===editingSkId) {
        if (!rawKey || rawKey===SK_MASK) entry.api_key = skPoolCache[i].api_key;
        skPoolCache[i] = entry;
        break;
      }
    }
  } else {
    skPoolCache.push(entry);
  }
  api.save_sk_pool(JSON.stringify(skPoolCache)).then(function(){
    showSkStatus('已保存','success');
    document.getElementById('skFormCard').style.display = 'none';
    loadSkList();
    renderSkTabs();
  });
}

function loadGlobalForm() {
  api.get_gateway_status().then(function(s){
    if (!s) return;
    document.getElementById('gwPort').value = s.gateway_port||8787;
    document.getElementById('convLimit').value = s.conversation_cost_limit||5;
    document.getElementById('balancePoll').value = s.balance_poll_minutes||10;
    priceTable = s.price_table || {};
    if (!priceTable._peak) priceTable._peak = {};
    document.getElementById('peakWindows').value =
      (priceTable._peak_windows||['09:00-12:00','14:00-18:00']).join('; ');
    ensureModelNames(function(){
      buildPriceModelOptions();
      loadPriceForm();
    });
  });
}

// ===== Per-model price table =====
var priceTable = {};
var PRICE_MODEL_DEFAULT = 'default';

function priceModelKey() {
  var sel = document.getElementById('priceModel');
  return (sel && sel.value) ? sel.value : PRICE_MODEL_DEFAULT;
}

function buildPriceModelOptions() {
  var sel = document.getElementById('priceModel');
  if (!sel) return;
  var h = '';
  for (var i=0;i<allModelNames.length;i++) {
    h += '<option value="'+esc(allModelNames[i])+'">'+esc(allModelNames[i])+'</option>';
  }
  h += '<option value="'+PRICE_MODEL_DEFAULT+'">其他模型（默认价）</option>';
  sel.innerHTML = h;
  sel.addEventListener('change', function(){ loadPriceForm(); });
}

function readPriceInputs() {
  return {
    off: {
      cache_hit: parseFloat(document.getElementById('priceHit').value)||0,
      cache_miss: parseFloat(document.getElementById('priceMiss').value)||0,
      output: parseFloat(document.getElementById('priceOut').value)||0,
    },
    peak: {
      cache_hit: parseFloat(document.getElementById('peakHit').value)||0,
      cache_miss: parseFloat(document.getElementById('peakMiss').value)||0,
      output: parseFloat(document.getElementById('peakOut').value)||0,
    },
  };
}

function commitPriceForm() {
  var prices = readPriceInputs();
  var key = priceModelKey();
  priceTable[key] = prices.off;
  if (!priceTable._peak) priceTable._peak = {};
  priceTable._peak[key] = prices.peak;
}

function loadPriceForm() {
  var key = priceModelKey();
  var fallback = priceTable[PRICE_MODEL_DEFAULT] || {};
  var peakFallback = (priceTable._peak||{})[PRICE_MODEL_DEFAULT] || {};
  var off = priceTable[key] || fallback;
  var peak = (priceTable._peak||{})[key] || peakFallback;
  document.getElementById('priceHit').value = off.cache_hit!=null?off.cache_hit:0;
  document.getElementById('priceMiss').value = off.cache_miss!=null?off.cache_miss:0;
  document.getElementById('priceOut').value = off.output!=null?off.output:0;
  document.getElementById('peakHit').value = peak.cache_hit!=null?peak.cache_hit:0;
  document.getElementById('peakMiss').value = peak.cache_miss!=null?peak.cache_miss:0;
  document.getElementById('peakOut').value = peak.output!=null?peak.output:0;
  document.getElementById('priceHint').textContent = key===PRICE_MODEL_DEFAULT
    ? '当前编辑：未单独配置的模型（默认价）'
    : '当前编辑：'+key+(priceTable[key]?'':'（沿用默认价，保存后单独生效）');
}

function saveGlobal() {
  commitPriceForm();
  var windows = document.getElementById('peakWindows').value
    .split(';').map(function(t){return t.trim();}).filter(Boolean);
  priceTable._peak_windows = windows;
  if (!priceTable._peak_weekdays) priceTable._peak_weekdays = [0, 1, 2, 3, 4];
  var data = {
    gateway_port: parseInt(document.getElementById('gwPort').value)||8787,
    conversation_cost_limit: parseFloat(document.getElementById('convLimit').value)||5,
    balance_poll_minutes: parseInt(document.getElementById('balancePoll').value)||10,
    price_table: priceTable,
  };
  api.save_settings(JSON.stringify(data)).then(function(){
    api.reload_gateway_config().then(function(){
      showSkStatus('全局配置已保存并生效','success');
      loadGatewayStatus();
    });
  });
}

function applyGateway() {
  api.apply_codex_gateway().then(function(st){
    loadGatewayStatus();
    showSkStatus('已写入 Codex 配置，请重启一次 Codex 生效（之后切换 SK 无需重启）','success');
  });
}

function restoreGateway() {
  api.restore_codex_config().then(function(r){
    loadGatewayStatus();
    showSkStatus(r&&r.restored ? '已还原直连，重启 Codex 生效' : '未找到备份，无法还原','info');
  });
}

function loadConversations() {
  api.get_conversations().then(function(list){
    var h = '';
    if (!list || !list.length) h = '<div class="sk-hint">暂无对话记录</div>';
    for (var i=0;i<list.length;i++) {
      var c = list[i];
      h += '<div class="sk-row">';
      h += '<div class="sk-row-head"><span class="sk-name">'+esc(c.title||c.fingerprint)+'</span>'+
           '<span class="status-badge info">'+esc(c.sk_id)+'</span></div>';
      h += '<div class="sk-meta">￥'+Number(c.cost||0).toFixed(4)+' | '+K(c.tokens||0)+
           ' token | '+c.requests+' 次 | '+esc(c.last_seen||'')+'</div>';
      h += '</div>';
    }
    document.getElementById('convList').innerHTML = h;
  });
}

function loadEvents() {
  api.get_events(50).then(function(list){
    var h = '';
    if (!list || !list.length) h = '<div class="sk-hint">暂无事件</div>';
    for (var i=0;i<list.length;i++) {
      var e = list[i];
      var tone = e.kind==='server_error' ? 'error'
        : (e.kind==='key_switched' ? 'info' : 'success');
      h += '<div class="sk-row">';
      h += '<div class="sk-row-head"><span class="status-badge '+tone+'">'+esc(e.kind)+'</span>'+
           '<span>'+esc(e.ts||'')+'</span></div>';
      h += '<div class="sk-meta">'+(e.sk_id?'SK '+esc(e.sk_id)+' | ':'')+esc(e.message)+'</div>';
      h += '</div>';
    }
    document.getElementById('eventList').innerHTML = h;
  });
}

window._onNotify = function(n) {
  var el = document.getElementById('notifyBanner');
  el.textContent = (n&&n.message)||'';
  el.style.display = 'block';
  clearTimeout(el._t);
  el._t = setTimeout(function(){ el.style.display = 'none'; }, 8000);
};

document.getElementById('btnOpenSk').addEventListener('click',function(){showPanel('sk')});
document.getElementById('btnSkBack').addEventListener('click',function(){showPanel('settings')});
document.getElementById('btnAddSk').addEventListener('click',addSk);
document.getElementById('btnSaveSk').addEventListener('click',saveSk);
document.getElementById('btnCancelSk').addEventListener('click',function(){
  document.getElementById('skFormCard').style.display = 'none';
});
document.getElementById('btnApplyGateway').addEventListener('click',applyGateway);
document.getElementById('btnRestoreGateway').addEventListener('click',restoreGateway);
document.getElementById('btnSaveGlobal').addEventListener('click',saveGlobal);

// ===== Model filter (names come from the platform response) =====
function renderModelFilter() {
  var box = document.getElementById('modelFilterList');
  if (!box) return;
  var h = '';
  if (!allModelNames.length) {
    h = '<div class="sk-hint">未获取到模型列表——点击右上角刷新后重试。</div>';
  }
  for (var i=0;i<allModelNames.length;i++) {
    var name = allModelNames[i];
    var checked = hiddenModels.indexOf(name)<0 ? ' checked' : '';
    h += '<label class="checkbox-row"><input type="checkbox" data-model="'+
         esc(name)+'"'+checked+'><span>'+esc(name)+'</span></label>';
  }
  box.innerHTML = h;
  var boxes = box.querySelectorAll('input[type=checkbox]');
  for (var j=0;j<boxes.length;j++) boxes[j].addEventListener('change', onModelToggle);
  document.getElementById('modelFilterHint').textContent = allModelNames.length
    ? '平台共 '+allModelNames.length+' 个模型；主界面只显示当日有调用记录的模型，取消勾选可永久隐藏' : '';
}

function onModelToggle() {
  var name = this.dataset.model;
  var index = hiddenModels.indexOf(name);
  if (this.checked && index>=0) hiddenModels.splice(index,1);
  else if (!this.checked && index<0) hiddenModels.push(name);
}

function loadModelNames() {
  ensureModelNames(function(){ renderModelFilter(); });
}

function ensureModelNames(callback) {
  if (allModelNames.length) { if (callback) callback(); return; }
  api.get_usage_data().then(function(d){
    var models = ((d||{}).usage||{}).models || {};
    allModelNames = [];
    for (var name in models) allModelNames.push(name);
    if (callback) callback();
  }).catch(function(){ if (callback) callback(); });
}

function loadAutoStartStatus() {
  api.get_autostart_status().then(function(s){
    if (!s) return;
    renderAutoStartStatus(s);
  }).catch(function(){});
}

function renderAutoStartStatus(s) {
  var box = document.getElementById('autoStartStatus');
  if (!box) return;
  if (!s.enabled) { box.textContent = '未启用'; return; }
  var parts = ['注册表启动项：'+(s.registry_ok?'已写入':'未写入'),
               '启动文件夹快捷方式：'+(s.shortcut_ok?'已写入':'未写入')];
  if (!s.target_exists) parts.push('目标文件不存在');
  box.textContent = parts.join(' | ');
}

// ===== Settings =====
function loadForm() {
  api.get_settings().then(function(s){
    if(!s)return;
    document.getElementById('platformToken').value = s.platform_token || '';
    document.getElementById('platformCookie').value = s.platform_cookie || '';
    document.getElementById('refreshInterval').value = String(s.refresh_interval_minutes||10);
    T('toggleAutoStart',!!s.auto_start);
    T('toggleAlert',!!s.alert_enabled);
    document.getElementById('alertBalance').value = s.alert_balance_threshold||10;
    document.getElementById('alertDaily').value = s.alert_daily_threshold||50;
    if(s.hidden_models)hiddenModels=s.hidden_models.slice();
    renderModelFilter();
    loadModelNames();
    loadAutoStartStatus();
    var cur=document.body.className.replace('theme-','')||'glass';
    document.querySelectorAll('.theme-opt').forEach(function(el){el.classList.toggle('active',el.dataset.theme===cur)});
    U();
  }).catch(function(){});
}
function T(id,on){var e=document.getElementById(id);if(on)e.classList.add('active');else e.classList.remove('active');}
function O(id){return document.getElementById(id).classList.contains('active');}
function U(){document.getElementById('alertSettings').style.display = O('toggleAlert')?'block':'none';}

document.querySelectorAll('.toggle-switch').forEach(function(el){el.addEventListener('click',function(){this.classList.toggle('active');U()})});
document.getElementById('btnToggleKey').addEventListener('click',function(){var i=document.getElementById('platformToken');i.type=i.type==='password'?'text':'password'});
document.getElementById('btnTestKey').addEventListener('click',function(){
  var k=document.getElementById('platformToken').value.trim();
  var c=document.getElementById('platformCookie').value.trim();
  if(!k){X('请输入平台Token','error');return;}
  X('测试中...','info');
  api.test_platform_token(k,c).then(function(r){X(r&&r.valid?'连接成功':'连接失败',r&&r.valid?'success':'error')});
});
function X(m,t){document.getElementById('keyStatus').innerHTML='<span class="status-badge '+t+'">'+m+'</span>';}

document.getElementById('btnSave').addEventListener('click',function(){
  var d={
    platform_token:document.getElementById('platformToken').value.trim(),
    platform_cookie:document.getElementById('platformCookie').value.trim(),
    refresh_interval_minutes:parseInt(document.getElementById('refreshInterval').value),
    auto_start:O('toggleAutoStart'),alert_enabled:O('toggleAlert'),
    alert_balance_threshold:parseFloat(document.getElementById('alertBalance').value)||10,
    alert_daily_threshold:parseFloat(document.getElementById('alertDaily').value)||50,
    theme:document.body.className.replace('theme-',''),hidden_models:hiddenModels.slice(),
  };
  api.save_settings(JSON.stringify(d)).then(function(r){
    var ok=!r||r.success!==false;
    document.getElementById('saveStatus').innerHTML='<span class="status-badge '+
      (ok?'success':'error')+'">'+(ok?'已保存':'保存失败：'+esc(r.error||''))+'</span>';
    if(r&&r.auto_start)renderAutoStartStatus(r.auto_start);
    if(window._onCfg)window._onCfg(d);
    startTimer(d.refresh_interval_minutes);
    setTimeout(function(){document.getElementById('saveStatus').innerHTML=''},4000);
  });
});

document.getElementById('btnBack').addEventListener('click',function(){showPanel('main')});

// ===== Init =====
api.get_settings().then(function(s){
  if(s){
    if(s.hidden_models)hiddenModels=s.hidden_models.slice();
    setTheme(s.theme||'glass');
    startTimer(s.refresh_interval_minutes||10);
  }
});
refreshData();
renderSkTabs();
ensureClearConvsButton();
startRecentTimer(5);
window._onCfg = function(d){
  if(d&&d.refresh_interval_minutes)startTimer(d.refresh_interval_minutes);
  if(d&&d.theme)setTheme(d.theme);
  if(d&&d.hidden_models)hiddenModels=d.hidden_models.slice();
  refreshData();
};

} // end setupApp
