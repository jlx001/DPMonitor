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

var visibleModels = ['deepseek-v4-flash', 'deepseek-v4-pro'];
var chart = null, timer = null;
var allChartData = [];
var chartMode = 'week';

function showPanel(name) {
  document.getElementById('mainPanel').style.display = name==='settings'?'none':'block';
  document.getElementById('settingsPanel').style.display = name==='settings'?'block':'none';
  if (name==='settings') loadForm();
}
window.showPanel = showPanel;

// ===== Data =====
function refreshData() {
  api.get_usage_data().then(function(d) {
    if (!d) return renderAll({});
    if (d.error && d.error==='no_token') return renderAll({});
    renderAll(d);
  }).catch(function(){ renderAll({}); });
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

  var models = u.models || {}, todayModels = u.today_models || {};
  var modelLabels = {'deepseek-v4-flash':'V4 Flash','deepseek-v4-pro':'V4 Pro'};
  var savedToggles = {};
  document.querySelectorAll('.mtg.active').forEach(function(b){savedToggles[b.dataset.mid]=b.dataset.mode});
  var h = '';
  for (var i=0;i<visibleModels.length;i++) {
    var mk = visibleModels[i];
    var ms = models[mk] || {}, ts = todayModels[mk] || {};
    var lbl = modelLabels[mk] || mk;
    var mid = mk.replace(/[^a-z0-9]/g,'_');
    h += '<div class="card model-card">';
    h += '<div class="model-name-row">';
    h += '<span class="model-name-title">'+S('zap',18)+' '+lbl+'</span>';
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
  document.getElementById('modelCards').innerHTML = h;
  for (var mid in savedToggles) {
    var mode = savedToggles[mid];
    document.getElementById('mp_'+mid+'_month').style.display = mode==='month'?'block':'none';
    document.getElementById('mp_'+mid+'_today').style.display = mode==='today'?'block':'none';
    document.querySelectorAll('.mtg[data-mid="'+mid+'"]').forEach(function(b){b.classList.remove('active')});
    var tb = document.querySelector('.mtg[data-mid="'+mid+'"][data-mode="'+mode+'"]');
    if (tb) tb.classList.add('active');
  }
  document.querySelectorAll('.mtg').forEach(function(btn){
    btn.addEventListener('click', function(){
      var mid = this.dataset.mid;
      var mode = this.dataset.mode;
      document.getElementById('mp_'+mid+'_month').style.display = mode==='month'?'block':'none';
      document.getElementById('mp_'+mid+'_today').style.display = mode==='today'?'block':'none';
      document.querySelectorAll('.mtg[data-mid="'+mid+'"]').forEach(function(b){b.classList.remove('active')});
      this.classList.add('active');
    });
  });

  allChartData = u.daily_breakdown || [];
  window.__chartData = allChartData;
  renderChart();
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
  var modelLabels = {'deepseek-v4-flash':'V4 Flash','deepseek-v4-pro':'V4 Pro'};
  var maxNameLen = 0;
  Object.values(modelLabels).forEach(function(l){if(l.length>maxNameLen)maxNameLen=l.length});
  function pad(s,l){while(s.length<l)s+=' ';return s;}
  var tickStep = Math.max(1, Math.ceil(data.length / 10));
  var showTicks = {};
  for (var ti=0; ti<data.length; ti+=tickStep) showTicks[ti] = true;
  showTicks[data.length-1] = true;
  chart = new Chart(cvs,{
    type:'bar',data:{labels:labels,datasets:[{data:values,backgroundColor:values.map(function(v){return v>0.5?'rgba(79,107,237,0.7)':'rgba(79,107,237,0.2)'}),borderColor:'rgba(79,107,237,0.8)',borderWidth:1,borderRadius:4,borderSkipped:false}]},
    options:{
      responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
      plugins:{legend:{display:false},tooltip:{backgroundColor:'rgba(12,14,22,0.96)',titleColor:'#e4e8f0',bodyColor:'#b0b8cc',borderColor:'rgba(79,107,237,0.35)',borderWidth:1,cornerRadius:10,padding:14,titleFont:{size:14,weight:'600'},bodyFont:{size:12,family:'"Segoe UI","Microsoft YaHei",monospace'},displayColors:false,callbacks:{title:function(ctx){return ctx[0].label},label:function(ctx){var md=modelData[ctx.dataIndex];var lines=['合计 ￥'+ctx.raw.toFixed(4)];for(var mk in md){if(!md[mk])continue;var l=modelLabels[mk]||mk;lines.push(pad(l+' ',maxNameLen+2)+'￥'+Number(md[mk]).toFixed(4))}return lines}}}},
      scales:{x:{ticks:{color:'#6b6b80',font:{size:10},autoSkip:false,callback:function(v){return showTicks[v]?(data[v]?data[v].date:''):''}},grid:{display:false},border:{display:false}},y:{ticks:{color:'#6b6b80',font:{size:10},callback:function(v){return '￥'+v}},grid:{color:'rgba(255,255,255,0.04)'},border:{display:false},beginAtZero:true}},
    },
  });
}

function startTimer(min) { if(timer)clearInterval(timer); timer=setInterval(refreshData,(min||10)*60000); }

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
document.getElementById('btnRefresh').addEventListener('click',refreshData);
document.getElementById('btnSettings').addEventListener('click',function(){showPanel('settings')});
document.getElementById('btnClose').addEventListener('click',function(){api.hide_window()});
document.querySelectorAll('.theme-opt').forEach(function(el){el.addEventListener('click',function(){setTheme(this.dataset.theme)})});

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
    if(s.visible_models){visibleModels=s.visible_models.slice();document.getElementById('modelFlash').checked=visibleModels.indexOf('deepseek-v4-flash')>=0;document.getElementById('modelPro').checked=visibleModels.indexOf('deepseek-v4-pro')>=0}
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

document.getElementById('modelFlash').addEventListener('change',function(){
  if(this.checked&&visibleModels.indexOf('deepseek-v4-flash')<0)visibleModels.push('deepseek-v4-flash');
  else{var i=visibleModels.indexOf('deepseek-v4-flash');if(i>=0)visibleModels.splice(i,1)}
});
document.getElementById('modelPro').addEventListener('change',function(){
  if(this.checked&&visibleModels.indexOf('deepseek-v4-pro')<0)visibleModels.push('deepseek-v4-pro');
  else{var i=visibleModels.indexOf('deepseek-v4-pro');if(i>=0)visibleModels.splice(i,1)}
});

document.getElementById('btnSave').addEventListener('click',function(){
  var d={
    platform_token:document.getElementById('platformToken').value.trim(),
    platform_cookie:document.getElementById('platformCookie').value.trim(),
    refresh_interval_minutes:parseInt(document.getElementById('refreshInterval').value),
    auto_start:O('toggleAutoStart'),alert_enabled:O('toggleAlert'),
    alert_balance_threshold:parseFloat(document.getElementById('alertBalance').value)||10,
    alert_daily_threshold:parseFloat(document.getElementById('alertDaily').value)||50,
    theme:document.body.className.replace('theme-',''),visible_models:visibleModels.slice(),
  };
  api.save_settings(JSON.stringify(d)).then(function(){
    document.getElementById('saveStatus').innerHTML='<span class="status-badge success">已保存</span>';
    if(window._onCfg)window._onCfg(d);
    startTimer(d.refresh_interval_minutes);
    setTimeout(function(){document.getElementById('saveStatus').innerHTML=''},3000);
  });
});

document.getElementById('btnBack').addEventListener('click',function(){showPanel('main')});

// ===== Init =====
api.get_settings().then(function(s){
  if(s){
    if(s.visible_models)visibleModels=s.visible_models.slice();
    setTheme(s.theme||'glass');
    startTimer(s.refresh_interval_minutes||10);
  }
});
refreshData();
window._onCfg = function(d){
  if(d&&d.refresh_interval_minutes)startTimer(d.refresh_interval_minutes);
  if(d&&d.theme)setTheme(d.theme);
  if(d&&d.visible_models)visibleModels=d.visible_models.slice();
  refreshData();
};

} // end setupApp
