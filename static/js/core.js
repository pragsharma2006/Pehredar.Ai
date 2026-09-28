/* Pehredar.ai — core: state, WebSocket, tiles, evidence log, alerts, router, modals */
'use strict';
// Missing elements return an inert stub, so async loaders that finish after the user has
// left a page don't throw when they update it.
const _NULL_FNS = ['querySelector', 'querySelectorAll', 'addEventListener', 'insertAdjacentHTML', 'remove', 'toggle', 'add', 'contains', 'click', 'scrollIntoView', 'getContext'];
const _NULL_EL = new Proxy({}, {
  get(t, k) {
    if (typeof k === 'symbol') return undefined;
    if (k === 'classList' || k === 'style' || k === 'dataset') return _NULL_EL;
    return _NULL_FNS.includes(k) ? () => null : undefined;
  },
  set() { return true; },
});
const $ = (s, r = document) => (r && r.querySelector(s)) || _NULL_EL;
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const TZ = 'Asia/Kolkata';
const fmtT = ts => new Date(ts * 1000).toLocaleTimeString('en-GB', {timeZone: TZ, hour12: false});
const fmtDT = ts => new Date(ts * 1000).toLocaleString('en-GB', {timeZone: TZ, hour12: false, day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit'});
const fmtISO = iso => iso ? iso.replace('T', ' ').slice(0, 23) + ' IST' : '—';
const ago = ts => { const s = Date.now() / 1000 - ts; return s < 60 ? `${s | 0}s ago` : s < 3600 ? `${(s / 60) | 0}m ago` : s < 86400 ? `${(s / 3600) | 0}h ago` : `${(s / 86400) | 0}d ago`; };
const shortHash = h => h ? h.slice(0, 12) : '—';
const num = (v, d = 0) => v == null || isNaN(v) ? '—' : Number(v).toFixed(d);
const SEV_ORDER = {critical: 0, high: 1, medium: 2, info: 3};

const S = {
  cams: {}, order: [], tick: null, models: {}, events: [], evFilter: 'all', grid: 3, gridPage: 0, page: null,
  dashModule: 'human', sound: true, operator: null, sinks: {}, lastUrl: {}, focus: null, settings: null,
  anpr: {job: null, stages: [], recent: []}, vehicleFeed: [], faceFeed: [], netLog: [], edge: {}, sync: {},
  meta: {}, integrity: null, listeners: {}, pageOff: [], charts: [], bannerAt: 0, toggles: {}, interacted: false,
};
['pointerdown', 'keydown'].forEach(t => addEventListener(t, () => { S.interacted = true; }, {once: true, capture: true}));

const MOD = {
  human: {name: 'Human Tracking', icon: 'person', tag: 'YOLOv8n + ByteTrack'},
  vehicle: {name: 'Vehicle Detection', icon: 'car', tag: 'YOLOv8 + colour/speed'},
  face: {name: 'Face Detection', icon: 'face', tag: 'YuNet + SFace'},
  anpr: {name: 'ANPR', icon: 'plate', tag: 'anpr_best.pt + plate OCR'},
  fence: {name: 'Virtual Fence', icon: 'fence', tag: 'Zones · tripwires'},
  activity: {name: 'Suspicious Activity', icon: 'activity', tag: 'Behaviour rules'},
  night: {name: 'Night Vision', icon: 'moon', tag: 'CLAHE · MOG2'},
  network: {name: 'Network Health', icon: 'wifi', tag: 'Adaptive streaming'},
};
const MOD_ORDER = ['human', 'vehicle', 'face', 'anpr', 'fence', 'activity', 'night', 'network'];

const IC = {
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  camera: '<path d="M3 7h11a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H3z"/><path d="M16 10l5-3v10l-5-3"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
  log: '<path d="M5 3h10l4 4v14H5z"/><path d="M9 11h7M9 15h7M9 7h3"/>',
  car: '<path d="M5 16l1.5-5.5A2 2 0 0 1 8.4 9h7.2a2 2 0 0 1 1.9 1.5L19 16"/><rect x="3" y="15" width="18" height="4" rx="1.5"/><circle cx="7" cy="19.5" r="1.5"/><circle cx="17" cy="19.5" r="1.5"/>',
  face: '<circle cx="12" cy="12" r="9"/><circle cx="9" cy="10" r=".8" fill="currentColor"/><circle cx="15" cy="10" r=".8" fill="currentColor"/><path d="M8.5 15c1.5 1.5 5.5 1.5 7 0"/>',
  map: '<path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2z"/><path d="M9 4v14M15 6v14"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  wifi: '<path d="M2 8.5a15 15 0 0 1 20 0M5.5 12a10 10 0 0 1 13 0M9 15.5a5 5 0 0 1 6 0"/><circle cx="12" cy="19" r="1.2" fill="currentColor"/>',
  plug: '<path d="M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0z"/><path d="M12 18v4"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
  person: '<circle cx="12" cy="6.5" r="3"/><path d="M6 21v-3a6 6 0 0 1 12 0v3"/>',
  plate: '<rect x="2.5" y="7" width="19" height="10" rx="2"/><path d="M5.5 7v10M8.5 12h10"/>',
  fence: '<path d="M4 21V7l2-3 2 3v14M16 21V7l2-3 2 3v14M4 11h16M4 17h16M10 21V7l2-3 2 3v14"/>',
  activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  moon: '<path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z"/>',
  soundOn: '<path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11"/>',
  soundOff: '<path d="M4 9v6h4l5 4V5L8 9z"/><path d="M17 9l5 6M22 9l-5 6"/>',
  expand: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
  users: '<circle cx="9" cy="7" r="3"/><path d="M3 21v-2a6 6 0 0 1 12 0v2M16 3.5a3 3 0 0 1 0 6M21 21v-2a5 5 0 0 0-4-4.9"/>',
};
const icon = (n, cls = '') => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${IC[n] || ''}</svg>`;

// ------------------------------------------------------------------ api
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let e = null;
    try { e = await r.json(); } catch (_) { /* not json */ }
    throw new Error((e && e.error) || `${r.status} ${r.statusText}`);
  }
  return (r.headers.get('content-type') || '').includes('json') ? r.json() : r;
}
const post = (p, b) => api(p, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(b || {})});

// ------------------------------------------------------------------ events bus (client)
function on(type, fn) { (S.listeners[type] ||= new Set()).add(fn); return () => S.listeners[type].delete(fn); }
function emit(type, d) { (S.listeners[type] || []).forEach(fn => { try { fn(d); } catch (e) { console.error(e); } }); }
const pageOn = (t, fn) => S.pageOff.push(on(t, fn));
const pageEvery = (fn, ms) => { const id = setInterval(fn, ms); S.pageOff.push(() => clearInterval(id)); };
const pageChart = c => { S.charts.push(c); return c; };

// ------------------------------------------------------------------ websocket
let WS = null, wsBackoff = 500, subKey = '';
function wsConnect() {
  WS = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
  WS.binaryType = 'arraybuffer';
  WS.onopen = () => { wsBackoff = 500; subKey = ''; syncSubs(); };
  WS.onclose = () => { setTimeout(wsConnect, wsBackoff); wsBackoff = Math.min(8000, wsBackoff * 2); };
  WS.onmessage = m => {
    if (typeof m.data !== 'string') return onFrame(m.data);
    let d; try { d = JSON.parse(m.data); } catch (_) { return; }
    const h = WSH[d.type];
    if (h) h(d);
    emit(d.type, d);
  };
}
function onFrame(buf) {
  const u8 = new Uint8Array(buf);
  if (u8[0] !== 70) return;
  const cid = S.order[u8[1]];
  const sinks = S.sinks[cid];
  if (!sinks || !sinks.size) return;
  const url = URL.createObjectURL(new Blob([u8.subarray(2)], {type: 'image/jpeg'}));
  sinks.forEach(img => { img.src = url; });
  const old = S.lastUrl[cid];
  S.lastUrl[cid] = url;
  if (old) setTimeout(() => URL.revokeObjectURL(old), 1500);
}
function addSink(cid, img) { (S.sinks[cid] ||= new Set()).add(img); queueSync(); }
function dropSinks(root) {
  for (const cid in S.sinks) S.sinks[cid].forEach(img => { if (!root || root.contains(img)) S.sinks[cid].delete(img); });
  queueSync();
}
let syncT = null;
function queueSync() { clearTimeout(syncT); syncT = setTimeout(syncSubs, 30); }
function syncSubs() {
  const subscribe = Object.keys(S.sinks).filter(c => S.sinks[c].size);
  const maxw = {1: 1280, 2: 720, 3: 480, 4: 400}[S.grid] || 480;
  const key = JSON.stringify([subscribe.sort(), S.focus, maxw]);
  if (!WS || WS.readyState !== 1 || key === subKey) return;
  subKey = key;
  WS.send(JSON.stringify({subscribe, focus: S.focus, maxw}));
}

const WSH = {
  hello(d) {
    const changed = JSON.stringify(d.cameras) !== JSON.stringify(S.order);
    S.order = d.cameras;
    if (changed && Object.keys(S.cams).length && d.cameras.some(c => !S.cams[c])) refreshCams().then(() => go());
    subKey = ''; syncSubs();
  },
  tick(d) {
    S.tick = d;
    S.toggles = d.toggles || S.toggles;
    renderHeader(); updateTiles(); updateKpis();
  },
  event(d) { addEvent(d.event, true); },
  event_update(d) {
    const i = S.events.findIndex(e => e.event_id === d.event.event_id);
    if (i >= 0) S.events[i] = d.event;
    const el = $(`.ev[data-id="${d.event.event_id}"]`);
    if (el) el.outerHTML = evCard(d.event);
  },
  anpr(d) {
    if (d.stage === 'captured' || !S.anpr.job || S.anpr.job.job !== d.job) S.anpr.job = {job: d.job, camera: d.camera, stages: {}, crop: null};
    const j = S.anpr.job;
    j.stages[d.stage] = d;
    if (d.crop) j.crop = d.crop;
    if (d.plate_crop) j.plate_crop = d.plate_crop;
    if (d.stage === 'done') { S.anpr.recent.unshift(d.result); S.anpr.recent = S.anpr.recent.slice(0, 40); }
  },
  vehicle(d) { S.vehicleFeed.unshift(d.item); S.vehicleFeed = S.vehicleFeed.slice(0, 60); },
  face(d) { S.faceFeed.unshift(d); S.faceFeed = S.faceFeed.slice(0, 40); },
  net_log(d) { S.netLog.unshift({...d, ts: Date.now() / 1000}); S.netLog = S.netLog.slice(0, 80); },
  edge(d) { S.edge[d.camera] = d; },
  sync(d) { S.sync[d.camera] = d; if (d.done >= d.total) setTimeout(() => { delete S.sync[d.camera]; }, 2500); },
  meta(d) { S.meta[d.camera] = d; drawMeta(d.camera); },
};

// ------------------------------------------------------------------ header
function tickClock() {
  const now = new Date();
  $('#clockT').textContent = now.toLocaleTimeString('en-GB', {timeZone: TZ, hour12: false});
  $('#clockD').textContent = now.toLocaleDateString('en-GB', {timeZone: TZ, weekday: 'short', day: '2-digit', month: 'short', year: 'numeric'}) + ' · IST (UTC+05:30)';
}
function renderHeader() {
  const t = S.tick;
  if (!t) return;
  const sys = $('#sys');
  sys.className = 'sys ' + (t.system === 'critical' ? 'critical' : t.system === 'degraded' ? 'degraded' : '');
  $('#sysText').textContent = t.system.toUpperCase();
  const n = t.kpis.active_alerts;
  const b = $('#alertN');
  b.hidden = !n; b.textContent = n > 99 ? '99+' : n; b.classList.toggle('pulse', n > 0);
}
function renderOperator() {
  const o = S.operator;
  if (!o) return;
  $('#opName').textContent = o.name; $('#opRole').textContent = `${o.role} · ${o.id}`;
  $('#opAv').textContent = o.name.split(/\s+/).filter(w => !w.endsWith('.')).map(w => w[0]).join('').slice(0, 2).toUpperCase() || 'OP';
}
function renderSound() { $('#soundBtn').innerHTML = icon(S.sound ? 'soundOn' : 'soundOff'); $('#soundBtn').title = S.sound ? 'Alert sound: ON' : 'Alert sound: OFF'; }

// ------------------------------------------------------------------ tiles
function camTag(c) {
  return c.kind === 'live' ? '<span class="live" title="Live inference">LIVE</span>'
    : c.kind === 'recorded' ? '<span class="live rec" title="Recorded sample — real detections replayed in sync">REC</span>'
    : '<span class="live sim" title="Synthetic scene — generator ground truth">SIM</span>';
}
function tileHTML(cid) {
  const c = S.cams[cid];
  if (!c) return '<div class="tile empty-slot">No camera</div>';
  const g = c.gps || [0, 0];
  return `<div class="tile" data-cam="${esc(cid)}">
    <img class="vid" alt="">
    <canvas class="ov"></canvas>
    <div class="cover" hidden></div>
    <div class="th"><span class="id">${esc(cid)}</span><span class="nm">${esc(c.name)}<span class="gps">${g[0].toFixed(4)}°N ${g[1].toFixed(4)}°E · ${esc(c.link)}</span></span>${camTag(c)}</div>
    <div class="acts"><button data-act="expand">Expand</button><button data-act="scan">Capture &amp; Scan</button></div>
    <div class="tf"><span class="meta">connecting…</span><span class="bars"><i></i><i></i><i></i><i></i></span><span class="tier">—</span></div>
  </div>`;
}
function bindTiles(root) {
  $$('.tile[data-cam]', root).forEach(t => {
    const cid = t.dataset.cam;
    addSink(cid, $('img.vid', t));
    t.addEventListener('dblclick', () => openCamera(cid));
    $$('button[data-act]', t).forEach(b => b.addEventListener('click', e => {
      e.stopPropagation();
      if (b.dataset.act === 'expand') openCamera(cid);
      else captureScan(cid);
    }));
  });
  updateTiles();
}
function sigClass(sig) { return sig >= 85 ? 's4' : sig >= 65 ? 's3' : sig >= 45 ? 's2' : 's1'; }
function updateTiles() {
  const t = S.tick;
  if (!t) return;
  $$('.tile[data-cam]').forEach(el => {
    const cid = el.dataset.cam, c = t.cams[cid];
    if (!c) return;
    const n = c.net || {}, st = c.stats || {};
    el.classList.toggle('alert', !!c.alert);
    const wh = n.out_wh || c.wh || [0, 0];
    const fps = cid === 'CAM-01' && st.infer_fps ? `${num(st.fps, 1)} fps · AI ${num(st.infer_fps, 1)}/s` : `${num(st.fps, 1)} fps`;
    const meta = $('.meta', el);
    if (meta) meta.innerHTML = `${wh[0]}×${wh[1]} · ${fps}<span class="ext"> · ${num(n.bandwidth, 1)} Mbps · ${esc(n.link || '')}${st.night ? ' · NIGHT' : ''}</span>`;
    const bars = $('.bars', el); if (bars) bars.className = 'bars ' + sigClass(n.signal || 0);
    const tier = $('.tier', el);
    if (tier) { tier.className = 'tier ' + (n.tier || ''); tier.textContent = n.tier === 'OFFLINE' ? 'OFFLINE' : `${n.tier || '—'} ${wh[1] ? wh[1] + 'p' : ''}`; }
    const cover = $('.cover', el);
    if (!cover) return;
    const status = String(st.status || '');
    let html = '';
    if (n.tier === 'OFFLINE') {
      const q = (S.edge[cid] || {}).queued || n.queued || 0;
      html = `<div>LINK OFFLINE<small>edge node buffering · ${q} event${q === 1 ? '' : 's'} queued — will sync on reconnect</small></div>`;
    } else if (S.sync[cid]) {
      const s = S.sync[cid];
      html = `<div>SYNCING EDGE BUFFER<small>${s.done}/${s.total} events uploaded</small><div class="sync"><i style="width:${(100 * s.done / Math.max(1, s.total)) | 0}%"></i></div></div>`;
    } else if (n.tier === 'METADATA') {
      html = `<div>METADATA-ONLY MODE<small>${num(n.bandwidth, 2)} Mbps · detections + snapshots only, video paused</small></div>`;
      cover.classList.add('meta');
    } else if (status && status !== 'online' && status !== 'starting') {
      html = `<div>${esc(status.split('—')[0])}<small>${esc(status.split('—').slice(1).join('—'))}</small></div>`;
    }
    if (n.tier !== 'METADATA') cover.classList.remove('meta');
    cover.hidden = !html;
    if (html && cover._h !== html) { cover.innerHTML = html; cover._h = html; }
  });
}
function drawMeta(cid) {
  const d = S.meta[cid];
  $$(`.tile[data-cam="${cid}"] canvas.ov`).forEach(cv => {
    const tile = cv.parentElement;
    const W = cv.width = tile.clientWidth, H = cv.height = tile.clientHeight;
    const g = cv.getContext('2d');
    g.clearRect(0, 0, W, H);
    if (!d || !S.tick || (S.tick.cams[cid]?.net || {}).tier !== 'METADATA') return;
    const [sw, sh] = d.wh; const sc = Math.min(W / sw, H / sh); const ox = (W - sw * sc) / 2, oy = (H - sh * sc) / 2;
    g.lineWidth = 2; g.font = '600 11px Inter, sans-serif';
    d.tracks.forEach(tr => {
      const [x1, y1, x2, y2] = tr.box;
      g.strokeStyle = tr.name === 'person' ? '#46CD50' : '#FF9933';
      g.strokeRect(ox + x1 * sc, oy + y1 * sc, (x2 - x1) * sc, (y2 - y1) * sc);
      g.fillStyle = g.strokeStyle; g.fillText(`${tr.name} #${tr.tid}`, ox + x1 * sc, oy + y1 * sc - 3);
    });
  });
}
async function captureScan(cid) {
  toastMsg(`Capture & Scan · ${cid}`, 'Grabbing frame — vehicles go to ANPR, faces to the registry matcher…', 'info');
  try {
    const r = await post(`/api/cameras/${cid}/capture`);
    const faces = (r.faces || []).map(f => `${f.match || 'Unregistered'} (${f.category}, sim ${num(f.similarity, 2)})`).join('; ');
    toastMsg(`Scan result · ${cid}`, `${r.vehicles} vehicle(s) sent to ANPR${faces ? ' · faces: ' + faces : ' · no faces'}`, 'info', () => { location.hash = '#/module/anpr'; });
  } catch (e) { toastMsg('Scan failed', e.message, 'high'); }
}

// ------------------------------------------------------------------ KPI strip
function kpiHTML() {
  return `<div class="kpis" id="kpis">${[
    ['people_now', 'People tracked now'], ['vehicles_today', 'Vehicles today'], ['plates_today', 'Plates read'], ['faces_today', 'Faces detected'],
    ['intrusions_today', 'Intrusions today'], ['active_alerts', 'Active alerts'], ['avg_response_s', 'Avg response'], ['cams', 'Cameras online'],
  ].map(([k, l]) => `<div class="kpi" data-k="${k}"><div class="l">${l}</div><div class="v">—</div></div>`).join('')}</div>`;
}
function updateKpis() {
  const box = $('#kpis');
  if (!box || !S.tick) return;
  const k = S.tick.kpis;
  const set = (key, html, alert) => { const el = $(`.kpi[data-k="${key}"]`, box); if (el) { $('.v', el).innerHTML = html; el.classList.toggle('alert', !!alert); } };
  ['people_now', 'vehicles_today', 'plates_today', 'faces_today', 'intrusions_today'].forEach(x => set(x, k[x] ?? '—'));
  set('active_alerts', k.active_alerts, k.active_alerts > 0);
  set('avg_response_s', k.avg_response_s == null ? '—' : `${num(k.avg_response_s, 0)}<small> s</small>`);
  set('cams', `${k.cameras_online}<small>/${k.cameras_total}</small>`, k.cameras_online < k.cameras_total);
}

// ------------------------------------------------------------------ evidence log
const LOG_FILTERS = [['all', 'All'], ['human', 'Human'], ['vehicle', 'Vehicle/ANPR'], ['face', 'Face'], ['fence', 'Fence'], ['activity', 'Activity'], ['night', 'Night'], ['network', 'Network']];
const FILTER_MODS = {human: ['human'], vehicle: ['vehicle', 'anpr'], face: ['face'], fence: ['fence'], activity: ['activity'], night: ['night'], network: ['network']};
const evMatch = (e, f) => f === 'all' || (FILTER_MODS[f] || []).includes(e.module);
function snapUrl(e) { return e.snapshot ? (e.extra && e.extra.sample_history ? `/history_snaps/${e.snapshot}` : `/events/${e.snapshot}`) : ''; }
function oneLine(e) {
  const x = e.extra || {};
  if (e.module === 'anpr' && x.plate_display) return `${x.plate_display} · ${x.state || ''} · ${x.body_type || x.vehicle || ''}`;
  return e.description;
}
function evCard(e) {
  const x = e.extra || {};
  const tags = [e.synthetic ? '<span class="tag" title="From a synthetic scene">SIM</span>' : '', e.night ? '<span class="tag">NIGHT</span>' : '',
    x.edge_synced ? '<span class="tag" title="Held at edge node while link was down">EDGE SYNC</span>' : '', x.telemetry === 'simulated' ? '<span class="tag">SIM LINK</span>' : ''].join('');
  const act = e.status === 'new' && e.severity !== 'info'
    ? `<button class="btn sm ack" data-ack="${esc(e.event_id)}">Acknowledge</button>`
    : `<span class="st ${esc(e.status)} ack">${esc(e.status.replace('_', ' '))}</span>`;
  return `<div class="ev ${esc(e.severity)}" data-id="${esc(e.event_id)}">
    ${e.snapshot ? `<img loading="lazy" src="${snapUrl(e)}" alt="">` : '<div></div>'}
    <div style="min-width:0">
      <div class="en">${esc(e.event_name)}</div>
      <div class="ed" title="${esc(e.description)}">${esc(oneLine(e))}</div>
      <div class="em"><span class="sev ${esc(e.severity)}">${esc(e.severity)}</span><span>${esc(e.camera_id)}</span><span>${fmtT(e.ts_epoch)}</span>
        <span title="SHA-256 ${esc(e.sha256_hash)}">#${shortHash(e.sha256_hash)}</span>${act}</div>
      ${tags ? `<div class="tags">${tags}</div>` : ''}
    </div></div>`;
}
function renderLog() {
  $('#logFilters').innerHTML = LOG_FILTERS.map(([k, l]) => `<span class="chip ${S.evFilter === k ? 'act' : ''}" data-f="${k}">${l}</span>`).join('');
  const rows = S.events.filter(e => evMatch(e, S.evFilter)).slice(0, 150);
  $('#evlist').innerHTML = rows.length ? rows.map(evCard).join('') : '<div class="empty">No events in this category yet.</div>';
  $('#logCount').textContent = S.tick ? S.tick.kpis.events_total : S.events.length;
}
function addEvent(e, live) {
  if (S.events.some(x => x.event_id === e.event_id)) return;
  S.events.unshift(e);
  S.events = S.events.slice(0, 400);
  if (evMatch(e, S.evFilter)) {
    const list = $('#evlist');
    const emptyEl = $('.empty', list); if (emptyEl) emptyEl.remove();
    list.insertAdjacentHTML('afterbegin', evCard(e));
    while (list.children.length > 150) list.lastElementChild.remove();
  }
  $('#logCount').textContent = S.tick ? S.tick.kpis.events_total + 1 : S.events.length;
  if (live) alertFor(e);
}
async function ackEvent(id, action = 'acknowledge', note = '') {
  try { await post(`/api/events/${id}/action`, {action, note}); } catch (e) { toastMsg('Action failed', e.message, 'high'); }
}
function renderChain() {
  const v = S.integrity, el = $('#chain');
  if (!v) return;
  el.classList.toggle('bad', !v.ok);
  el.textContent = v.pending ? 'Verifying chain…' : v.ok ? `CHAIN VERIFIED ✓ (${v.checked} events)` : `TAMPERING DETECTED at ${v.failed_at} — ${v.reason}`;
}
async function verifyChain() {
  try { S.integrity = await api('/api/integrity'); renderChain(); emit('integrity', S.integrity); } catch (_) { /* offline */ }
  return S.integrity;
}

// ------------------------------------------------------------------ alerts: toast / sound / banner
let AC = null;
function beep(pattern) {
  if (!S.sound || !S.interacted) return;  // browsers block audio until the first click/keypress
  try {
    AC ||= new (window.AudioContext || window.webkitAudioContext)();
    if (AC.state === 'suspended') AC.resume();
    let t = AC.currentTime;
    pattern.forEach(([f, d]) => {
      const o = AC.createOscillator(), g = AC.createGain();
      o.type = 'square'; o.frequency.value = f; o.connect(g); g.connect(AC.destination);
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.12, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + d);
      o.start(t); o.stop(t + d + 0.02); t += d + 0.07;
    });
  } catch (_) { /* audio unavailable */ }
}
const SOUNDS = {critical: [[988, .16], [988, .16], [988, .16], [740, .3]], high: [[784, .14], [784, .14]], medium: [[587, .12]]};
function toastMsg(title, desc, sev = 'info', onclick = null, ms = 6500) {
  const el = document.createElement('div');
  el.className = `toast ${sev}`;
  el.innerHTML = `<div class="tt"><span class="sev ${sev}">${sev}</span>${esc(title)}</div><div class="td">${esc(desc)}</div>`;
  el.onclick = () => { if (onclick) onclick(); el.remove(); };
  $('#toasts').prepend(el);
  while ($('#toasts').children.length > 3) $('#toasts').lastElementChild.remove();
  setTimeout(() => el.remove(), ms);
}
function alertFor(e) {
  if (e.severity === 'info' || e.severity === 'medium') return;
  const el = document.createElement('div');
  el.className = `toast ${e.severity}`;
  el.innerHTML = `<div class="tt"><span class="sev ${esc(e.severity)}">${esc(e.severity)}</span>${esc(e.event_name)}</div>
    <div class="td">${esc(oneLine(e))}</div><div class="tm">${esc(e.camera_id)} · ${esc(e.location)} · ${fmtT(e.ts_epoch)} IST</div>`;
  el.onclick = () => { openEvent(e.event_id); el.remove(); };
  $('#toasts').prepend(el);
  while ($('#toasts').children.length > 3) $('#toasts').lastElementChild.remove();
  setTimeout(() => el.remove(), e.severity === 'critical' ? 12000 : 7000);
  beep(SOUNDS[e.severity] || []);
  const s = S.settings || {};
  if (e.severity === 'critical' && (s.alerts?.banner ?? true) && Date.now() - S.bannerAt > 45000 && $('#banner').hidden) showBanner(e);
}
function showBanner(e) {
  S.bannerAt = Date.now();
  const b = $('#banner');
  b.innerHTML = `<div class="banner"><div class="box">
    <div class="bh">${icon('shield')} CRITICAL ALERT — ${esc(e.event_name.toUpperCase())}</div>
    <div class="bb">
      ${e.snapshot ? `<img src="${snapUrl(e)}" alt="">` : '<div></div>'}
      <div class="stack" style="gap:10px">
        <dl class="kv"><dt>Camera</dt><dd>${esc(e.camera_id)} — ${esc(e.location)}</dd><dt>GPS</dt><dd class="mono">${esc(e.gps)}</dd>
        <dt>Time</dt><dd class="mono">${fmtISO(e.ts_iso)}</dd><dt>Detail</dt><dd>${esc(e.description)}</dd>
        <dt>Evidence</dt><dd class="mono">${esc(e.event_id)} · #${shortHash(e.sha256_hash)}</dd></dl>
        <div class="row"><button class="btn grn" data-b="acknowledge">Acknowledge</button><button class="btn red" data-b="escalate">Escalate to QRT</button>
        <button class="btn" data-b="open">Open evidence</button><button class="btn" data-b="close">Dismiss</button></div>
        <div class="note">Auto-dismisses in 15 s · the alert stays in the evidence log until actioned.</div>
      </div></div></div></div>`;
  b.hidden = false;
  const close = () => { b.hidden = true; b.innerHTML = ''; };
  const tm = setTimeout(close, 15000);
  $$('[data-b]', b).forEach(x => x.onclick = async () => {
    clearTimeout(tm);
    const a = x.dataset.b;
    if (a === 'acknowledge' || a === 'escalate') await ackEvent(e.event_id, a);
    if (a === 'open') openEvent(e.event_id);
    close();
  });
}

// ------------------------------------------------------------------ modal
function openModal(title, html, onClose) {
  const m = $('#modal');
  m.innerHTML = `<div class="modal"><div class="mbox"><div class="mh"><h2>${title}</h2><span style="flex:1"></span><button class="btn" data-x>Close (Esc)</button></div><div class="mb">${html}</div></div></div>`;
  m.hidden = false;
  const close = () => { dropSinks(m); S.focus = null; queueSync(); m.hidden = true; m.innerHTML = ''; document.removeEventListener('keydown', key); if (onClose) onClose(); };
  const key = e => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', key);
  $('[data-x]', m).onclick = close;
  $('.modal', m).addEventListener('mousedown', e => { if (e.target.classList.contains('modal')) close(); });
  return {el: $('.mb', m), close};
}

async function openEvent(id) {
  let e;
  try { e = await api(`/api/events/${encodeURIComponent(id)}`); } catch (err) { toastMsg('Not found', err.message, 'medium'); return; }
  const x = e.extra || {};
  const crops = ['vehicle_img', 'plate_img', 'face_img'].filter(k => x[k]).map(k => `<div><div class="note">${k.split('_')[0]} crop</div><img class="thumb" style="width:auto;height:84px" src="/events/${esc(x[k])}"></div>`).join('');
  const extraRows = Object.entries(x).filter(([k, v]) => !k.endsWith('_img') && k !== 'faces' && k !== 'timeline' && v !== null && v !== '')
    .map(([k, v]) => `<dt>${esc(k.replace(/_/g, ' '))}</dt><dd>${esc(typeof v === 'object' ? JSON.stringify(v) : v)}</dd>`).join('');
  const tl = (x.timeline || []).map(s => `<div class="step done"><i>✓</i>${esc(s.t)}s · ${esc(s.event)}</div>`).join('');
  const acts = (e.actions || []).map(a => `<tr><td class="mono">${fmtISO(a.ts_iso)}</td><td><span class="st ${esc(a.action)}">${esc(a.action.replace('_', ' '))}</span></td><td>${esc(a.operator)}</td><td>${esc(a.note)}</td><td class="hash">#${shortHash(a.sha256_hash)}</td></tr>`).join('');
  const m = openModal(`${esc(e.event_id)} · ${esc(e.event_name)}`, `
    <div class="grid2" style="grid-template-columns:1.35fr 1fr">
      <div class="stack">
        ${e.snapshot ? `<img src="${snapUrl(e)}" style="width:100%;border-radius:9px;border:1px solid var(--border)" alt="snapshot">` : '<div class="empty">No snapshot</div>'}
        ${crops ? `<div class="row">${crops}</div>` : ''}
        ${tl ? `<div class="panel"><div class="ph"><h3>Behaviour timeline</h3></div><div class="pb steps">${tl}</div></div>` : ''}
      </div>
      <div class="stack">
        <div class="row"><span class="sev ${esc(e.severity)}">${esc(e.severity)}</span><span class="st ${esc(e.status)}">${esc(e.status.replace('_', ' '))}</span>
          ${e.response_s ? `<span class="chip">response ${num(e.response_s, 0)} s</span>` : ''}${e.synthetic ? '<span class="chip">synthetic scene</span>' : ''}</div>
        <dl class="kv">
          <dt>Event ID</dt><dd class="mono">${esc(e.event_id)}</dd><dt>Alert type</dt><dd>${esc(e.alert_type)}</dd><dt>Module</dt><dd>${esc(e.module)}</dd>
          <dt>Timestamp</dt><dd class="mono">${fmtISO(e.ts_iso)}</dd><dt>Camera</dt><dd>${esc(e.camera_id)} — ${esc(e.location)}</dd>
          <dt>GPS</dt><dd class="mono">${esc(e.gps)}</dd><dt>Model</dt><dd>${esc(e.model_used)}</dd>
          <dt>Confidence</dt><dd>${e.confidence == null ? '—' : num(e.confidence, 3)}</dd><dt>Track ID</dt><dd>${e.track_id ?? '—'}</dd>
          <dt>Detail</dt><dd>${esc(e.description)}</dd>${extraRows}
          <dt>Notification</dt><dd class="mono">${esc(e.notification_status)}</dd>
        </dl>
        <div class="panel"><div class="ph"><h3>Tamper-evidence</h3></div><div class="pb"><dl class="kv">
          <dt>Snapshot SHA-256</dt><dd class="hash">${esc(e.snapshot_sha256 || '—')}</dd>
          <dt>Previous hash</dt><dd class="hash">${esc(e.prev_hash)}</dd><dt>Event hash</dt><dd class="hash">${esc(e.sha256_hash)}</dd></dl>
          <div class="note" style="margin-top:6px">Event hash = SHA-256(snapshot bytes + event JSON + previous hash).</div></div></div>
        <div class="panel"><div class="ph"><h3>Operator workflow</h3></div><div class="pb stack" style="gap:8px">
          <textarea class="in" id="actNote" rows="2" placeholder="Note (optional)"></textarea>
          <div class="row"><button class="btn grn" data-a="acknowledge">Acknowledge</button><button class="btn red" data-a="escalate">Escalate</button>
          <button class="btn" data-a="false_alarm">Mark false alarm</button><button class="btn pri" data-a="resolve">Resolve</button></div>
          ${acts ? `<table class="t"><thead><tr><th>Time</th><th>Action</th><th>Operator</th><th>Note</th><th>Hash</th></tr></thead><tbody>${acts}</tbody></table>` : '<div class="note">No actions yet — every action is logged with operator + time in its own hash chain.</div>'}
        </div></div>
      </div>
    </div>`);
  $$('[data-a]', m.el).forEach(b => b.onclick = async () => { await ackEvent(e.event_id, b.dataset.a, $('#actNote').value); m.close(); openEvent(e.event_id); });
}

// ------------------------------------------------------------------ router
const ROUTES = {};
const NAV = [
  ['dashboard', 'Dashboard', 'dashboard'], ['cameras', 'Live Cameras', 'camera'], ['modules', 'AI Modules', 'cpu'], ['events', 'Event Log', 'log'],
  ['vehicles', 'Vehicle Registry', 'car'], ['faces', 'Face Registry', 'users'], ['map', 'Map View', 'map'], ['analytics', 'Analytics', 'chart'],
  ['network', 'Network Health', 'wifi'], ['integrations', 'Integrations', 'plug'], ['settings', 'Settings', 'settings'], ['about', 'About', 'info'],
];
function renderNav() {
  $('#nav').innerHTML = NAV.map(([k, l, i], idx) => `${idx === 0 ? '<div class="grp">Operations</div>' : idx === 4 ? '<div class="grp">Intelligence</div>' : idx === 8 ? '<div class="grp">System</div>' : ''}
    <a href="#/${k}" data-r="${k}">${icon(i)}${l}</a>`).join('') +
    '<div class="foot"><div class="tri-mini"></div>IBVAP v2 · edge node BOP-A<br>Offline-capable · software-only</div>';
}
function cleanupPage() {
  S.pageOff.forEach(f => { try { f(); } catch (_) { /* ignore */ } });
  S.pageOff = [];
  S.charts.forEach(c => c.destroy());
  S.charts = [];
  dropSinks($('#main'));
}
function go() {
  const parts = (location.hash.replace(/^#\/?/, '') || 'dashboard').split('/');
  const name = ROUTES[parts[0]] ? parts[0] : 'dashboard';
  cleanupPage();
  S.page = name;
  $$('#nav a').forEach(a => a.classList.toggle('on', a.dataset.r === name || (name === 'module' && a.dataset.r === 'modules')));
  const main = $('#main');
  main.innerHTML = '';
  main.scrollTop = 0;
  ROUTES[name](main, parts.slice(1).map(decodeURIComponent));
  syncSubs();
}

// ------------------------------------------------------------------ boot
async function refreshCams() {
  const cams = await api('/api/cameras');
  S.cams = Object.fromEntries(cams.map(c => [c.id, c]));
  if (!S.order.length) S.order = cams.map(c => c.id);
}
async function refreshModels() { try { S.models = await api('/api/models'); } catch (_) { /* retry later */ } return S.models; }
async function boot() {
  renderNav(); renderSound(); tickClock(); setInterval(tickClock, 250);
  $('#soundBtn').onclick = () => { S.sound = !S.sound; renderSound(); if (S.sound) beep([[660, .1]]); post('/api/settings', {sound: S.sound}); };
  $('#logBtn').onclick = () => {
    const b = $('#body');
    if (innerWidth <= 1280) b.classList.toggle('log-open'); else b.classList.toggle('log-closed');
    document.body.classList.toggle('nolog', b.classList.contains('log-closed'));
  };
  $('#alertBtn').onclick = () => { location.hash = '#/events/active'; };
  $('#chain').onclick = verifyChain;
  $('#logFilters').onclick = e => { const c = e.target.closest('[data-f]'); if (c) { S.evFilter = c.dataset.f; renderLog(); } };
  $('#evlist').onclick = e => {
    const a = e.target.closest('[data-ack]');
    if (a) { e.stopPropagation(); ackEvent(a.dataset.ack); return; }
    const c = e.target.closest('.ev'); if (c) openEvent(c.dataset.id);
  };
  let tries = 0;
  for (;;) {
    try {
      const st = await api('/api/status');
      S.operator = st.operator; S.sound = st.sound !== false; S.integrity = st.integrity;
      break;
    } catch (_) { $('#bootMsg').textContent = `Waiting for server… (${++tries})`; await new Promise(r => setTimeout(r, 1200)); }
  }
  renderOperator(); renderSound(); renderChain();
  [S.settings] = await Promise.all([api('/api/settings'), refreshCams(), refreshModels()]);
  S.events = await api('/api/events?limit=150');
  renderLog();
  wsConnect();
  window.addEventListener('hashchange', go);
  go();
  $('#boot').remove();
  setInterval(async () => { try { S.integrity = (await api('/api/status')).integrity; renderChain(); } catch (_) { /* retry */ } }, 15000);
  setInterval(refreshModels, 3000);
}
document.addEventListener('DOMContentLoaded', boot);
