const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();

const qs = new URLSearchParams(location.search);
const code = (qs.get('room') || '').toUpperCase();
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
  app.innerHTML = `<h1>🎬 ${esc(r.title)}</h1><p class="muted">Room <code>${esc(r.code)}</code> · 👥 ${d.members} · ${r.playing?'▶️ Playing':'⏸️ Paused'}</p>
    <section class="card">${film ? `<div class="film-title">🎞️ ${esc(film.title)} <small>(${fmtBytes(film.size)})</small></div><video id="video" controls playsinline preload="metadata" src="${esc(film.url)}"></video>` : '<p class="muted">Belum ada film. Host bisa upload lewat tombol Upload.</p>'}
    ${r.is_host ? `<div class="row" style="margin-top:12px"><button id="toggle">${r.playing?'⏸️ Pause':'▶️ Play'}</button><button class="secondary" id="seek">↗️ Sync posisi</button></div><div id="hoststatus" class="status"></div>` : `<div id="watchstatus" class="status">Sinkronisasi otomatis aktif.</div>`}</section>
    ${r.is_host ? `<section class="card" id="uploadCard"><h3>Upload film</h3><p class="muted">Maks. 5 GiB · upload multipart langsung ke Backblaze B2.</p><input id="file" type="file" accept="video/*"><input id="title" type="text" placeholder="Judul film"><button id="uploadBtn">Upload ke B2</button><div class="progress"><i id="bar"></i></div><div id="upstatus" class="status"></div></section>` : ''}`;

  const v = document.querySelector('#video');
  if (v) {
    v.currentTime = Number(r.position || 0);
    if (r.is_host) {
      document.querySelector('#toggle').onclick = async () => { const playing = v.paused; await sync(r.code, playing, v.currentTime); };
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

  const file = document.querySelector('#file');
  const title = document.querySelector('#title');
  const btn = document.querySelector('#uploadBtn');
  if (btn) btn.onclick = () => startUpload(file.files[0], title.value.trim() || file.files[0]?.name || 'Film');
}

async function sync(roomCode, playing, position) {
  await api(`/api/sync/${encodeURIComponent(roomCode)}`, {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({init_data:init,playing,position})});
}

async function startUpload(file, title) {
  const status = document.querySelector('#upstatus');
  const bar = document.querySelector('#bar');
  const btn = document.querySelector('#uploadBtn');
  if (!file) return status.textContent = 'Pilih file video dulu.';
  if (file.size > 5 * 1024**3) return status.textContent = 'File lebih besar dari 5 GiB.';
  if (!file.type.startsWith('video/')) return status.textContent = 'File harus berupa video.';
  btn.disabled = true;
  status.textContent = 'Menyiapkan multipart upload…';
  let started;
  try {
    started = await api(`/api/upload/start/${encodeURIComponent(code)}`, {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({init_data:init,title,size:file.size,mime:file.type||'video/mp4'})});
    const completed = [];
    const concurrency = 4;
    let next = 0;
    async function worker() {
      while (true) {
        const idx = next++;
        if (idx >= started.parts.length) return;
        const p = started.parts[idx];
        const start = (p.part_number - 1) * started.part_size;
        const end = Math.min(start + started.part_size, file.size);
        const blob = file.slice(start, end);
        let ok = false;
        for (let attempt = 1; attempt <= 3 && !ok; attempt++) {
          try {
            const res = await fetch(p.url, {method:'PUT',body:blob});
            if (!res.ok) throw new Error(`B2 HTTP ${res.status}`);
            const etag = res.headers.get('ETag');
            if (!etag) throw new Error('ETag B2 tidak terbaca. Cek CORS ExposeHeaders=ETag.');
            completed.push({part_number:p.part_number,etag});
            ok = true;
            const pct = Math.round(completed.length / started.parts.length * 100);
            bar.style.width = pct + '%';
            status.textContent = `Upload ${pct}% · part ${completed.length}/${started.parts.length}`;
          } catch (e) {
            if (attempt === 3) throw e;
            await new Promise(r => setTimeout(r, 1000 * attempt));
          }
        }
      }
    }
    await Promise.all(Array.from({length: concurrency}, worker));
    status.textContent = 'Menggabungkan part di B2…';
    await api(`/api/upload/complete/${encodeURIComponent(code)}`, {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({init_data:init,upload_id:started.upload_id,parts:completed})});
    status.textContent = '✅ Film berhasil disimpan di B2.';
    await room();
  } catch (e) {
    status.textContent = `❌ ${e.message}`;
    if (started) {
      try { await api(`/api/upload/abort/${encodeURIComponent(code)}`, {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({init_data:init,upload_id:started.upload_id})}); } catch {}
    }
  } finally {
    btn.disabled = false;
  }
}

if (groupId) dashboard();
else if (code) room();
else app.innerHTML = '<section class="card"><h1>🎬 NOBAR</h1><p class="muted">Buka Mini App dari Telegram.</p></section>';
