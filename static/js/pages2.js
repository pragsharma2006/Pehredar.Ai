/* Pehredar.ai — remaining pages */
'use strict';

// =================================================================== live cameras
ROUTES.cameras = (main) => {
  const ids = S.order.filter(c => S.cams[c]);
  main.innerHTML = pageH('Live Cameras', `${ids.length} cameras · live, recorded and synthetic sources labelled on every tile`,
    '<a class="btn" href="#/integrations">+ Onboard RTSP / ONVIF camera</a>') + `
    <div class="cam-grid g3" id="cg">${ids.map(tileHTML).join('')}</div>
    <div class="panel" style="margin-top:14px"><div class="ph"><h3>Camera inventory</h3></div><div class="pb tscroll" id="ctab"></div></div>`;
  bindTiles($('#cg'));
  const tab = () => {
    $('#ctab').innerHTML = `<table class="t"><thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Source</th><th>Status</th><th>Res · fps</th><th>Link</th><th>Stream</th><th>People / vehicles</th><th>Modules</th></tr></thead><tbody>${
      ids.map(c => { const k = S.cams[c], t = S.tick?.cams?.[c] || {}, s = t.stats || {}, n = t.net || {};
        return `<tr class="click" data-c="${c}"><td class="mono"><b>${c}</b></td><td>${esc(k.name)}<div class="note">${esc(k.location)}</div></td><td>${camTag(k)}</td>
          <td class="note" style="max-width:260px">${esc(t.source || k.source)}</td><td>${esc(String(s.status || '').split('—')[0])}</td>
          <td class="mono">${(t.wh || [0, 0]).join('×')} · ${num(s.fps, 1)}</td><td>${esc(k.link)}</td><td><span class="tier ${n.tier}">${n.tier || '—'}</span></td>
          <td class="mono">${s.people ?? 0} / ${s.vehicles ?? 0}</td><td>${(k.modules || []).map(m => `<span class="chip">${esc(MOD[m]?.name || m)}</span>`).join(' ')}</td></tr>`; }).join('')}</tbody></table>`;
  };
  $('#ctab').onclick = e => { const r = e.target.closest('[data-c]'); if (r) openCamera(r.dataset.c); };
  tab(); pageOn('tick', tab);
};

// =================================================================== AI modules
ROUTES.modules = (main) => {
  main.innerHTML = pageH('AI Modules', 'Eight capabilities from the problem statement — each with its own page, live status and honest data-source label') + '<div class="grid4" id="mods"></div>';
  const draw = () => {
    $('#mods').innerHTML = MOD_ORDER.map(k => { const m = S.models[k] || {}; return `<a class="panel" href="#/module/${k}" style="text-decoration:none;color:inherit">
      <div class="ph">${icon(MOD[k].icon)}<h3>${MOD[k].name}</h3><span class="sp"></span><span style="color:${m.running ? '#46CD50' : '#8A98B3'}">●</span></div>
      <div class="pb stack" style="gap:8px"><div class="mono" style="font-size:11.5px;color:var(--saffron-2)">${esc(m.model || '')}</div>
      <div class="note">${esc(MODINFO[k].detects)}</div>
      <div class="row"><span class="chip">${num(m.fps, 1)} fps</span>${m.ms ? `<span class="chip">${num(m.ms, 0)} ms</span>` : ''}<span class="chip">${(m.cameras || []).length} cameras</span>
        <span class="chip ${S.toggles[k] === false ? '' : 'on'}">overlay ${S.toggles[k] === false ? 'off' : 'on'}</span></div>
      <div class="src">Source: <b>${esc((m.sources || []).join(' · '))}</b></div></div></a>`; }).join('');
  };
  draw(); pageEvery(draw, 3000);
};
ROUTES.module = (main, [key]) => {
  if (!MOD[key]) { location.hash = '#/modules'; return; }
  main.innerHTML = pageH(MOD[key].name, `AI module · <a href="#/modules">all modules</a>`, `<div class="seg">${MOD_ORDER.map(k => `<button onclick="location.hash='#/module/${k}'" class="${k === key ? 'on' : ''}">${MOD[k].name.split(' ')[0]}</button>`).join('')}</div>`) +
    `<div class="cam-grid g4" id="mcams" style="margin-bottom:14px"></div><div id="mp"></div>`;
  const cams = (S.models[key]?.cameras || camsWith(key)).slice(0, 4);
  $('#mcams').innerHTML = cams.map(tileHTML).join('');
  bindTiles($('#mcams'));
  S.pageOff.push(mountModule(key, $('#mp'), true));
};

// =================================================================== event log
ROUTES.events = (main, [preset]) => {
  const opts = (arr, sel) => arr.map(([v, l]) => `<option value="${v}" ${sel === v ? 'selected' : ''}>${l}</option>`).join('');
  main.innerHTML = pageH('Event Log', 'Tamper-evident evidence chain · every event: IST timestamp, alert type, real snapshot, SHA-256 hash linked to the previous event') + `
    <div class="grid2" style="grid-template-columns:1fr 1fr 1fr;margin-bottom:14px">
      <div class="panel"><div class="ph"><h3>Integrity</h3></div><div class="pb stack" style="gap:8px"><div id="integ" class="chain">…</div>
        <div class="row"><button class="btn pri" id="vBtn">Verify integrity</button></div>
        <div class="note">Tamper demo (reversible):</div>
        <div class="row"><button class="btn sm red" data-tamper="record">Edit a stored record</button><button class="btn sm red" data-tamper="snapshot">Swap a snapshot file</button><button class="btn sm grn" id="restore">Restore originals</button></div></div></div>
      <div class="panel"><div class="ph"><h3>Hash code generator</h3></div><div class="pb stack" style="gap:8px">
        <div class="drop" id="hDrop">Drop any snapshot / evidence file here, or click to choose<input type="file" id="hFile" hidden></div><div id="hOut" class="note">Computes SHA-256 locally on the server and checks it against every logged snapshot and event hash.</div></div></div>
      <div class="panel"><div class="ph"><h3>Export</h3></div><div class="pb stack" style="gap:8px"><div class="note">Uses the filters below.</div>
        <div class="row"><button class="btn" data-exp="csv">CSV</button><button class="btn" data-exp="json">JSON</button><button class="btn pri" data-exp="pdf">PDF evidence report</button></div>
        <label class="switch"><input type="checkbox" id="priv" checked><i></i>Blur non-watchlist faces in export</label><div class="note">Stored evidence is never altered; privacy blur applies to the exported copy only.</div></div></div>
    </div>
    <div class="panel"><div class="ph"><h3>Events</h3><span class="sp"></span><span class="note" id="eCount"></span></div>
      <div class="pb stack" style="gap:10px">
        <div class="row">
          <input class="in" type="date" id="fFrom"><input class="in" type="date" id="fTo">
          <select class="in" id="fMod"><option value="">All modules</option>${opts(MOD_ORDER.map(k => [k, MOD[k].name]))}</select>
          <select class="in" id="fCam"><option value="">All cameras</option>${opts(Object.keys(S.cams).map(c => [c, c]))}</select>
          <select class="in" id="fSev"><option value="">All severities</option>${opts([['critical', 'Critical'], ['high', 'High'], ['medium', 'Medium'], ['info', 'Info'], ['critical,high', 'Critical + High']], preset === 'active' ? 'critical,high' : '')}</select>
          <select class="in" id="fSt"><option value="">All statuses</option>${opts([['new', 'New'], ['acknowledged', 'Acknowledged'], ['escalated', 'Escalated'], ['false_alarm', 'False alarm'], ['resolved', 'Resolved'], ['new,escalated', 'Open (new + escalated)']], preset === 'active' ? 'new,escalated' : '')}</select>
          <input class="in" id="fQ" placeholder="Search id, plate, zone…" style="flex:1;min-width:160px"><button class="btn pri" id="fGo">Apply</button></div>
        <div class="tscroll" id="eTab" style="max-height:640px"></div></div></div>`;
  const q = () => {
    const p = new URLSearchParams({limit: 500});
    const d = id => $(id).value ? new Date($(id).value + 'T00:00:00+05:30').getTime() / 1000 : null;
    if (d('#fFrom')) p.set('from', d('#fFrom'));
    if (d('#fTo')) p.set('to', d('#fTo') + 86399);
    [['module', '#fMod'], ['camera', '#fCam'], ['severity', '#fSev'], ['status', '#fSt'], ['q', '#fQ']].forEach(([k, id]) => { if ($(id).value) p.set(k, $(id).value); });
    return p;
  };
  const load = async () => {
    const evs = await api('/api/events?' + q());
    $('#eCount').textContent = `${evs.length} shown`;
    $('#eTab').innerHTML = evTable(evs);
  };
  const integ = v => { const el = $('#integ'); if (!el || !v) return; el.classList.toggle('bad', !v.ok); el.textContent = v.ok ? `✓ Chain intact — ${v.checked} events, ${v.actions_checked ?? 0} operator actions verified` : `✕ Tampering detected at ${v.failed_at} — ${v.reason}`; };
  $('#eTab').onclick = e => { const r = e.target.closest('[data-ev]'); if (r) openEvent(r.dataset.ev); };
  $('#fGo').onclick = load;
  $('#fQ').onkeydown = e => { if (e.key === 'Enter') load(); };
  $('#vBtn').onclick = async () => integ(await verifyChain());
  $$('[data-tamper]').forEach(b => b.onclick = async () => {
    try { const r = await post('/api/integrity/tamper', {kind: b.dataset.tamper}); S.integrity = r.verify; renderChain(); integ(r.verify);
      toastMsg('Tamper demo', `${b.dataset.tamper === 'record' ? 'Edited the stored description of' : 'Swapped the snapshot file of'} ${r.tampered} — verification now fails there`, 'high'); }
    catch (e) { toastMsg('Tamper demo', e.message, 'medium'); }
  });
  $('#restore').onclick = async () => { const r = await post('/api/integrity/restore'); S.integrity = r.verify; renderChain(); integ(r.verify); toastMsg('Restored', `${r.restored.length} record(s) restored`, 'info'); };
  const hash = async f => {
    const fd = new FormData(); fd.append('file', f);
    $('#hOut').textContent = 'Hashing…';
    const r = await fetch('/api/hash', {method: 'POST', body: fd}).then(x => x.json());
    $('#hOut').innerHTML = `<div><b>${esc(r.name)}</b> · ${r.bytes} bytes</div><div class="hash">SHA-256 ${esc(r.sha256)}</div>` +
      (r.matches.length ? r.matches.map(m => `<div style="color:#6BE35F;margin-top:4px">✓ Matches ${esc(m.event_id)} · ${esc(m.event_name)} · ${esc(m.camera_id)} — file is the original evidence</div>`).join('')
        : '<div style="color:#FF8A86;margin-top:4px">✕ No logged event has this hash — not an original snapshot (or it was modified)</div>');
  };
  const drop = $('#hDrop');
  drop.onclick = () => $('#hFile').click();
  $('#hFile').onchange = e => e.target.files[0] && hash(e.target.files[0]);
  drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); if (e.dataTransfer.files[0]) hash(e.dataTransfer.files[0]); };
  $$('[data-exp]').forEach(b => b.onclick = () => { const p = q(); p.set('fmt', b.dataset.exp); p.set('privacy', $('#priv').checked ? '1' : '0'); location.href = '/api/export?' + p; });
  integ(S.integrity); load();
  pageOn('integrity', integ);
  pageEvery(load, 8000);
};

// =================================================================== vehicle registry
ROUTES.vehicles = (main) => {
  main.innerHTML = pageH('Vehicle Registry', 'Every validated plate read by ANPR · first/last seen, times seen, crossing history, watchlist status',
    '<a class="btn" id="vcsv" href="/api/vehicles.csv">Export CSV</a>') + `
    <div class="panel"><div class="ph"><h3>Registry</h3><span class="sp"></span><input class="in" id="vq" placeholder="Search plate, state, type, colour…" style="width:280px">
      <label class="switch"><input type="checkbox" id="vw"><i></i>Watchlist only</label></div><div class="pb tscroll" id="vtab" style="max-height:560px"></div></div>
    <div class="panel" style="margin-top:14px" id="vhist" hidden></div>`;
  const load = async () => {
    const p = new URLSearchParams(); if ($('#vq').value) p.set('q', $('#vq').value); if ($('#vw').checked) p.set('watch', '1');
    $('#vcsv').href = '/api/vehicles.csv?' + p;
    const rows = await api('/api/vehicles?' + p);
    $('#vtab').innerHTML = rows.length ? `<table class="t"><thead><tr><th>Vehicle</th><th>Plate</th><th>State</th><th>Type</th><th>Body (your model)</th><th>Colour</th><th>Seen</th><th>First seen</th><th>Last seen</th><th>Last camera</th><th>Status</th></tr></thead><tbody>${
      rows.map(v => `<tr class="click" data-p="${esc(v.plate)}"><td>${v.crop ? `<img class="thumb" src="/events/${esc(v.crop)}">` : ''}</td><td>${plateHTML(v.display, 'sm')}</td><td>${esc(v.state)}</td>
        <td>${esc(v.vehicle_type)}</td><td>${esc(v.body_type || '—')}</td><td>${esc(v.colour || '—')}</td><td class="mono">${v.times_seen}×</td><td class="mono">${fmtDT(v.first_seen)}</td>
        <td class="mono">${fmtDT(v.last_seen)}</td><td class="mono">${esc(v.last_camera)}</td><td>${v.watchlist ? `<span class="sev critical" title="${esc(v.watch_reason)}">watchlist</span>` : '<span class="sev info">clear</span>'}</td></tr>`).join('')}</tbody></table>`
      : '<div class="empty">No plates in the registry yet — CAM-02 (ANPR lane) reads a vehicle every ~7 s.</div>';
  };
  $('#vtab').onclick = async e => {
    const r = e.target.closest('[data-p]'); if (!r) return;
    const h = await api(`/api/vehicles/${encodeURIComponent(r.dataset.p)}`);
    const v = h.vehicle;
    const box = $('#vhist'); box.hidden = false;
    box.innerHTML = `<div class="ph"><h3>Crossing history · </h3>${plateHTML(v.display, 'sm')}<span class="sp"></span>${v.watchlist ? `<span class="sev critical">${esc(v.watch_reason)}</span>` : ''}</div>
      <div class="pb"><table class="t"><thead><tr><th>Time (IST)</th><th>Camera</th><th>Direction</th><th>Evidence</th></tr></thead><tbody>${
      h.crossings.map(c => `<tr><td class="mono">${fmtDT(c.ts_epoch)}</td><td class="mono">${esc(c.camera_id)}</td><td>${esc(c.direction || '—')}</td><td>${c.event_id ? `<a href="#" data-ev="${esc(c.event_id)}">${esc(c.event_id)}</a>` : '<span class="dim">queued at edge</span>'}</td></tr>`).join('')}</tbody></table></div>`;
    box.onclick = ev => { const a = ev.target.closest('[data-ev]'); if (a) { ev.preventDefault(); openEvent(a.dataset.ev); } };
    box.scrollIntoView({behavior: 'smooth'});
  };
  $('#vq').oninput = () => { clearTimeout(load.t); load.t = setTimeout(load, 250); };
  $('#vw').onchange = load;
  load(); pageEvery(load, 7000);
};

// =================================================================== face registry
ROUTES.faces = (main) => {
  const CATS = ['All', 'Authorised Personnel', 'Local Resident', 'Unregistered Visitor', 'Watchlist'];
  let cat = 'All';
  main.innerHTML = pageH('Face Registry', 'Enrolled faces with real SFace templates match live; illustrated samples are display-only',
    '<a class="btn pri" href="#/module/face">Enrol a face</a>') + `
    <div class="seg" id="fcat" style="margin-bottom:14px">${CATS.map(c => `<button data-c="${c}" class="${c === cat ? 'on' : ''}">${c}</button>`).join('')}</div>
    <div class="grid3" id="fgrid"></div>`;
  const load = async () => {
    const list = (await api('/api/faces')).filter(e => cat === 'All' || e.category === cat);
    const col = {'Authorised Personnel': '#1FAE12', 'Local Resident': '#FF9933', 'Unregistered Visitor': '#8A98B3', Watchlist: '#E53935'};
    $('#fgrid').innerHTML = list.length ? list.map(e => `<div class="panel"><div class="pb" style="display:grid;grid-template-columns:96px 1fr;gap:12px">
      <img src="/data/${esc(e.image)}" style="width:96px;height:96px;object-fit:cover;border-radius:10px;border:2px solid ${col[e.category]}">
      <div style="min-width:0"><div class="head" style="font-size:16px">${esc(e.name)}</div><div class="mono dim" style="font-size:11px">${esc(e.id)}</div>
        <div class="row" style="margin:5px 0"><span class="chip" style="border-color:${col[e.category]}">${esc(e.category)}</span>${e.has_template ? '<span class="chip on">SFace template</span>' : '<span class="chip">no template</span>'}</div>
        <div class="note">${esc(e.source)}${e.last_seen ? ` · last seen ${fmtISO(e.last_seen)}` : ''}</div>
        ${(e.matches || []).slice(0, 3).map(m => `<div class="note mono">✓ ${esc(m.camera)} · ${esc(m.ts.slice(11, 19))} · sim ${m.score} · <a href="#" data-ev="${esc(m.event_id)}">${esc(m.event_id)}</a></div>`).join('')}
        ${e.id.startsWith('SAMPLE-') ? '' : `<button class="btn sm red" data-del="${esc(e.id)}" style="margin-top:6px">Remove</button>`}</div></div></div>`).join('')
      : '<div class="empty">No entries in this category.</div>';
  };
  $('#fcat').onclick = e => { const b = e.target.closest('[data-c]'); if (!b) return; cat = b.dataset.c; $$('#fcat button').forEach(x => x.classList.toggle('on', x === b)); load(); };
  $('#fgrid').onclick = async e => {
    const d = e.target.closest('[data-del]'); if (d) { await api(`/api/faces/${d.dataset.del}`, {method: 'DELETE'}); load(); }
    const a = e.target.closest('[data-ev]'); if (a) { e.preventDefault(); openEvent(a.dataset.ev); }
  };
  load(); pageEvery(load, 8000);
};

// =================================================================== map
ROUTES.map = (main) => {
  const B = {lat0: 31.575, lat1: 31.640, lon0: 74.500, lon1: 74.620};
  main.innerHTML = pageH('Map View', 'Offline schematic sector map · pin colour = camera status · click a pin to open the camera') + `
    <div class="grid2" style="grid-template-columns:1fr 300px"><div class="mapwrap" id="mw"><img src="/static/img/sector_map.svg" alt="sector map"></div>
    <div class="panel"><div class="ph"><h3>Legend</h3></div><div class="pb stack" style="gap:8px">
      ${[['#1FAE12', 'Online · full stream'], ['#FDD835', 'Degraded link (low / keyframes / metadata)'], ['#E53935', 'Active alert (blinking)'], ['#6B7A90', 'Offline — edge buffering']].map(([c, l]) => `<div class="row"><span style="width:14px;height:14px;border-radius:50%;background:${c}"></span>${l}</div>`).join('')}
      <div class="note">Schematic, not to scale. Border line and river are illustrative — no official map data is used.</div><div id="mlist"></div></div></div></div>`;
  const draw = () => {
    const mw = $('#mw');
    $$('.pin', mw).forEach(p => p.remove());
    Object.values(S.cams).forEach(c => {
      const t = S.tick?.cams?.[c.id] || {}, n = t.net || {};
      const x = (c.gps[1] - B.lon0) / (B.lon1 - B.lon0) * 100, y = (B.lat1 - c.gps[0]) / (B.lat1 - B.lat0) * 100;
      const cls = t.alert ? 'alert' : n.tier === 'OFFLINE' ? 'offline' : ['LOW', 'KEYFRAMES', 'METADATA'].includes(n.tier) ? 'degraded' : '';
      mw.insertAdjacentHTML('beforeend', `<div class="pin ${cls}" data-c="${c.id}" style="left:${x}%;top:${y}%" title="${esc(c.name)}"><span class="lb">${c.id}</span><span class="p"></span></div>`);
    });
    $('#mlist').innerHTML = Object.values(S.cams).map(c => `<div class="row note" style="gap:6px"><b class="mono">${c.id}</b>${esc(c.name)}</div>`).join('');
  };
  $('#mw').onclick = e => { const p = e.target.closest('.pin'); if (p) openCamera(p.dataset.c); };
  draw(); pageOn('tick', draw);
};

// =================================================================== analytics
ROUTES.analytics = (main) => {
  main.innerHTML = pageH('Analytics', 'Computed from the evidence log', `<div class="seg" id="rng"><button data-d="1" class="on">Today</button><button data-d="7">7 days</button></div>
    <label class="switch"><input type="checkbox" id="hist"><i></i>Include sample history (generated)</label>`) + `
    <div class="warnbox" id="histNote" hidden>Including the generated 7-day SAMPLE history (data/generated/history.db, every row flagged) so trends are visible in a demo. Live system events alone are shown when this is off.</div>
    <div class="grid4" id="aK" style="margin:14px 0"></div>
    <div class="grid3">
      <div class="panel"><div class="ph"><h3>Events per hour (IST)</h3></div><div class="pb" style="height:230px"><canvas id="c1"></canvas></div></div>
      <div class="panel"><div class="ph"><h3>By module</h3></div><div class="pb" style="height:230px"><canvas id="c2"></canvas></div></div>
      <div class="panel"><div class="ph"><h3>Severity split</h3></div><div class="pb" style="height:230px"><canvas id="c3"></canvas></div></div>
      <div class="panel"><div class="ph"><h3>By camera</h3></div><div class="pb" style="height:230px"><canvas id="c4"></canvas></div></div>
      <div class="panel"><div class="ph"><h3>Vehicle classes</h3></div><div class="pb" style="height:230px"><canvas id="c5"></canvas></div></div>
      <div class="panel"><div class="ph"><h3>Intrusions by zone</h3></div><div class="pb" style="height:230px"><canvas id="c6"></canvas></div></div>
      <div class="panel"><div class="ph"><h3>Day vs night</h3></div><div class="pb" style="height:230px"><canvas id="c7"></canvas></div></div>
      <div class="panel" style="grid-column:span 2"><div class="ph"><h3>Top plates</h3></div><div class="pb tscroll" id="tp" style="max-height:230px"></div></div>
    </div>`;
  let days = 1;
  const ch = {
    c1: chart($('#c1'), barCfg([...Array(24).keys()].map(h => String(h).padStart(2, '0')), [])),
    c2: chart($('#c2'), doughnutCfg([], [])), c3: chart($('#c3'), doughnutCfg([], [], [])),
    c4: chart($('#c4'), barCfg([], [], '#5B8DEF')), c5: chart($('#c5'), barCfg([], [], '#1FAE12')),
    c6: chart($('#c6'), barCfg([], [], '#E53935', true)), c7: chart($('#c7'), barCfg(['Day', 'Night'], [], ['#FF9933', '#000080'])),
  };
  const set = (c, obj, colors) => { c.data.labels = Object.keys(obj); c.data.datasets[0].data = Object.values(obj); if (colors) c.data.datasets[0].backgroundColor = colors; c.update(); };
  const load = async () => {
    const h = $('#hist').checked;
    $('#histNote').hidden = !h;
    const a = await api(`/api/analytics?days=${days}&history=${h ? 1 : 0}`);
    $('#aK').innerHTML = [['Events', a.total], ['False-alarm rate', a.false_alarm_rate == null ? '—' : num(a.false_alarm_rate * 100, 1) + '%'],
      ['Avg response (alert→ack)', a.avg_response_s == null ? '—' : num(a.avg_response_s, 0) + ' s'], ['Night share', a.total ? num(100 * a.day_night.night / a.total, 0) + '%' : '—']]
      .map(([l, v]) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div></div>`).join('');
    ch.c1.data.datasets[0].data = a.per_hour; ch.c1.update();
    set(ch.c2, a.by_module); set(ch.c3, a.severity, Object.keys(a.severity).map(s => SEV_COL[s]));
    set(ch.c4, a.by_camera); set(ch.c5, a.vehicle_classes); set(ch.c6, a.intrusions_by_zone);
    ch.c7.data.datasets[0].data = [a.day_night.day, a.day_night.night]; ch.c7.update();
    $('#tp').innerHTML = a.top_plates.length ? `<table class="t"><thead><tr><th>Plate</th><th>State</th><th>Times seen</th><th>Watchlist</th><th></th></tr></thead><tbody>${
      a.top_plates.map(p => `<tr><td>${plateHTML(p.display, 'sm')}</td><td>${esc(p.state)}</td><td class="mono">${p.times_seen}</td><td>${p.watchlist ? '<span class="sev critical">yes</span>' : '—'}</td><td>${p.sample ? '<span class="chip">sample</span>' : ''}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">No plates yet.</div>';
  };
  $('#rng').onclick = e => { const b = e.target.closest('[data-d]'); if (!b) return; days = +b.dataset.d; $$('#rng button').forEach(x => x.classList.toggle('on', x === b)); load(); };
  $('#hist').onchange = load;
  load(); pageEvery(load, 10000);
};

// =================================================================== network (page)
ROUTES.network = (main) => {
  main.innerHTML = pageH('Network Health', 'Per-camera link telemetry, adaptive streaming, metadata-only mode and edge store-and-forward') + '<div id="np"></div>';
  S.pageOff.push(mountModule('network', $('#np'), true));
};

// =================================================================== integrations
ROUTES.integrations = (main) => {
  const host = location.host;
  main.innerHTML = pageH('Integrations', 'Plug Pehredar.ai into existing command-and-control (C2) systems') + `
    <div class="grid2">
      <div class="panel"><div class="ph"><h3>REST API</h3></div><div class="pb stack" style="gap:8px">
        <table class="t"><tbody>${[['GET', '/api/events?since=0&severity=critical,high', 'Events (filters: module, camera, severity, status, from, to, q)'], ['GET', '/api/alerts', 'Open critical/high alerts'],
          ['GET', '/api/cameras', 'Cameras + live status + link'], ['POST', '/api/events/{id}/action', '{"action":"acknowledge|escalate|false_alarm|resolve","note":""}'],
          ['GET', '/api/integrity', 'Verify the evidence hash chain'], ['GET', '/api/export?fmt=csv|json|pdf', 'Bulk export'], ['GET', '/video/{cam}', 'MJPEG stream (annotated)'],
          ['GET', '/api/vehicles?q=PB10', 'Vehicle registry search']].map(([m, p, d]) => `<tr><td><span class="chip ${m === 'POST' ? 'act' : ''}">${m}</span></td><td class="mono" style="font-size:11.5px">${esc(p)}</td><td class="note">${esc(d)}</td></tr>`).join('')}</tbody></table>
        <div class="code">curl http://${esc(host)}/api/alerts</div></div></div>
      <div class="panel"><div class="ph"><h3>Live alert stream (WebSocket)</h3><span class="sp"></span><button class="btn sm" id="wsT">Connect test console</button></div><div class="pb stack" style="gap:8px">
        <div class="code">ws://${esc(host)}/ws/alerts?min=high   // one JSON event per message</div><div class="code" id="wsLog" style="height:210px">not connected</div></div></div>
      <div class="panel"><div class="ph"><h3>Outgoing webhook</h3></div><div class="pb stack" style="gap:8px">
        <label class="f">POST critical/high alerts as JSON to<input class="in" id="wh" placeholder="https://c2.example/api/pehredar" value="${esc(S.settings?.integrations?.webhook_url || '')}"></label>
        <div class="row"><button class="btn pri" id="whSave">Save</button><button class="btn" id="whTest">Send test</button><span class="note" id="whNote"></span></div></div></div>
      <div class="panel"><div class="ph"><h3>Onboard a camera (RTSP / ONVIF)</h3></div><div class="pb stack" style="gap:8px">
        <div class="grid2"><label class="f">Name<input class="in" id="oName" placeholder="BOP Kilo gate"></label><label class="f">Location<input class="in" id="oLoc" placeholder="BOP Kilo"></label>
          <label class="f">Latitude<input class="in" id="oLat" value="31.6100"></label><label class="f">Longitude<input class="in" id="oLon" value="74.5500"></label>
          <label class="f">Link<select class="in" id="oLink"><option>Fibre</option><option>4G</option><option>VSAT</option><option>Radio</option></select></label>
          <label class="f">Protocol<select class="in" id="oProto"><option>RTSP</option><option>ONVIF (Profile S — paste its RTSP URI)</option><option>HTTP MJPEG</option></select></label></div>
        <label class="f">Stream URL<input class="in" id="oUrl" placeholder="rtsp://user:pass@10.0.0.21:554/stream1"></label>
        <div class="row"><button class="btn pri" id="oAdd">Onboard camera</button><span class="note" id="oNote">Runs the full live pipeline (YOLOv8n + ByteTrack + all modules) on the new stream.</span></div></div></div>
    </div>
    <div class="panel" style="margin-top:14px"><div class="ph"><h3>Sample event payload (latest event)</h3></div><div class="pb"><div class="code" id="sample">…</div></div></div>`;
  api('/api/integrations/sample').then(s => { $('#sample').textContent = JSON.stringify(s, null, 2); });
  let ws = null;
  $('#wsT').onclick = () => {
    if (ws) { ws.close(); ws = null; $('#wsT').textContent = 'Connect test console'; return; }
    ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${host}/ws/alerts?min=medium`);
    $('#wsLog').textContent = 'connected · waiting for medium+ alerts…\n';
    ws.onmessage = m => { const e = JSON.parse(m.data); $('#wsLog').textContent = `${e.ts_iso} ${e.severity.toUpperCase()} ${e.event_id} ${e.event_name} @ ${e.camera_id}\n` + $('#wsLog').textContent.slice(0, 4000); };
    $('#wsT').textContent = 'Disconnect';
  };
  S.pageOff.push(() => ws && ws.close());
  $('#whSave').onclick = () => settingsPatch({integrations: {webhook_url: $('#wh').value.trim()}}).then(() => { $('#whNote').textContent = 'Saved'; });
  $('#whTest').onclick = async () => { try { const r = await post('/api/webhook/test'); $('#whNote').textContent = `Test delivered · HTTP ${r.status}`; } catch (e) { $('#whNote').textContent = e.message; } };
  $('#oAdd').onclick = async () => {
    try {
      const r = await post('/api/cameras', {name: $('#oName').value, location: $('#oLoc').value, lat: $('#oLat').value, lon: $('#oLon').value, link: $('#oLink').value, protocol: $('#oProto').value, rtsp: $('#oUrl').value});
      $('#oNote').textContent = `Onboarded ${r.camera.id} · status: ${r.camera.stats.status}`;
      await refreshCams(); if (WS && WS.readyState === 1) WS.send(JSON.stringify({cameras_refresh: true}));
    } catch (e) { $('#oNote').textContent = e.message; }
  };
};

// =================================================================== settings
ROUTES.settings = (main) => {
  const s = S.settings;
  const sec = (key, title, fields) => `<div class="panel"><div class="ph"><h3>${title}</h3></div><div class="pb grid2">${fields.map(([k, l, type = 'number']) => {
    const v = s[key][k];
    if (type === 'bool') return `<label class="switch"><input type="checkbox" data-s="${key}.${k}" ${v ? 'checked' : ''}><i></i>${l}</label>`;
    if (Array.isArray(type)) return `<label class="f">${l}<select class="in" data-s="${key}.${k}">${type.map(o => `<option ${o === v ? 'selected' : ''}>${o}</option>`).join('')}</select></label>`;
    return `<label class="f">${l}<input class="in" type="${type}" step="any" data-s="${key}.${k}" value="${esc(v)}"></label>`;
  }).join('')}</div></div>`;
  main.innerHTML = pageH('Settings', 'Thresholds apply to every camera immediately · saved to data/settings.json', '<button class="btn pri" id="save">Save all</button>') + `
    <div class="grid2">
      <div class="panel"><div class="ph"><h3>Operator profile</h3></div><div class="pb grid2">
        <label class="f">Name<input class="in" data-s="operator.name" type="text" value="${esc(s.operator.name)}"></label>
        <label class="f">Role<input class="in" data-s="operator.role" type="text" value="${esc(s.operator.role)}"></label>
        <label class="f">Operator ID<input class="in" data-s="operator.id" type="text" value="${esc(s.operator.id)}"></label>
        <label class="switch"><input type="checkbox" data-s="sound" ${s.sound ? 'checked' : ''}><i></i>Alert sounds</label></div></div>
      ${sec('alerts', 'Alerts', [['cooldown_s', 'Cooldown per track + alert type (s)'], ['banner', 'Full-screen banner for critical alerts', 'bool']])}
      ${sec('human', 'Human tracking', [['conf', 'Detection confidence'], ['crowd_threshold', 'Crowd threshold (people)'], ['imgsz', 'Inference size (px)']])}
      ${sec('vehicle', 'Vehicles', [['conf', 'Detection confidence'], ['stopped_seconds', 'Stopped too long after (s)'], ['m_per_px', 'Speed calibration (metres per pixel)']])}
      ${sec('face', 'Faces', [['match_threshold', 'Match threshold (cosine)'], ['min_face_px', 'Min face size (px)'], ['privacy_blur', 'Blur non-watchlist faces in exports', 'bool']])}
      ${sec('anpr', 'ANPR', [['ocr_min_conf', 'OCR confidence floor'], ['plate_cooldown_s', 'Same-plate re-log cooldown (s)'], ['min_crop_px', 'Min vehicle crop (px)']])}
      ${sec('activity', 'Suspicious activity', [['loiter_seconds', 'Loiter (s)'], ['run_speed_bh_s', 'Running (body-heights/s)'], ['group_size', 'Group size'], ['group_radius_bh', 'Group radius (bh)'], ['group_seconds', 'Group duration (s)'], ['crawl_aspect', 'Crawl aspect'], ['repeat_passes', 'Repeated passes'], ['abandon_seconds', 'Abandoned object (s)']])}
      ${sec('night', 'Day / night', [['mode', 'Mode', ['auto', 'day', 'night']], ['enter_below', 'Night below brightness'], ['exit_above', 'Day above brightness'], ['clahe_clip', 'CLAHE clip'], ['gamma', 'Gamma']])}
      ${sec('network', 'Network', [['adaptive', 'Adaptive streaming', 'bool']])}
      <div class="panel"><div class="ph"><h3>Zones</h3></div><div class="pb stack" style="gap:8px"><div class="note">Draw / edit zones per camera from the Virtual Fence module or any camera's expanded view.</div>
        <div class="row"><a class="btn" href="#/module/fence">Open zone editor</a><button class="btn red" id="zr">Reset all zones to defaults</button></div></div></div>
    </div>
    <div class="panel" style="margin-top:14px"><div class="ph"><h3>System info</h3><span class="sp"></span><span class="note">answer judges accurately: every module's model + data source</span></div><div class="pb" id="sys"></div></div>`;
  $('#save').onclick = async () => {
    const patch = {};
    $$('[data-s]').forEach(i => {
      const path = i.dataset.s.split('.');
      const v = i.type === 'checkbox' ? i.checked : i.type === 'number' ? +i.value : i.value;
      if (path.length === 1) patch[path[0]] = v; else (patch[path[0]] ||= {})[path[1]] = v;
    });
    await settingsPatch(patch);
    S.operator = S.settings.operator; S.sound = S.settings.sound; renderOperator(); renderSound();
    toastMsg('Settings saved', 'Applied to all cameras', 'info');
  };
  $('#zr').onclick = async () => { await post('/api/zones/reset'); toastMsg('Zones reset', 'Defaults restored', 'info'); };
  api('/api/system').then(si => {
    $('#sys').innerHTML = `<div class="grid2"><dl class="kv"><dt>Version</dt><dd>Pehredar.ai ${esc(si.version)}</dd><dt>Device</dt><dd>${esc(si.device)}</dd>
      <dt>Python</dt><dd>${esc(si.python)}</dd><dt>PyTorch</dt><dd>${esc(si.torch)}</dd><dt>OpenCV</dt><dd>${esc(si.opencv)}</dd><dt>Ultralytics</dt><dd>${esc(si.ultralytics)}</dd>
      <dt>Platform</dt><dd>${esc(si.platform)}</dd><dt>Uptime</dt><dd>${Math.round(si.uptime_s / 60)} min</dd></dl>
      <table class="t"><thead><tr><th>Module</th><th>Model</th><th>Runs on</th></tr></thead><tbody>${si.models.map(m => `<tr><td>${esc(m.module)}</td><td class="note">${esc(m.model)}</td><td class="mono">${esc(m.device)}</td></tr>`).join('')}</tbody></table></div>
      <h4 style="margin:16px 0 8px">Data source per module</h4><table class="t"><tbody>${Object.entries(si.data_sources).map(([k, v]) => `<tr><td style="width:190px"><b>${esc(k)}</b></td><td>${esc(v)}</td></tr>`).join('')}</tbody></table>
      <h4 style="margin:16px 0 8px">Data source per camera</h4><table class="t"><tbody>${si.sources.map(c => `<tr><td class="mono" style="width:80px">${esc(c.camera)}</td><td>${esc(c.name)}</td><td>${esc(c.kind)}</td><td class="note">${esc(c.source)}</td></tr>`).join('')}</tbody></table>`;
  });
};

// =================================================================== about
ROUTES.about = (main) => {
  main.innerHTML = pageH('About Pehredar.ai', 'IBVAP — Intelligent Border Video Analytics Platform') + `
    <div class="grid2">
      <div class="panel"><div class="ph"><h3>The problem</h3></div><div class="pb stack" style="gap:10px;font-size:13.5px;line-height:1.6">
        <p style="margin:0">Border security forces run ordinary IP CCTV cameras at Border Out Posts (BOPs), check posts, border roads and strategic locations. Conventional CCTV only records and streams live video, so people must watch every screen continuously.</p>
        <p style="margin:0">Advanced features — Facial Recognition (FRS), Automatic Number Plate Recognition (ANPR), intrusion detection, object tracking — usually need expensive specialised or proprietary hardware, which makes large-scale deployment at remote border posts costly and hard.</p></div></div>
      <div class="panel"><div class="ph"><h3>How Pehredar.ai solves it</h3></div><div class="pb stack" style="gap:10px;font-size:13.5px;line-height:1.6">
        <p style="margin:0"><b class="hl">Software-only.</b> It ingests the streams the existing IP cameras already produce (RTSP/ONVIF) and runs AI analytics on an edge computer at the post — no smart cameras, no FRS/ANPR hardware.</p>
        <div class="row">${['Human detection & tracking', 'Vehicle detection & classification', 'Face detection', 'ANPR', 'Virtual fence intrusion', 'Suspicious activity', 'Night-time movement', 'Real-time alerts & tamper-evident logging'].map((x, i) => `<span class="chip on">${i + 1} ${x}</span>`).join('')}</div>
        <p style="margin:0">Real-time alerts, face / vehicle / behaviour analytics in software, a SHA-256 evidence chain, REST + WebSocket + webhook integration with existing C2 systems, and adaptive streaming for 4G / VSAT / radio links at remote posts.</p></div></div>
    </div>
    <div class="panel" style="margin-top:14px"><div class="ph"><h3>Architecture</h3></div><div class="pb">
      <svg viewBox="0 0 1100 250" style="width:100%" font-family="Inter" font-size="12">
        <defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#FF9933"/></marker></defs>
        ${[['Existing IP CCTV', 'RTSP / ONVIF · Fibre, 4G, VSAT, radio', 20], ['Edge node at BOP', 'YOLOv8 + ByteTrack · faces · ANPR · zones · rules · night', 300], ['Evidence & alerts', 'SHA-256 chain · snapshots · edge buffer', 580], ['Command centre', 'Dashboard · C2 REST / WebSocket / webhook', 860]].map(([t, s, x], i) => `
          <rect x="${x}" y="70" width="220" height="100" rx="12" fill="#16213A" stroke="${['#8A98B3', '#FF9933', '#FFFFFF', '#138808'][i]}" stroke-width="2"/>
          <text x="${x + 110}" y="112" text-anchor="middle" fill="#fff" font-family="Rajdhani" font-size="19" font-weight="700">${t}</text>
          <text x="${x + 110}" y="138" text-anchor="middle" fill="#8A98B3" font-size="11">${s}</text>${i < 3 ? `<line x1="${x + 222}" y1="120" x2="${x + 296}" y2="120" stroke="#FF9933" stroke-width="3" marker-end="url(#ar)"/>` : ''}`).join('')}
        <text x="550" y="215" text-anchor="middle" fill="#8A98B3">Scales out by adding one edge node per BOP; the command centre aggregates events from every sector.</text></svg></div></div>
    <div class="grid2" style="margin-top:14px">
      <div class="panel"><div class="ph"><h3>Cost comparison per post (illustrative)</h3></div><div class="pb stack" style="gap:8px">
        <table class="t"><thead><tr><th></th><th>Dedicated smart-camera stack</th><th>Existing CCTV + Pehredar.ai</th></tr></thead><tbody>
          <tr><td>Cameras</td><td>Replace with FRS / ANPR smart cameras</td><td>Keep existing IP cameras</td></tr>
          <tr><td>Compute</td><td>Proprietary appliances per feature</td><td>One edge PC (GPU optional)</td></tr>
          <tr><td>New analytics</td><td>New hardware / vendor licence</td><td>Software update</td></tr>
          <tr><td>Remote links</td><td>Full video backhaul</td><td>Adaptive · metadata-only when weak</td></tr></tbody></table>
        <div class="warnbox">No rupee figures are shown on purpose: they depend on vendor quotes and scale. Get the per-post hardware and licence quotes before presenting cost numbers.</div></div></div>
      <div class="panel"><div class="ph"><h3>What is real vs simulated in this build</h3></div><div class="pb" id="rv"></div></div>
    </div>
    <div class="panel" style="margin-top:14px"><div class="ph"><h3>Credits</h3></div><div class="pb note">Sample footage: Intel IoT DevKit sample-videos (CC-BY 4.0). Face models: OpenCV Zoo YuNet / SFace. Detection: Ultralytics YOLOv8 (AGPL-3.0). ANPR body-type model: anpr_best.pt from the team's Anpr_system project. Offline plate OCR: open-image-models + fast-plate-ocr. Fonts: Rajdhani, Inter, JetBrains Mono (SIL OFL). Original motifs only — no state emblem, force crest or government logos.</div></div>`;
  api('/api/system').then(si => { $('#rv').innerHTML = `<table class="t"><tbody>${Object.entries(si.data_sources).map(([k, v]) => `<tr><td style="width:150px"><b>${esc(k)}</b></td><td class="note">${esc(v)}</td></tr>`).join('')}</tbody></table>`; });
};
