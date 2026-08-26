const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();

const qs = new URLSearchParams(location.search);
const startParam = tg?.initDataUnsafe?.start_param || '';
const roomFromStart = startParam.match(/^room[_-]([A-Za-z0-9]+)$/i)?.[1] || '';
const code = (qs.get('room') || roomFromStart || '').toUpperCase();
const groupId = qs.get('group_id');
const init = tg?.initData || '';
const app = document.querySelector('#app');
let syncTimer = null;

async function api(url, options = {}) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Request gagal');
  return data;
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
}

function fmtBytes(n) {
  if (!n) return '0 B';
  const u = ['B','KB','MB','GB'];
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), 3);
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`;
}

async function dashboard() {
  try {
    const d = await api(`/api/dashboard/${encodeURIComponent(groupId)}?init_data=${encodeURIComponent(init)}`);
    app.innerHTML = `<h1>🎬 NOBAR</h1><p class="muted">Room aktif di GC</p>` +
      (d.rooms.length ? d.rooms.map(r => `<section class="card"><b>${esc(r.title)}</b><p class="muted"><code>${esc(r.code)}</code> · 👥 ${r.members} · ${r.has_film?'🎞️ Film siap':'📭 Belum ada film'} · ${r.playing?'▶️ Playing':'⏸️ Paused'}</p><button onclick="location.href='/miniapp?room=${encodeURIComponent(r.code)}'">Buka Room</button></section>`).join('') : `<section class="card">Belum ada room aktif.</section>`);
  } catch (e) {
    app.innerHTML = `<section class="card"><h2>⚠️ Dashboard gagal</h2><p class="muted">${esc(e.message)}</p></section>`;
  }
}

async function room() {
  try {
    const d = await api(`/api/rooms/${encodeURIComponent(code)}?init_data=${encodeURIComponent(init)}`);
    renderRoom(d);
  } catch (e) {
    app.innerHTML = `<section class="card"><h2>⚠️ Room gagal dimuat</h2><p class="muted">${esc(e.message)}</p></section>`;
  }
}

function renderRoom(d) {
  const r = d.room;
  const film = d.film;
  app.innerHTML = `<header><h1>🎬 ${esc(r.title)}</h1><p class="muted">Room <code>${esc(r.code)}</code> · 👥 ${d.members} · ${r.is_host?'👑 Host':''}</p></header>
    <section class="card">${film ? `<div class="film-title">🎞️ ${esc(film.title)} <small>(${fmtBytes(film.size)})</small></div><video id="video" controls playsinline preload="metadata" src="${esc(film.url)}"></video>` : '<p class="muted">Host belum memilih film untuk room ini.</p>'}
    ${r.is_host && film ? `<div class="row" style="margin-top:12px"><button id="toggle">${r.playing?'⏸️ Pause':'▶️ Play'}</button><button class="secondary" id="seek">↗️ Sync posisi</button></div><div id="hoststatus" class="status">Kamu mengontrol pemutaran untuk semua peserta.</div>` : `<div id="watchstatus" class="status">Sinkronisasi otomatis aktif.</div>`}</section>`;

  const v = document.querySelector('#video');
  if (!v) return;
  v.currentTime = Number(r.position || 0);
  if (r.is_host) {
    document.querySelector('#toggle').onclick = async () => {
      const playing = v.paused;
      await sync(r.code, playing, v.currentTime);
      if (playing) await v.play().catch(()=>{}); else v.pause();
    };
    document.querySelector('#seek').onclick = async () => sync(r.code, !v.paused, v.currentTime);
    v.addEventListener('play', () => sync(r.code, true, v.currentTime).catch(()=>{}));
    v.addEventListener('pause', () => sync(r.code, false, v.currentTime).catch(()=>{}));
    v.addEventListener('seeked', () => sync(r.code, !v.paused, v.currentTime).catch(()=>{}));
  } else {
    if (syncTimer) clearInterval(syncTimer);
    syncTimer = setInterval(async () => {
      try {
        const x = await api(`/api/rooms/${encodeURIComponent(code)}?init_data=${encodeURIComponent(init)}`);
        if (Math.abs(v.currentTime - x.room.position) > 1.5) v.currentTime = x.room.position;
        if (x.room.playing && v.paused) await v.play().catch(()=>{});
        if (!x.room.playing && !v.paused) v.pause();
      } catch {}
    }, 1500);
  }
}

async function sync(roomCode, playing, position) {
  await api(`/api/sync/${encodeURIComponent(roomCode)}`, {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({init_data:init,playing,position})});
}

if (groupId) dashboard();
else if (code) room();
else app.innerHTML = '<section class="card"><h1>🎬 NOBAR</h1><p class="muted">Buka NOBAR dari tombol undangan di Telegram.</p></section>';
