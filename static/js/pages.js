/* Pehredar.ai — pages & module panels */
'use strict';
if (window.Chart) {
  Chart.defaults.color = '#C9D3E3'; Chart.defaults.borderColor = '#1F2A44';
  Chart.defaults.font.family = 'Inter, Segoe UI, sans-serif'; Chart.defaults.font.size = 11;
  Chart.defaults.plugins.legend.labels.boxWidth = 10;
}
const PAL = ['#FF9933', '#1FAE12', '#5B8DEF', '#E53935', '#FDD835', '#B0BEC5', '#AB47BC', '#26C6DA'];
const SEV_COL = {critical: '#E53935', high: '#FF9933', medium: '#FDD835', info: '#138808'};
const settingsPatch = patch => post('/api/settings', patch).then(s => { S.settings = s; return s; });
const camsWith = m => Object.values(S.cams).filter(c => (c.modules || []).includes(m)).map(c => c.id);
const pageH = (title, sub, right = '') => `<div class="page-h"><div><h1>${title}</h1><div class="sub">${sub}</div></div><span class="sp"></span>${right}</div>`;

function chart(canvas, cfg) { return pageChart(new Chart(canvas, cfg)); }
function barCfg(labels, data, color = '#FF9933', horizontal = false) {
  return {type: 'bar', data: {labels, datasets: [{data, backgroundColor: color, borderRadius: 4}]},
    options: {indexAxis: horizontal ? 'y' : 'x', animation: false, maintainAspectRatio: false, plugins: {legend: {display: false}},
      scales: {x: {grid: {display: horizontal}}, y: {beginAtZero: true, ticks: {precision: 0}}}}};
}
function doughnutCfg(labels, data, colors) {
  return {type: 'doughnut', data: {labels, datasets: [{data, backgroundColor: colors || PAL, borderColor: '#121B2E', borderWidth: 2}]},
    options: {animation: false, maintainAspectRatio: false, cutout: '62%', plugins: {legend: {position: 'right'}}}};
}

// =================================================================== dashboard
ROUTES.dashboard = (main) => {
  main.innerHTML = pageH('Command Dashboard', `${esc(S.settings?.sector || '')} · all feeds, all AI modules`) + kpiHTML() + `
    <div class="grid-tools"><span class="head" style="font-size:15px;letter-spacing:1px">CAMERA GRID</span>
      <div class="seg" id="gridSeg">${[1, 2, 3, 4].map(n => `<button data-g="${n}" class="${S.grid === n ? 'on' : ''}">${n}×${n}</button>`).join('')}</div>
      <span id="pager" class="row"></span><span style="flex:1"></span>
      <span class="note">Double-click a tile to expand · hover for Capture &amp; Scan</span></div>
    <div class="cam-grid g${S.grid}" id="camGrid"></div>
    <div class="mbar" id="mbar"></div>
    <div id="modPanel"></div>`;
  let offMod = null;
  const drawGrid = () => {
    dropSinks($('#camGrid'));
    const ids = S.order.filter(c => S.cams[c]);
    const per = S.grid * S.grid;
    const pages = Math.max(1, Math.ceil(ids.length / per));
    S.gridPage = Math.min(S.gridPage, pages - 1);
    const slice = ids.slice(S.gridPage * per, S.gridPage * per + per);
    const pad = S.grid >= 3 ? Math.max(0, per - slice.length) : 0;
    $('#camGrid').className = `cam-grid g${S.grid}`;
    $('#camGrid').innerHTML = slice.map(tileHTML).join('') +
      Array.from({length: pad}, () => '<div class="tile empty-slot"><a href="#/integrations" style="color:var(--dim)">+ onboard RTSP / ONVIF camera</a></div>').join('');
    bindTiles($('#camGrid'));
    $('#pager').innerHTML = pages > 1 ? `<button class="btn sm" data-p="-1">‹</button><span class="mono dim">${S.gridPage + 1}/${pages}</span><button class="btn sm" data-p="1">›</button>` : '';
    queueSync();
  };
  $('#gridSeg').onclick = e => { const b = e.target.closest('[data-g]'); if (!b) return; S.grid = +b.dataset.g; S.gridPage = 0; $$('#gridSeg button').forEach(x => x.classList.toggle('on', x === b)); drawGrid(); };
  $('#pager').onclick = e => { const b = e.target.closest('[data-p]'); if (!b) return; S.gridPage = Math.max(0, S.gridPage + +b.dataset.p); drawGrid(); };
  const drawBar = () => {
    const mb = $('#mbar');
    if (!mb) return;
    const allOn = MOD_ORDER.every(k => S.toggles[k] !== false);
    mb.innerHTML = MOD_ORDER.map(k => {
      const m = S.models[k] || {}, on_ = S.toggles[k] !== false;
      return `<div class="mbtn ${S.dashModule === k ? 'sel' : ''} ${on_ ? '' : 'off'}" data-m="${k}" title="${esc(m.model || '')}">
        <label class="switch tgl" title="Toggle ${esc(MOD[k].name)} overlay"><input type="checkbox" data-t="${k}" ${on_ ? 'checked' : ''}><i></i></label>
        <div class="top">${icon(MOD[k].icon)}<span class="n">${MOD[k].name}</span></div>
        <div class="tg">${esc(m.short || MOD[k].tag)}</div>
        <div class="stt"><span class="d"></span>${on_ ? (m.running ? `${num(m.fps, 1)} fps` : 'idle') : 'overlay off'}${m.ms ? ` · ${num(m.ms, 0)} ms` : ''}</div></div>`;
    }).join('') + `<div class="mbtn all" data-all="1"><div class="n">ALL MODELS</div>
      <label class="switch"><input type="checkbox" id="allT" ${allOn ? 'checked' : ''}><i></i></label><div class="tg">master overlay toggle</div></div>`;
  };
  $('#mbar').addEventListener('click', async e => {
    const t = e.target.closest('input[data-t]');
    if (t) { e.stopPropagation(); S.toggles = await post(`/api/models/${t.dataset.t}/toggle`, {enabled: t.checked}); drawBar(); return; }
    if (e.target.id === 'allT') { S.toggles = await post('/api/models/all/toggle', {enabled: e.target.checked}); drawBar(); return; }
    if (e.target.closest('.switch')) return;
    const b = e.target.closest('[data-m]');
    if (b) { S.dashModule = b.dataset.m; drawBar(); showMod(); }
  });
  const showMod = () => { if (offMod) offMod(); offMod = mountModule(S.dashModule, $('#modPanel'), false); };
  S.pageOff.push(() => offMod && offMod());
  drawGrid(); drawBar(); showMod(); updateKpis();
  pageEvery(drawBar, 2000);
};

// =================================================================== camera modal (full view + zone editor)
const ZCOL = {restricted: '#E53935', buffer: '#FF9933', tripwire: '#FFFFFF', count: '#26C6DA'};
async function openCamera(cid, opts = {}) {
  const c = S.cams[cid];
  if (!c) return;
  const info = await api(`/api/cameras/${cid}`);
  const wh = info.wh[0] ? info.wh : [16, 9];
  const live = c.kind === 'live';
  const m = openModal(`${esc(cid)} · ${esc(c.name)} ${camTag(c)}`, `
    <div class="cam-full">
      <div class="stack">
        <div class="cam-view" id="cv" style="aspect-ratio:${wh[0]}/${wh[1]}"><img id="cvImg" alt=""><canvas id="cvCan"></canvas></div>
        <div class="row">
          <div class="seg" id="dispSeg">${['normal', 'enhanced', 'thermal'].map(d => `<button data-d="${d}" class="${info.display === d ? 'on' : ''}">${d}</button>`).join('')}</div>
          <label class="switch"><input type="checkbox" id="heatT" ${info.heatmap ? 'checked' : ''}><i></i>Heatmap</label>
          ${(c.variants || []).length ? `<select class="in" id="variant">${c.variants.map(v => `<option value="${v}">${v ? v + ' scene' : 'day scene'}</option>`).join('')}</select>` : ''}
          <span style="flex:1"></span><button class="btn pri" id="scanBtn">Capture &amp; Scan</button>
        </div>
        ${live ? `<div class="panel"><div class="ph"><h3>Video source</h3></div><div class="pb">${sourceControls(cid)}</div></div>` : ''}
        <div class="panel"><div class="ph"><h3>Recent events · ${esc(cid)}</h3></div><div class="pb tscroll" id="camEvents" style="max-height:260px"></div></div>
      </div>
      <div class="stack">
        <div class="panel"><div class="ph"><h3>Camera</h3></div><div class="pb"><dl class="kv">
          <dt>Location</dt><dd>${esc(c.location)}</dd><dt>GPS</dt><dd class="mono">${c.gps[0].toFixed(5)}°N, ${c.gps[1].toFixed(5)}°E</dd>
          <dt>Link</dt><dd>${esc(c.link)}</dd><dt>Source</dt><dd id="camSrc">${esc(info.source)}</dd>
          <dt>Modules</dt><dd>${(c.modules || []).map(x => `<span class="chip">${esc(MOD[x]?.name || x)}</span>`).join(' ')}</dd>
          <dt>Restricted post</dt><dd>${c.restricted_post ? 'yes' : 'no'}</dd></dl></div></div>
        <div class="panel"><div class="ph"><h3>Live</h3></div><div class="pb"><div class="grid2" id="camLive"></div></div></div>
        <div class="panel"><div class="ph"><h3>Virtual fence zones</h3><span class="sp"></span><button class="btn sm" id="zEdit">Draw zone</button></div>
          <div class="pb stack" style="gap:8px"><div id="zForm" hidden></div><div id="zList" class="stack" style="gap:6px"></div>
          <div class="row"><button class="btn sm pri" id="zSave">Save zones</button><span class="note" id="zNote"></span></div></div></div>
      </div>
    </div>`, () => { clearInterval(iv); offTick(); });
  const img = $('#cvImg', m.el);
  addSink(cid, img); S.focus = cid; queueSync();
  if (live) bindSourceControls(cid, m.el);
  $('#dispSeg', m.el).onclick = async e => { const b = e.target.closest('[data-d]'); if (!b) return; await post(`/api/cameras/${cid}/display`, {mode: b.dataset.d}); $$('#dispSeg button', m.el).forEach(x => x.classList.toggle('on', x === b)); };
  $('#heatT', m.el).onchange = e => post(`/api/cameras/${cid}/display`, {heatmap: e.target.checked});
  if ($('#variant', m.el)) $('#variant', m.el).onchange = e => post(`/api/cameras/${cid}/display`, {variant: e.target.value});
  $('#scanBtn', m.el).onclick = () => captureScan(cid);
  const renderLive = () => {
    const t = S.tick?.cams?.[cid];
    if (!t) return;
    const s = t.stats, n = t.net || {};
    $('#camLive', m.el).innerHTML = [
      ['People', s.people], ['Vehicles', s.vehicles], ['Faces', s.faces], ['Display fps', num(s.fps, 1)],
      [live ? 'AI inference' : 'Analysis', live ? `${num(s.infer_fps, 1)}/s · ${num(s.infer_ms, 0)} ms` : `${num(s.analysis_fps, 1)} fps`],
      ['Scene', `${s.night ? 'NIGHT' : 'DAY'} · ${num(s.light, 0)}/255`], ['Entries / exits', `${s.entries} / ${s.exits}`],
      ['Stream', `${n.tier || '—'} · ${num(n.bandwidth, 1)} Mbps`]].map(([l, v]) => `<div class="statbox"><div class="l">${l}</div><div class="v" style="font-size:17px">${v ?? '—'}</div></div>`).join('');
    $('#camSrc', m.el).textContent = t.source || '';
  };
  const offTick = on('tick', renderLive);
  renderLive();
  const loadEvents = async () => {
    const evs = await api(`/api/events?camera=${cid}&limit=25`);
    const box = $('#camEvents', m.el);
    if (box) box.innerHTML = evTable(evs, true);
  };
  loadEvents();
  const iv = setInterval(loadEvents, 5000);
  $('#camEvents', m.el).onclick = e => { const r = e.target.closest('[data-ev]'); if (r) openEvent(r.dataset.ev); };
  zoneEditor(cid, m.el, wh, opts.edit);
}

function zoneEditor(cid, root, wh, startEditing) {
  let zones = [], draft = null;
  const cv = $('#cvCan', root), view = $('#cv', root);
  const draw = () => {
    const W = cv.width = view.clientWidth, H = cv.height = view.clientHeight;
    const g = cv.getContext('2d');
    g.clearRect(0, 0, W, H);
    if (!draft) return;
    g.strokeStyle = ZCOL[draft.type]; g.fillStyle = ZCOL[draft.type] + '33'; g.lineWidth = 3;
    g.beginPath();
    draft.pts.forEach(([x, y], i) => i ? g.lineTo(x * W, y * H) : g.moveTo(x * W, y * H));
    if (draft.pts.length > 2 && !['tripwire', 'count'].includes(draft.type)) { g.closePath(); g.fill(); }
    g.stroke();
    draft.pts.forEach(([x, y]) => { g.beginPath(); g.arc(x * W, y * H, 5, 0, 7); g.fillStyle = '#fff'; g.fill(); });
  };
  const list = () => {
    $('#zList', root).innerHTML = zones.length ? zones.map((z, i) => `<div class="zone-row"><span class="sw" style="background:${ZCOL[z.type]}"></span>
      <div><b>${esc(z.name)}</b> <span class="dim">· ${z.type} · ${z.objects} · ${z.schedule === 'custom' ? `${z.from}–${z.to}` : z.schedule}${['tripwire', 'count'].includes(z.type) ? ` · ${z.direction}` : ''}</span></div>
      <span class="row" style="gap:6px"><label class="switch" title="armed"><input type="checkbox" data-arm="${i}" ${z.armed !== false ? 'checked' : ''}><i></i></label><button class="btn sm red" data-del="${i}">✕</button></span></div>`).join('')
      : '<div class="note">No zones on this camera yet.</div>';
  };
  const form = () => {
    const f = $('#zForm', root);
    f.hidden = !draft;
    if (!draft) return;
    f.innerHTML = `<div class="grid2">
      <label class="f">Type<select class="in" id="zType">${['restricted', 'buffer', 'tripwire', 'count'].map(t => `<option ${draft.type === t ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
      <label class="f">Name<input class="in" id="zName" value="${esc(draft.name)}"></label>
      <label class="f">Objects<select class="in" id="zObj">${['both', 'person', 'vehicle'].map(t => `<option ${draft.objects === t ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
      <label class="f">Armed<select class="in" id="zSch">${[['always', 'always'], ['night', 'only at night'], ['custom', 'custom hours']].map(([v, l]) => `<option value="${v}" ${draft.schedule === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
      <label class="f" id="zHours" ${draft.schedule === 'custom' ? '' : 'hidden'}>Hours (IST)<span class="row"><input class="in" type="time" id="zFrom" value="${draft.from}"><input class="in" type="time" id="zTo" value="${draft.to}"></span></label>
      <label class="f" ${['tripwire', 'count'].includes(draft.type) ? '' : 'hidden'} id="zDirL">Direction<select class="in" id="zDir">${[['any', 'any crossing'], ['forward', 'forward only (arrow side)'], ['reverse', 'reverse only']].map(([v, l]) => `<option value="${v}" ${draft.direction === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
    </div>
    <div class="note">${['tripwire', 'count'].includes(draft.type) ? 'Click 2 points on the video to draw the line (A → B). "Forward" = crossing to the side the arrow points (left of A→B).' : 'Click 3+ points on the video, then Finish.'} Checks use each object's foot point (bottom-centre of its box).</div>
    <div class="row"><button class="btn sm grn" id="zDone">Finish zone</button><button class="btn sm" id="zUndo">Undo point</button><button class="btn sm red" id="zCancel">Cancel</button></div>`;
    const bind = (id, k, ev = 'onchange') => { $(id, f)[ev] = e => { draft[k] = e.target.value; if (k === 'type' || k === 'schedule') form(); draw(); }; };
    bind('#zType', 'type'); bind('#zName', 'name', 'oninput'); bind('#zObj', 'objects'); bind('#zSch', 'schedule');
    bind('#zFrom', 'from'); bind('#zTo', 'to'); bind('#zDir', 'direction');
    $('#zUndo', f).onclick = () => { draft.pts.pop(); draw(); };
    $('#zCancel', f).onclick = () => { draft = null; view.classList.remove('editing'); form(); draw(); };
    $('#zDone', f).onclick = finish;
  };
  const finish = () => {
    const line = ['tripwire', 'count'].includes(draft.type);
    if ((line && draft.pts.length !== 2) || (!line && draft.pts.length < 3)) { toastMsg('Zone incomplete', line ? 'A line needs exactly 2 points' : 'A polygon needs at least 3 points', 'medium'); return; }
    zones.push({...draft, points: draft.pts.map(p => p.map(v => +v.toFixed(4)))});
    draft = null; view.classList.remove('editing'); form(); draw(); list();
    $('#zNote', root).textContent = 'Unsaved changes — click Save zones';
  };
  cv.addEventListener('click', e => {
    if (!draft) return;
    const r = cv.getBoundingClientRect();
    draft.pts.push([(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height]);
    if (['tripwire', 'count'].includes(draft.type) && draft.pts.length === 2) { draw(); return; }
    draw();
  });
  cv.addEventListener('dblclick', () => { if (draft && draft.pts.length >= 3) finish(); });
  $('#zEdit', root).onclick = () => { draft = {type: 'restricted', name: 'New zone', objects: 'both', schedule: 'always', from: '20:00', to: '06:00', direction: 'any', pts: []}; view.classList.add('editing'); form(); draw(); };
  $('#zList', root).onclick = e => {
    const d = e.target.closest('[data-del]');
    if (d) { zones.splice(+d.dataset.del, 1); list(); $('#zNote', root).textContent = 'Unsaved changes — click Save zones'; }
  };
  $('#zList', root).onchange = e => { const a = e.target.closest('[data-arm]'); if (a) { zones[+a.dataset.arm].armed = a.checked; $('#zNote', root).textContent = 'Unsaved changes — click Save zones'; } };
  $('#zSave', root).onclick = async () => {
    const r = await post(`/api/zones/${cid}`, {zones});
    zones = r.zones; list(); $('#zNote', root).textContent = `Saved ${zones.length} zone(s) · active immediately`;
    toastMsg('Zones saved', `${cid}: ${zones.length} zone(s)`, 'info');
  };
  api(`/api/zones/${cid}`).then(z => { zones = z; list(); if (startEditing) $('#zEdit', root).click(); });
  new ResizeObserver(draw).observe(view);
}

function sourceControls(cid) {
  return `<div class="stack" style="gap:8px">
    <div class="row"><button class="btn" data-src="webcam:0">Use webcam</button>
      <select class="in" id="sampleSel"></select><button class="btn" id="useSample">Use sample clip</button>
      <label class="btn">Upload video<input type="file" id="upVid" accept="video/*" hidden></label></div>
    <div class="row"><input class="in" id="rtspUrl" style="flex:1;min-width:240px" placeholder="rtsp://user:pass@192.168.1.64:554/Streaming/Channels/101"><button class="btn" id="useRtsp">Connect RTSP</button></div>
    <div class="note" id="srcNote">A black / covered webcam is detected automatically and CAM-01 falls back to a sample clip.</div></div>`;
}
function bindSourceControls(cid, root) {
  api('/api/samples').then(list => { const s = $('#sampleSel', root); if (s) s.innerHTML = list.map(n => `<option>${esc(n)}</option>`).join(''); });
  const set = async src => {
    $('#srcNote', root).textContent = 'Switching source…';
    try { const r = await post(`/api/cameras/${cid}/source`, {source: src}); $('#srcNote', root).textContent = r.ok ? `Now: ${r.source}` : `Failed: ${r.status}`; }
    catch (e) { $('#srcNote', root).textContent = e.message; }
  };
  $$('[data-src]', root).forEach(b => b.onclick = () => set(b.dataset.src));
  $('#useSample', root).onclick = () => set('sample:' + $('#sampleSel', root).value);
  $('#useRtsp', root).onclick = () => set($('#rtspUrl', root).value.trim());
  $('#upVid', root).onchange = async e => {
    const f = e.target.files[0]; if (!f) return;
    const fd = new FormData(); fd.append('video', f);
    $('#srcNote', root).textContent = `Uploading ${f.name}…`;
    const r = await fetch(`/api/cameras/${cid}/upload`, {method: 'POST', body: fd}).then(x => x.json());
    $('#srcNote', root).textContent = r.ok ? `Now: ${r.source}` : `Upload failed: ${r.error}`;
  };
}

// =================================================================== shared tables
function evTable(evs, compact = false) {
  if (!evs.length) return '<div class="empty">No events yet.</div>';
  return `<table class="t"><thead><tr><th></th><th>Event</th>${compact ? '' : '<th>Camera</th>'}<th>Time (IST)</th><th>Severity</th><th>Status</th>${compact ? '' : '<th>Hash</th>'}</tr></thead><tbody>${
    evs.map(e => `<tr class="click" data-ev="${esc(e.event_id)}"><td>${e.snapshot ? `<img class="thumb" loading="lazy" src="${snapUrl(e)}">` : ''}</td>
      <td><b>${esc(e.event_name)}</b><div class="note">${esc(oneLine(e)).slice(0, 110)}</div></td>${compact ? '' : `<td class="mono">${esc(e.camera_id)}</td>`}
      <td class="mono">${fmtDT(e.ts_epoch)}</td><td><span class="sev ${esc(e.severity)}">${esc(e.severity)}</span></td>
      <td><span class="st ${esc(e.status)}">${esc(e.status.replace('_', ' '))}</span></td>${compact ? '' : `<td class="hash">#${shortHash(e.sha256_hash)}</td>`}</tr>`).join('')}</tbody></table>`;
}
function plateHTML(p, cls = '') { return p ? `<span class="plate ${cls}"><span>${esc(p)}</span></span>` : '<span class="plate unk sm"><span>NOT READ</span></span>'; }

// =================================================================== module panels
const MODINFO = {
  human: {detects: 'People (COCO "person") with persistent ByteTrack IDs, 30-point movement trails, counts, entry/exit over counting lines, dwell per ID, heatmap',
    alerts: ['Person in restricted zone (via Virtual Fence)', 'Crowd above threshold'], thr: ['human', 'conf', 'Detection confidence', 0.1, 0.9, 0.05]},
  vehicle: {detects: 'Car, motorcycle, bus, truck, bicycle · colour (k-means on the crop), direction IN/OUT, speed km/h (calibrated), size class LMV/HMV/2-wheeler',
    alerts: ['Heavy vehicle on restricted road', 'Vehicle stopped too long', 'Wrong-way vehicle (one-way cameras)'], thr: ['vehicle', 'conf', 'Detection confidence', 0.1, 0.9, 0.05]},
  face: {detects: 'Faces (YuNet), quality score (size + sharpness), best shot per person track, SFace embedding matched against the Face Registry',
    alerts: ['Watchlist face match (Critical)', 'Unregistered person at restricted post (Medium)'], thr: ['face', 'match_threshold', 'Match threshold (cosine)', 0.2, 0.8, 0.01]},
  anpr: {detects: 'Every vehicle track → best frame → your anpr_best.pt body type → plate detection + OCR → Indian format check + state decode → watchlist',
    alerts: ['Watchlisted Vehicle Detected (Critical)', 'Plate read — manual review (Medium)', 'Vehicle plate read (Info)'], thr: ['anpr', 'ocr_min_conf', 'OCR confidence floor', 0.3, 0.95, 0.05]},
  fence: {detects: 'Polygon zones (restricted / buffer), counting lines and direction-aware tripwires; foot-point checks; per-zone object filter and schedule',
    alerts: ['Fence Breach (Critical)', 'Buffer Zone Entry (High)', 'Night variants escalate'], thr: ['alerts', 'cooldown_s', 'Alert cooldown per track (s)', 5, 120, 5]},
  activity: {detects: 'Loitering, running, wrong-way, group gathering, crawling near fence, repeated passes, abandoned object — each with a 0–100 risk score',
    alerts: ['Severity from risk: ≥75 Critical · ≥55 High · ≥35 Medium'], thr: ['activity', 'loiter_seconds', 'Loiter time (s)', 4, 60, 1]},
  night: {detects: 'Day/night from smoothed frame brightness (hysteresis), CLAHE + gamma enhancement before inference, thermal palette, MOG2 motion when YOLO struggles',
    alerts: ['Night movement near border (High)', 'Fence Breach (Night) inside restricted zones (Critical)', 'Unclassified night motion (Medium)'], thr: ['night', 'enter_below', 'Night below brightness', 20, 120, 1]},
  network: {detects: 'Per-camera latency, jitter, loss, bandwidth, uptime, signal · adaptive ladder HIGH → MEDIUM → LOW → KEYFRAMES → METADATA-ONLY · edge store-and-forward',
    alerts: ['Camera link offline (High)', 'Metadata-only mode (High)', 'Bandwidth adaptation', 'Link restored + edge sync'], thr: null},
};

function mountModule(key, el, full) {
  const m = S.models[key] || {};
  const info = MODINFO[key];
  const thr = info.thr;
  const val = thr ? S.settings?.[thr[0]]?.[thr[1]] : null;
  el.innerHTML = `<div class="panel"><div class="ph">${icon(MOD[key].icon)}<h3>${MOD[key].name}</h3><span class="chip">${esc(m.model || '')}</span><span class="sp"></span>
      <span class="chip" id="modStat"></span>${full ? '' : `<a class="btn sm" href="#/module/${key}">Open module page</a>`}</div>
    <div class="pb stack">
      <div class="mod-head"><div>
        <div class="src">Source: <b>${esc((m.sources || []).join(' · '))}</b></div>
        <div class="mod-meta"><span>Detects: <b>${esc(info.detects)}</b></span></div>
        <div class="mod-meta"><span>Cameras: ${(m.cameras || []).map(c => `<span class="chip clickable" data-cam="${c}">${c}</span>`).join(' ')}</span></div>
        <div class="mod-meta"><span>Raises: ${info.alerts.map(a => `<span class="chip">${esc(a)}</span>`).join(' ')}</span></div>
      </div>
      ${thr ? `<div class="statbox" style="min-width:230px"><div class="l">${thr[2]}</div><div class="row"><input type="range" id="thr" min="${thr[3]}" max="${thr[4]}" step="${thr[5]}" value="${val}" style="flex:1"><b class="mono" id="thrV">${val}</b></div></div>` : ''}
      </div>
      <div id="modBody"></div>
    </div></div>`;
  const offs = [];
  const stat = () => { const mm = S.models[key] || {}; const s = $('#modStat', el); if (s) s.innerHTML = `<span style="color:${mm.running ? '#46CD50' : '#8A98B3'}">●</span> ${mm.running ? 'running' : 'idle'} · ${num(mm.fps, 1)} fps${mm.ms ? ` · ${num(mm.ms, 0)} ms` : ''}`; };
  stat();
  const iv = setInterval(stat, 2000);
  offs.push(() => clearInterval(iv));
  if (thr) {
    $('#thr', el).oninput = e => { $('#thrV', el).textContent = e.target.value; };
    $('#thr', el).onchange = e => settingsPatch({[thr[0]]: {[thr[1]]: +e.target.value}}).then(() => toastMsg('Setting saved', `${thr[2]} = ${e.target.value}`, 'info'));
  }
  $$('[data-cam]', el).forEach(ch => ch.onclick = () => openCamera(ch.dataset.cam));
  const body = $('#modBody', el);
  const ctx = {el: body, full, on: (t, f) => offs.push(on(t, f)), every: (f, ms) => { const i = setInterval(f, ms); offs.push(() => clearInterval(i)); },
    chart: cfg => { const c = new Chart(cfg.canvas, cfg.cfg); offs.push(() => c.destroy()); return c; }};
  (MODBODY[key] || (() => {}))(ctx);
  return () => offs.forEach(f => f());
}

async function moduleEvents(ctx, sel, query, n = 12) {
  const box = $(sel, ctx.el);
  if (!box) return;
  const evs = await api(`/api/events?limit=${n}&${query}`);
  box.innerHTML = evTable(evs, !ctx.full);
  box.onclick = e => { const r = e.target.closest('[data-ev]'); if (r) openEvent(r.dataset.ev); };
}
function sumStat(ids, k) { return ids.reduce((a, c) => a + (S.tick?.cams?.[c]?.stats?.[k] || 0), 0); }

const MODBODY = {
  human(ctx) {
    const ids = camsWith('human');
    ctx.el.innerHTML = `<div class="grid4" id="hStats"></div>
      <div class="grid2" style="margin-top:14px">
        <div class="panel"><div class="ph"><h3>CAM-01 live source</h3></div><div class="pb">${sourceControls('CAM-01')}</div></div>
        <div class="panel"><div class="ph"><h3>Active tracks · dwell per ID</h3><span class="sp"></span><select class="in" id="hCam">${ids.map(c => `<option>${c}</option>`).join('')}</select>
          <label class="switch"><input type="checkbox" id="hHeat"><i></i>Heatmap</label></div><div class="pb tscroll" id="hTracks" style="max-height:230px"></div></div>
      </div>
      <div class="panel" style="margin-top:14px"><div class="ph"><h3>Recent human / crowd / zone events</h3></div><div class="pb tscroll" id="hEv"></div></div>`;
    bindSourceControls('CAM-01', ctx.el);
    const stats = () => {
      $('#hStats', ctx.el).innerHTML = [['People now', sumStat(ids, 'people')], ['Unique people (session)', sumStat(ids, 'people_seen')],
        ['Entries / exits', `${sumStat(ids, 'entries')} / ${sumStat(ids, 'exits')}`], ['CAM-01 AI', `${num(S.tick?.cams?.['CAM-01']?.stats?.infer_fps, 1)}/s · ${num(S.tick?.cams?.['CAM-01']?.stats?.infer_ms, 0)} ms`]]
        .map(([l, v]) => `<div class="statbox"><div class="l">${l}</div><div class="v">${v}</div></div>`).join('');
    };
    const tracks = async () => {
      const cid = $('#hCam', ctx.el).value;
      const t = await api(`/api/cameras/${cid}/tracks`);
      const p = t.filter(x => x.name === 'person');
      $('#hTracks', ctx.el).innerHTML = p.length ? `<table class="t"><thead><tr><th>ID</th><th>Dwell</th><th>Speed</th><th>Conf</th><th>In zones</th></tr></thead><tbody>${
        p.map(x => `<tr><td class="mono">#${x.tid}</td><td class="mono">${num(x.dwell_s, 1)} s</td><td class="mono">${num(x.speed_bh_s, 2)} bh/s</td><td>${num(x.conf, 2)}</td><td>${x.zones.map(z => `<span class="chip">${esc(z)}</span>`).join(' ') || '—'}</td></tr>`).join('')}</tbody></table>`
        : '<div class="empty">No people in view right now.</div>';
      $('#hHeat', ctx.el).checked = !!S.tick?.cams?.[cid]?.heat;
    };
    $('#hHeat', ctx.el).onchange = e => post(`/api/cameras/${$('#hCam', ctx.el).value}/display`, {heatmap: e.target.checked});
    stats(); tracks(); moduleEvents(ctx, '#hEv', 'module=human,fence');
    ctx.on('tick', stats); ctx.every(tracks, 1500); ctx.every(() => moduleEvents(ctx, '#hEv', 'module=human,fence'), 5000);
  },

  vehicle(ctx) {
    ctx.el.innerHTML = `<div class="grid2">
        <div class="panel"><div class="ph"><h3>Vehicles by class · today</h3></div><div class="pb" style="height:220px"><canvas id="vCls"></canvas></div></div>
        <div class="panel"><div class="ph"><h3>Traffic timeline · per camera (10-min)</h3></div><div class="pb" style="height:220px"><canvas id="vTl"></canvas></div></div></div>
      <div class="panel" style="margin-top:14px"><div class="ph"><h3>Live vehicle feed</h3><span class="sp"></span><span class="note">every vehicle track, classified on its best frame · colour computed from the crop</span></div>
        <div class="pb tscroll" id="vFeed" style="max-height:340px"></div></div>
      <div class="panel" style="margin-top:14px"><div class="ph"><h3>Vehicle alerts</h3></div><div class="pb tscroll" id="vEv"></div></div>`;
    const cls = ctx.chart({canvas: $('#vCls', ctx.el), cfg: barCfg([], [], PAL)});
    const tl = ctx.chart({canvas: $('#vTl', ctx.el), cfg: {type: 'line', data: {labels: [], datasets: []}, options: {animation: false, maintainAspectRatio: false, elements: {point: {radius: 0}}, scales: {y: {beginAtZero: true, ticks: {precision: 0}}}}}});
    const stats = async () => {
      const s = await api('/api/vehicles/stats');
      const ks = Object.keys(s.by_class);
      cls.data.labels = ks; cls.data.datasets[0].data = ks.map(k => s.by_class[k]); cls.update();
      const now = Math.floor((Date.now() / 1000 - (Date.now() / 1000 + 19800) % 86400) ); // midnight IST (epoch)
      const slotNow = Math.floor(((Date.now() / 1000) - now) / 600);
      const slots = Array.from({length: Math.min(slotNow + 1, 144)}, (_, i) => i).slice(-36);
      tl.data.labels = slots.map(i => `${String(Math.floor(i / 6)).padStart(2, '0')}:${String((i % 6) * 10).padStart(2, '0')}`);
      tl.data.datasets = Object.entries(s.timeline).map(([cid, m], i) => ({label: cid, data: slots.map(k => m[k] || 0), borderColor: PAL[i % PAL.length], tension: .3}));
      tl.update();
    };
    const feed = () => {
      const f = S.vehicleFeed;
      $('#vFeed', ctx.el).innerHTML = f.length ? `<table class="t"><thead><tr><th>Crop</th><th>Type</th><th>Size</th><th>Colour</th><th>Direction</th><th>Speed</th><th>Camera</th><th>Time</th></tr></thead><tbody>${
        f.map(v => `<tr><td>${v.crop ? `<img class="thumb" src="data:image/jpeg;base64,${v.crop}">` : ''}</td><td><b>${esc(v.cls)}</b> <span class="dim">${num(v.conf, 2)}</span></td><td>${esc(v.size)}</td>
          <td><span class="chip"><span style="width:10px;height:10px;border-radius:50%;background:${esc(v.colour)};border:1px solid #555;display:inline-block"></span>${esc(v.colour)}</span></td>
          <td>${esc(v.direction)}</td><td class="mono">${num(v.speed, 1)} km/h</td><td class="mono">${esc(v.camera)}</td><td class="mono">${fmtT(v.ts)}</td></tr>`).join('')}</tbody></table>`
        : '<div class="empty">Waiting for the next vehicle track to complete…</div>';
    };
    api('/api/vehicles/feed').then(f => { if (!S.vehicleFeed.length) S.vehicleFeed = f; feed(); });
    stats(); moduleEvents(ctx, '#vEv', 'module=vehicle');
    ctx.on('vehicle', feed); ctx.every(stats, 6000); ctx.every(() => moduleEvents(ctx, '#vEv', 'module=vehicle'), 6000);
  },

  face(ctx) {
    ctx.el.innerHTML = `<div class="grid4" id="fStats"></div>
      <div class="panel" style="margin-top:14px"><div class="ph"><h3>Face crops · best shot per person</h3><span class="sp"></span><span class="note">border colour = registry category</span></div><div class="pb crops" id="fCrops"></div></div>
      <div class="grid2" style="margin-top:14px">
        <div class="panel"><div class="ph"><h3>Enrol a face (real template)</h3></div><div class="pb stack" style="gap:8px">
          <div class="row"><input class="in" id="fName" placeholder="Name / service no." style="flex:1"><select class="in" id="fCat">${['Authorised Personnel', 'Local Resident', 'Unregistered Visitor', 'Watchlist'].map(c => `<option>${c}</option>`).join('')}</select></div>
          <div class="row"><select class="in" id="fCam">${camsWith('face').map(c => `<option>${c}</option>`).join('')}</select><button class="btn pri" id="fEnrol">Enrol from live camera</button>
            <label class="btn">Upload photo<input type="file" id="fUp" accept="image/*" hidden></label></div>
          <div class="note" id="fNote">Face the webcam in good light. Enrolled faces are matched for real (SFace embeddings); the illustrated registry samples carry no template and never match.</div>
          <label class="switch"><input type="checkbox" id="fPriv" ${S.settings?.face?.privacy_blur ? 'checked' : ''}><i></i>Privacy: blur non-watchlist faces in exported evidence</label></div></div>
        <div class="panel"><div class="ph"><h3>Recent face events</h3><span class="sp"></span><a class="btn sm" href="#/faces">Face Registry</a></div><div class="pb tscroll" id="fEv" style="max-height:300px"></div></div>
      </div>`;
    const stats = () => {
      const ids = camsWith('face');
      $('#fStats', ctx.el).innerHTML = [['Faces in view', sumStat(ids, 'faces')], ['Face crops (session)', S.faceFeed.length],
        ['Watchlist hits (session)', S.faceFeed.filter(f => f.category === 'Watchlist').length], ['Detector', `${num(S.models.face?.ms, 0)} ms`]]
        .map(([l, v]) => `<div class="statbox"><div class="l">${l}</div><div class="v">${v}</div></div>`).join('');
    };
    const crops = () => {
      $('#fCrops', ctx.el).innerHTML = S.faceFeed.length ? S.faceFeed.map(f => `<div class="c ${esc((f.category || '').split(' ')[0])}"><img src="data:image/jpeg;base64,${f.crop}">
        <div><b>${esc(f.category)}</b></div><div class="dim">${esc(f.camera)} · q ${num(f.quality, 2)}</div></div>`).join('') : '<div class="empty">No faces yet — CAM-06 (corridor) and CAM-01 (webcam) run face detection.</div>';
    };
    const enrol = async (fd) => {
      $('#fNote', ctx.el).textContent = 'Enrolling…';
      try {
        const r = fd ? await fetch('/api/faces/enroll', {method: 'POST', body: fd}).then(x => x.json())
          : await post('/api/faces/enroll', {camera: $('#fCam', ctx.el).value, name: $('#fName', ctx.el).value, category: $('#fCat', ctx.el).value});
        $('#fNote', ctx.el).textContent = r.ok ? `Enrolled ${r.entry.name} (${r.entry.category}) as ${r.entry.id}` : `Failed: ${r.error}`;
      } catch (e) { $('#fNote', ctx.el).textContent = e.message; }
    };
    $('#fEnrol', ctx.el).onclick = () => enrol();
    $('#fUp', ctx.el).onchange = e => { const f = e.target.files[0]; if (!f) return; const fd = new FormData(); fd.append('image', f); fd.append('name', $('#fName', ctx.el).value); fd.append('category', $('#fCat', ctx.el).value); enrol(fd); };
    $('#fPriv', ctx.el).onchange = e => settingsPatch({face: {privacy_blur: e.target.checked}});
    stats(); crops(); moduleEvents(ctx, '#fEv', 'module=face');
    ctx.on('tick', stats); ctx.on('face', () => { crops(); stats(); }); ctx.every(() => moduleEvents(ctx, '#fEv', 'module=face'), 5000);
  },

  anpr(ctx) {
    ctx.el.innerHTML = `<div class="panel"><div class="ph"><h3>ANPR processing</h3><span class="sp"></span><span class="chip" id="aQ"></span>
        ${['CAM-01', 'CAM-02', 'CAM-03', 'CAM-07'].map(c => `<button class="btn sm" data-scan="${c}">Capture &amp; Scan ${c}</button>`).join('')}</div>
      <div class="pb"><div class="anpr-stage">
        <div class="anpr-vehicle" id="aVeh"><div class="note">Waiting for the next vehicle…</div><div class="scan"></div></div>
        <div class="stack">
          <div class="steps" id="aSteps"></div>
          <div id="aResult"></div>
        </div></div></div></div>
      <div class="grid4" id="aStats" style="margin-top:14px"></div>
      <div class="grid2" style="margin-top:14px;grid-template-columns:1.6fr 1fr">
        <div class="panel"><div class="ph"><h3>Recent plate reads</h3></div><div class="pb tscroll" id="aRecent" style="max-height:360px"></div></div>
        <div class="panel"><div class="ph"><h3>Watchlist</h3></div><div class="pb stack" style="gap:8px">
          <div class="row"><input class="in" id="wPlate" placeholder="PB 10 AB 1234" style="flex:1"><input class="in" id="wReason" placeholder="Reason" style="flex:1"><button class="btn pri" id="wAdd">Add</button></div>
          <div id="wList" class="stack" style="gap:6px"></div></div></div>
      </div>`;
    const STEPS = [['captured', 'Best frame captured · vehicle crop'], ['classifying', 'Body type — your anpr_best.pt (YOLOv8l)'], ['reading', 'Plate detection + OCR'], ['plate', 'Indian format check · state decode · watchlist'], ['done', 'Logged to evidence chain']];
    const render = () => {
      const j = S.anpr.job;
      const veh = $('#aVeh', ctx.el);
      if (!j) return;
      const done = !!j.stages.done, skipped = !!j.stages.skipped;
      veh.classList.toggle('busy', !done && !skipped);
      if (j.crop && veh._crop !== j.crop) { veh.innerHTML = `<img src="data:image/jpeg;base64,${j.crop}"><div class="scan"></div>`; veh._crop = j.crop; }
      const last = ['captured', 'classifying', 'reading', 'plate', 'done'].filter(s => j.stages[s]).pop();
      $('#aSteps', ctx.el).innerHTML = `<div class="note">Job #${j.job} · ${esc(j.camera)}</div>` + STEPS.map(([k, l]) => {
        const reached = !!j.stages[k]; const cur = k === last && !done && !skipped;
        if (k === 'classifying' && !j.stages.classifying && j.stages.reading) return `<div class="step done"><i>–</i>${l} <span class="dim">(not a car/SUV — skipped)</span></div>`;
        return `<div class="step ${cur ? 'on' : reached ? 'done' : ''}"><i>${reached && !cur ? '✓' : ''}</i>${l}</div>`;
      }).join('') + (skipped ? `<div class="warnbox">${esc(j.stages.skipped.reason)}</div>` : '');
      const r = j.stages.done?.result;
      if (!r) { $('#aResult', ctx.el).innerHTML = j.stages.plate ? `<div class="row">${plateHTML(j.stages.plate.plate)}</div>` : ''; return; }
      $('#aResult', ctx.el).innerHTML = `
        ${r.status === 'watchlist' ? `<div class="watch-hit">WATCHLIST HIT — ${esc(r.watch_reason)}</div>` : ''}
        <div class="row" style="margin:8px 0">${r.plate ? plateHTML(r.plate_display, r.status === 'manual_review' ? 'bad' : '') : plateHTML(null)}
          ${r.plate_crop ? `<img class="plate-crop" src="data:image/jpeg;base64,${r.plate_crop}">` : ''}</div>
        <dl class="kv"><dt>Status</dt><dd>${esc({valid: 'Valid Indian plate', watchlist: 'Valid · on watchlist', manual_review: 'Low confidence / invalid format — manual review', no_plate: 'No readable plate at this range'}[r.status] || r.status)}${r.status_note ? ` <span class="dim">(${esc(r.status_note)})</span>` : ''}</dd>
          ${r.plate ? `<dt>State</dt><dd>${esc(r.state)}</dd><dt>OCR</dt><dd>${num(r.ocr_conf * 100, 0)}% · raw <span class="mono">${esc(r.raw)}</span></dd><dt>Reader</dt><dd>${esc(r.ocr_source)}</dd>` : ''}
          <dt>Body type</dt><dd>${r.body_type ? `${esc(r.body_type)} <span class="dim">(${num(r.body_conf * 100, 0)}% · anpr_best.pt)</span>` : '—'}</dd>
          <dt>Vehicle</dt><dd>${esc(r.vehicle || '—')} · ${esc(r.colour || '—')} · ${esc(r.direction || '—')}${r.speed_kmh ? ` · ${num(r.speed_kmh, 0)} km/h` : ''}</dd>
          <dt>Camera · time</dt><dd>${esc(r.camera)} · ${fmtT(r.ts)} IST ${r.event_id ? `· <a href="#" data-ev="${esc(r.event_id)}">${esc(r.event_id)}</a>` : ''}</dd></dl>`;
    };
    const stats = () => {
      const st = S.models.anpr?.stats || {};
      $('#aStats', ctx.el).innerHTML = [['Vehicle jobs', st.jobs], ['Plates read', st.plates_read], ['Valid / watchlist', `${st.valid ?? 0} / ${st.watch_hits ?? 0}`],
        ['Manual review / no plate', `${st.manual_review ?? 0} / ${st.no_plate ?? 0}`], ['Your model (body)', `${num(st.ms_body, 0)} ms`], ['Plate det + OCR', `${num(st.ms_plate, 0)} ms`],
        ['Too small / dropped', `${st.skipped_small ?? 0} / ${st.dropped ?? 0}`], ['Plate reader', `<span style="font-size:12px">${esc(S.models.anpr?.plate_source || '')}</span>`]]
        .map(([l, v]) => `<div class="statbox"><div class="l">${l}</div><div class="v">${v ?? '—'}</div></div>`).join('');
      $('#aQ', ctx.el).textContent = `queue ${S.tick?.anpr_queue ?? 0}${S.tick?.anpr_busy ? ' · processing' : ''}`;
    };
    const recent = () => {
      const rs = S.anpr.recent.filter(r => r.plate);
      $('#aRecent', ctx.el).innerHTML = rs.length ? `<table class="t"><thead><tr><th>Vehicle</th><th>Plate</th><th>State</th><th>Body (your model)</th><th>OCR</th><th>Status</th><th>Camera</th><th>Time</th></tr></thead><tbody>${
        rs.map(r => `<tr class="${r.event_id ? 'click' : ''}" ${r.event_id ? `data-ev="${esc(r.event_id)}"` : ''}><td>${r.crop ? `<img class="thumb" src="data:image/jpeg;base64,${r.crop}">` : ''}</td>
          <td>${plateHTML(r.plate_display, 'sm' + (r.status === 'manual_review' ? ' bad' : ''))}</td><td>${esc(r.state)}</td><td>${esc(r.body_type || '—')}</td><td class="mono">${num(r.ocr_conf * 100, 0)}%</td>
          <td>${r.status === 'watchlist' ? '<span class="sev critical">watchlist</span>' : r.status === 'valid' ? '<span class="sev info">valid</span>' : '<span class="sev medium">review</span>'}</td>
          <td class="mono">${esc(r.camera)}</td><td class="mono">${fmtT(r.ts)}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">No plates read yet.</div>';
    };
    const wl = async () => {
      const list = await api('/api/watchlist');
      $('#wList', ctx.el).innerHTML = list.map(w => `<div class="zone-row" style="grid-template-columns:auto 1fr auto">${plateHTML(w.display, 'sm')}<span class="note">${esc(w.reason)} · since ${esc(w.since)}</span><button class="btn sm red" data-wdel="${esc(w.plate)}">✕</button></div>`).join('') || '<div class="note">Empty</div>';
    };
    $('#wAdd', ctx.el).onclick = async () => { try { await post('/api/watchlist', {plate: $('#wPlate', ctx.el).value, reason: $('#wReason', ctx.el).value}); wl(); } catch (e) { toastMsg('Watchlist', e.message, 'medium'); } };
    $('#wList', ctx.el).onclick = async e => { const d = e.target.closest('[data-wdel]'); if (d) { await api(`/api/watchlist?plate=${encodeURIComponent(d.dataset.wdel)}`, {method: 'DELETE'}); wl(); } };
    ctx.el.addEventListener('click', e => {
      const s = e.target.closest('[data-scan]'); if (s) captureScan(s.dataset.scan);
      const ev = e.target.closest('[data-ev]'); if (ev) { e.preventDefault(); openEvent(ev.dataset.ev); }
    });
    api('/api/anpr/recent').then(r => { if (!S.anpr.recent.length) S.anpr.recent = r; recent(); if (!S.anpr.job && r[0]) { S.anpr.job = {job: r[0].job, camera: r[0].camera, crop: r[0].crop, stages: {captured: 1, reading: 1, plate: 1, done: {result: r[0]}}}; render(); } });
    render(); stats(); wl();
    ctx.on('anpr', d => { render(); if (d.stage === 'done') recent(); }); ctx.on('tick', stats);
  },

  fence(ctx) {
    ctx.el.innerHTML = `<div class="panel"><div class="ph"><h3>Zones by camera</h3><span class="sp"></span><button class="btn sm" id="zReset">Reset to default zones</button></div><div class="pb tscroll" id="zTab"></div></div>
      <div class="panel" style="margin-top:14px"><div class="ph"><h3>Recent intrusions</h3></div><div class="pb tscroll" id="fzEv"></div></div>`;
    const load = async () => {
      const rows = [];
      for (const cid of Object.keys(S.cams)) {
        const zs = await api(`/api/zones/${cid}`);
        const st = S.tick?.cams?.[cid]?.stats || {};
        rows.push(`<tr><td class="mono"><b>${cid}</b></td><td>${esc(S.cams[cid].name)}</td><td>${zs.map(z => `<span class="chip"><span style="width:9px;height:9px;border-radius:2px;background:${ZCOL[z.type]}"></span>${esc(z.name)} · ${z.type}${z.schedule !== 'always' ? ' · ' + (z.schedule === 'night' ? 'night only' : z.from + '–' + z.to) : ''}${z.direction !== 'any' && ['tripwire', 'count'].includes(z.type) ? ' · ' + z.direction : ''}</span>`).join(' ') || '<span class="dim">none</span>'}</td>
          <td class="mono">${st.entries ?? 0} / ${st.exits ?? 0}</td><td><button class="btn sm" data-ed="${cid}">Edit zones</button></td></tr>`);
      }
      $('#zTab', ctx.el).innerHTML = `<table class="t"><thead><tr><th>Camera</th><th>Name</th><th>Zones</th><th>In / out</th><th></th></tr></thead><tbody>${rows.join('')}</tbody></table>`;
    };
    $('#zTab', ctx.el).onclick = e => { const b = e.target.closest('[data-ed]'); if (b) openCamera(b.dataset.ed, {edit: true}); };
    $('#zReset', ctx.el).onclick = async () => { await post('/api/zones/reset'); load(); toastMsg('Zones reset', 'Default zones restored on all cameras', 'info'); };
    load(); moduleEvents(ctx, '#fzEv', 'module=fence', 15);
    ctx.every(() => moduleEvents(ctx, '#fzEv', 'module=fence', 15), 5000);
  },

  activity(ctx) {
    const a = S.settings?.activity || {};
    const F = [['loiter_seconds', 'Loiter time (s)'], ['run_speed_bh_s', 'Running speed (body-heights/s)'], ['group_size', 'Group size (people)'], ['group_radius_bh', 'Group radius (body-heights)'],
      ['group_seconds', 'Group duration (s)'], ['crawl_aspect', 'Crawl box aspect (w/h ≥)'], ['repeat_passes', 'Repeated passes (in 60 s)'], ['abandon_seconds', 'Abandoned object after (s)']];
    ctx.el.innerHTML = `<div class="grid2" style="grid-template-columns:1fr 1.6fr">
      <div class="panel"><div class="ph"><h3>Thresholds</h3><span class="sp"></span><button class="btn sm pri" id="aApply">Apply</button></div><div class="pb grid2">${
        F.map(([k, l]) => `<label class="f">${l}<input class="in" type="number" step="any" data-k="${k}" value="${a[k]}"></label>`).join('')}</div></div>
      <div class="panel"><div class="ph"><h3>Behaviours · today</h3></div><div class="pb" style="height:250px"><canvas id="actC"></canvas></div></div></div>
      <div class="panel" style="margin-top:14px"><div class="ph"><h3>Recent suspicious activity · risk score</h3></div><div class="pb tscroll" id="actEv" style="max-height:420px"></div></div>`;
    const c = ctx.chart({canvas: $('#actC', ctx.el), cfg: barCfg([], [], '#FF9933', true)});
    $('#aApply', ctx.el).onclick = () => { const p = {}; $$('[data-k]', ctx.el).forEach(i => p[i.dataset.k] = +i.value); settingsPatch({activity: p}).then(() => toastMsg('Thresholds applied', 'Active on all cameras immediately', 'info')); };
    const load = async () => {
      const evs = await api(`/api/events?module=activity&limit=200&from=${Math.floor(Date.now() / 1000 - ((Date.now() / 1000 + 19800) % 86400))}`);
      const counts = {};
      evs.forEach(e => { counts[e.event_name] = (counts[e.event_name] || 0) + 1; });
      c.data.labels = Object.keys(counts); c.data.datasets[0].data = Object.values(counts); c.update();
      $('#actEv', ctx.el).innerHTML = evs.length ? `<table class="t"><thead><tr><th></th><th>Activity</th><th>Tracks</th><th>Risk</th><th>Camera</th><th>Time</th><th>Status</th></tr></thead><tbody>${
        evs.slice(0, 30).map(e => `<tr class="click" data-ev="${esc(e.event_id)}"><td><img class="thumb" src="${snapUrl(e)}"></td><td><b>${esc(e.event_name)}</b><div class="note">${esc(e.description)}</div></td>
          <td class="mono">${(e.extra.tracks || []).map(t => '#' + t).join(' ')}</td>
          <td><span class="risk"><span class="meter"><i style="width:${e.extra.risk || 0}%"></i></span><b class="mono">${e.extra.risk ?? '—'}</b></span></td>
          <td class="mono">${esc(e.camera_id)}</td><td class="mono">${fmtT(e.ts_epoch)}</td><td><span class="sev ${esc(e.severity)}">${esc(e.severity)}</span></td></tr>`).join('')}</tbody></table>` : '<div class="empty">No activity alerts yet.</div>';
    };
    $('#actEv', ctx.el).onclick = e => { const r = e.target.closest('[data-ev]'); if (r) openEvent(r.dataset.ev); };
    load(); ctx.every(load, 5000);
  },

  night(ctx) {
    const n = S.settings?.night || {};
    const ids = Object.keys(S.cams);
    ctx.el.innerHTML = `<div class="grid2" style="grid-template-columns:1fr 1.5fr">
      <div class="stack">
        <div class="panel"><div class="ph"><h3>Light level by camera</h3></div><div class="pb stack" id="nMeters" style="gap:8px"></div></div>
        <div class="panel"><div class="ph"><h3>Controls</h3></div><div class="pb stack" style="gap:10px">
          <label class="f">Day / night mode<select class="in" id="nMode">${[['auto', 'Auto (brightness)'], ['day', 'Force day'], ['night', 'Force night']].map(([v, l]) => `<option value="${v}" ${n.mode === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
          <label class="f">Enter night below / return to day above (0-255)<span class="row"><input class="in" type="number" id="nIn" value="${n.enter_below}"><input class="in" type="number" id="nOut" value="${n.exit_above}"></span></label>
          <label class="f">CLAHE clip limit <b class="mono" id="nClipV">${n.clahe_clip}</b><input type="range" id="nClip" min="1" max="6" step="0.5" value="${n.clahe_clip}"></label>
          <label class="f">Gamma lift <b class="mono" id="nGamV">${n.gamma}</b><input type="range" id="nGam" min="1" max="3" step="0.1" value="${n.gamma}"></label>
          <button class="btn pri" id="nApply">Apply</button></div></div>
        <div class="panel"><div class="ph"><h3>Detections before vs after enhancement</h3></div><div class="pb" id="nCmp"></div></div>
      </div>
      <div class="stack">
        <div class="panel"><div class="ph"><h3>Original | Enhanced</h3><span class="sp"></span><select class="in" id="nCam">${ids.map(c => `<option ${c === 'CAM-05' ? 'selected' : ''}>${c}</option>`).join('')}</select>
          <select class="in" id="nRight"><option value="enhanced">CLAHE + gamma</option><option value="thermal">Thermal palette</option></select></div>
          <div class="pb"><div class="split" id="nSplit"><img id="nA"><img id="nB"><span class="lbl" style="left:8px">ORIGINAL</span><span class="lbl" id="nBl" style="right:8px">ENHANCED</span><div class="bar" id="nBar"></div></div>
          <input type="range" id="nSlide" min="0" max="100" value="50" style="width:100%;margin-top:8px">
          <div class="row" style="margin-top:6px"><span class="note">Tile display for this camera:</span><div class="seg" id="nDisp">${['normal', 'enhanced', 'thermal'].map(d => `<button data-d="${d}">${d}</button>`).join('')}</div>
          <select class="in" id="nVar" hidden><option value="">CAM-04 day scene</option><option value="night">CAM-04 night scene</option></select></div></div></div>
        <div class="panel"><div class="ph"><h3>Recent night events</h3></div><div class="pb tscroll" id="nEv"></div></div>
      </div></div>`;
    const meters = () => {
      $('#nMeters', ctx.el).innerHTML = ids.map(c => { const s = S.tick?.cams?.[c]?.stats || {}; return `<div class="row" style="gap:8px"><span class="mono" style="width:56px">${c}</span>
        <span class="meter" style="flex:1"><i style="width:${Math.min(100, (s.light || 0) / 2.55)}%;background:linear-gradient(90deg,#000080,#FDD835)"></i></span>
        <span class="mono" style="width:34px">${num(s.light, 0)}</span><span class="chip ${s.night ? 'act' : ''}" style="width:60px;justify-content:center">${s.night ? 'NIGHT' : 'DAY'}</span></div>`; }).join('');
      const c1 = S.tick?.cams?.['CAM-01']?.stats || {};
      $('#nCmp', ctx.el).innerHTML = c1.night_raw != null
        ? `<div class="grid2"><div class="statbox"><div class="l">CAM-01 raw frame</div><div class="v">${c1.night_raw} people</div></div><div class="statbox"><div class="l">CAM-01 after CLAHE+gamma</div><div class="v">${c1.night_enh} people</div></div></div><div class="note" style="margin-top:6px">Measured live every 3 s on the same frame while CAM-01 is in night mode.</div>`
        : '<div class="note">Measured live on CAM-01 once it is in night mode (dim the room or force night). See the test report for the measured before/after on a darkened real clip.</div>';
    };
    const split = () => {
      const cid = $('#nCam', ctx.el).value, mode = $('#nRight', ctx.el).value, t = Date.now();
      const a = new Image(), b = new Image();
      a.onload = () => { const x = $('#nA', ctx.el); if (x) x.src = a.src; };
      b.onload = () => { const x = $('#nB', ctx.el); if (x) x.src = b.src; };
      a.src = `/api/cameras/${cid}/frame?mode=raw&t=${t}`; b.src = `/api/cameras/${cid}/frame?mode=${mode}&t=${t}`;
      $('#nBl', ctx.el).textContent = mode === 'thermal' ? 'THERMAL' : 'ENHANCED';
      $('#nVar', ctx.el).hidden = cid !== 'CAM-04';
      const d = S.tick?.cams?.[cid]?.display;
      $$('#nDisp button', ctx.el).forEach(x => x.classList.toggle('on', x.dataset.d === d));
    };
    const slide = () => { const v = $('#nSlide', ctx.el).value; $('#nB', ctx.el).style.clipPath = `inset(0 0 0 ${v}%)`; $('#nBar', ctx.el).style.left = v + '%'; };
    $('#nSlide', ctx.el).oninput = slide;
    $('#nCam', ctx.el).onchange = split; $('#nRight', ctx.el).onchange = split;
    $('#nDisp', ctx.el).onclick = async e => { const b = e.target.closest('[data-d]'); if (b) { await post(`/api/cameras/${$('#nCam', ctx.el).value}/display`, {mode: b.dataset.d}); } };
    $('#nVar', ctx.el).onchange = e => post('/api/cameras/CAM-04/display', {variant: e.target.value});
    $('#nClip', ctx.el).oninput = e => { $('#nClipV', ctx.el).textContent = e.target.value; };
    $('#nGam', ctx.el).oninput = e => { $('#nGamV', ctx.el).textContent = e.target.value; };
    $('#nApply', ctx.el).onclick = () => settingsPatch({night: {mode: $('#nMode', ctx.el).value, enter_below: +$('#nIn', ctx.el).value, exit_above: +$('#nOut', ctx.el).value,
      clahe_clip: +$('#nClip', ctx.el).value, gamma: +$('#nGam', ctx.el).value}}).then(() => toastMsg('Night settings applied', 'Live on all cameras', 'info'));
    meters(); split(); slide(); moduleEvents(ctx, '#nEv', 'module=night');
    ctx.on('tick', meters); ctx.every(split, 1000); ctx.every(() => moduleEvents(ctx, '#nEv', 'module=night'), 6000);
  },

  network(ctx) {
    ctx.el.innerHTML = `<div class="warnbox">Link telemetry below is <b>simulated</b> per link type (Fibre / 4G / VSAT / Radio) with scripted degradations. What it drives is real: tile resolution and fps actually step down, metadata-only mode actually stops video, and events raised during an outage are actually held at the edge and synced on reconnect.</div>
      <div class="grid2" style="margin-top:14px;grid-template-columns:1.2fr 1fr">
        <div class="panel"><div class="ph"><h3>Bandwidth · last 5 min</h3></div><div class="pb" style="height:260px"><canvas id="nwBw"></canvas></div></div>
        <div class="panel"><div class="ph"><h3>Topology</h3></div><div class="pb" id="nwTopo"></div></div></div>
      <div class="panel" style="margin-top:14px"><div class="ph"><h3>Per-camera links</h3><span class="sp"></span><span class="note">Simulate a condition on any link:</span></div><div class="pb tscroll" id="nwTab"></div></div>
      <div class="grid2" style="margin-top:14px">
        <div class="panel"><div class="ph"><h3>Latency · last 5 min</h3></div><div class="pb" style="height:200px"><canvas id="nwLat"></canvas></div></div>
        <div class="panel"><div class="ph"><h3>Adaptation log</h3></div><div class="pb tscroll" id="nwLog" style="max-height:220px"></div></div></div>`;
    const lineCfg = unit => ({type: 'line', data: {labels: [], datasets: []}, options: {animation: false, maintainAspectRatio: false, elements: {point: {radius: 0}},
      plugins: {legend: {position: 'bottom'}}, scales: {x: {ticks: {maxTicksLimit: 6}}, y: {beginAtZero: true, title: {display: true, text: unit}}}}});
    const bw = ctx.chart({canvas: $('#nwBw', ctx.el), cfg: lineCfg('Mbps')});
    const lat = ctx.chart({canvas: $('#nwLat', ctx.el), cfg: lineCfg('ms')});
    const load = async () => {
      const d = await api('/api/network');
      const cids = Object.keys(d.links);
      const h0 = d.history[cids[0]] || [];
      const labels = h0.map(r => fmtT(r[0]).slice(0, 5 + 3));
      bw.data.labels = labels; lat.data.labels = labels;
      bw.data.datasets = cids.map((c, i) => ({label: c, data: (d.history[c] || []).map(r => r[1]), borderColor: PAL[i % PAL.length], borderWidth: 1.6, tension: .25}));
      lat.data.datasets = cids.map((c, i) => ({label: c, data: (d.history[c] || []).map(r => r[2]), borderColor: PAL[i % PAL.length], borderWidth: 1.4, tension: .25}));
      bw.update(); lat.update();
      $('#nwTab', ctx.el).innerHTML = `<table class="t"><thead><tr><th>Camera</th><th>Link</th><th>Tier</th><th>Stream</th><th>Bandwidth</th><th>Latency</th><th>Jitter</th><th>Loss</th><th>Signal</th><th>Uptime</th><th>Edge queue</th><th></th></tr></thead><tbody>${
        cids.map(c => { const l = d.links[c]; return `<tr><td class="mono"><b>${c}</b></td><td>${esc(l.link)}</td><td><span class="tier ${l.tier}">${l.tier}</span></td>
          <td class="mono">${l.out_wh ? l.out_wh.join('×') : '—'} @ ${l.fps_cap} fps</td><td class="mono">${num(l.bandwidth, 2)} Mbps</td><td class="mono">${l.latency} ms</td><td class="mono">${l.jitter} ms</td>
          <td class="mono">${num(l.loss, 2)}%</td><td><span class="bars ${sigClass(l.signal)}"><i></i><i></i><i></i><i></i></span> <span class="mono dim">${l.signal}%</span></td>
          <td class="mono">${num(l.uptime_pct, 2)}%</td><td class="mono">${l.queued}${l.scenario ? ` <span class="chip act">${l.scenario}</span>` : ''}</td>
          <td class="row" style="gap:4px"><button class="btn sm" data-sim="${c}" data-k="degrade">Degrade</button><button class="btn sm" data-sim="${c}" data-k="outage">Outage</button></td></tr>`; }).join('')}</tbody></table>`;
      topo(d.links);
    };
    const topo = links => {
      const groups = [['EDGE · BOP ALPHA', ['CAM-01', 'CAM-02', 'CAM-03']], ['EDGE · WATCHTOWER DELTA', ['CAM-04', 'CAM-05']], ['EDGE · BOP FOXTROT', ['CAM-06', 'CAM-07']], ['EDGE · SECTOR HQ', ['CAM-08']]];
      Object.keys(links).filter(c => !groups.some(g => g[1].includes(c))).forEach(c => groups[0][1].push(c));
      const col = t => ({HIGH: '#1FAE12', MEDIUM: '#1FAE12', LOW: '#FDD835', KEYFRAMES: '#FF9933', METADATA: '#E53935', OFFLINE: '#E53935'}[t] || '#8A98B3');
      let y = 18, svg = '';
      groups.forEach(([g, cams], gi) => {
        const gy = y + cams.length * 13;
        cams.forEach((c, i) => { const l = links[c] || {}; const cy = y + i * 26;
          svg += `<line x1="92" y1="${cy + 9}" x2="200" y2="${gy}" stroke="${col(l.tier)}" stroke-width="2.5" ${l.tier === 'OFFLINE' ? 'stroke-dasharray="6 5"' : ''}/>
            <rect x="8" y="${cy}" width="84" height="18" rx="4" fill="#16213A" stroke="#2A3858"/><text x="50" y="${cy + 13}" fill="#fff" font-size="11" text-anchor="middle" font-family="JetBrains Mono">${c}</text>`; });
        svg += `<line x1="330" y1="${gy}" x2="420" y2="170" stroke="#FF9933" stroke-width="2"/><rect x="200" y="${gy - 13}" width="130" height="26" rx="6" fill="#121B2E" stroke="#138808"/>
          <text x="265" y="${gy + 4}" fill="#C9D3E3" font-size="10" text-anchor="middle" font-family="Inter">${g}</text>`;
        y += cams.length * 26 + 14;
      });
      svg += `<rect x="420" y="146" width="112" height="48" rx="8" fill="#16213A" stroke="#FF9933" stroke-width="2"/><text x="476" y="166" fill="#fff" font-size="12" font-weight="700" text-anchor="middle" font-family="Rajdhani">COMMAND</text><text x="476" y="182" fill="#fff" font-size="12" font-weight="700" text-anchor="middle" font-family="Rajdhani">CENTRE</text>`;
      $('#nwTopo', ctx.el).innerHTML = `<svg viewBox="0 0 540 ${Math.max(340, y)}" style="width:100%">${svg}</svg><div class="note">Edge nodes run inference + buffer events; the command centre aggregates events and evidence.</div>`;
    };
    const logs = async () => {
      const evs = await api('/api/events?module=network&limit=40');
      $('#nwLog', ctx.el).innerHTML = evs.length ? evs.map(e => `<div style="padding:5px 0;border-bottom:1px solid var(--border);font-size:12px"><span class="mono dim">${fmtT(e.ts_epoch)}</span> <span class="sev ${esc(e.severity)}">${esc(e.event_name)}</span> ${esc(e.description)}</div>`).join('') : '<div class="empty">No link changes yet (scripted degradations start ~45 s after boot).</div>';
    };
    $('#nwTab', ctx.el).onclick = async e => { const b = e.target.closest('[data-sim]'); if (b) { await post(`/api/network/${b.dataset.sim}/simulate`, {kind: b.dataset.k}); toastMsg('Network simulation', `${b.dataset.k} on ${b.dataset.sim}`, 'medium'); } };
    load(); logs(); ctx.every(load, 2000); ctx.every(logs, 4000);
  },
};
