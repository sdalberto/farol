/* ==========================================================================
   Farol — interface (JavaScript puro, sem frameworks, sem internet)

   Organização do arquivo:
     1. Utilidades (atalhos de DOM, formatação, ícones, chamadas à API)
     2. Idiomas (i18n)
     3. Aparência (tema, fundo, cores)
     4. Login e inicialização
     5. Rotas (#/, #/busca, #/pasta, #/rede, #/dev)
     6. Home, busca e resultados
     7. Navegação de pastas
     8. Visualizador (vídeo, áudio, imagem, PDF, documentos, editor de código)
     9. Player de música
    10. Assistente de IA
    11. Rede (sessões + dispositivos)
    12. Modo Dev (terminal / SSH)
    13. Configurações
    14. Atalhos de teclado
   ========================================================================== */
'use strict';

/* ---------------------------------------------------------------- 1. Utils */
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

// Estado global da interface.
const S = {
  dict: {}, lang: 'pt-BR', settings: null, favorites: [], recent: [], stats: null, dev: null,
  q: '', kind: 'all', offset: 0, total: 0,
  queue: [], qi: -1,           // fila de músicas
  viewerItem: null, editorDirty: false,
  term: null, ws: null, fit: null,
};

/** Escapa HTML — TODO texto vindo de arquivos/usuário passa por aqui. */
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function fmtSize(b) {
  if (b == null) return '';
  const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return `${b.toFixed(i ? 1 : 0)} ${u[i]}`;
}
function fmtDate(ts) {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleDateString(S.lang, { day: '2-digit', month: 'short', year: 'numeric' });
}
function fmtTime(sec) {
  if (!isFinite(sec)) return '0:00';
  const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}
function ago(ts) {
  const d = Date.now() / 1000 - ts;
  if (d < 60) return t('time.now');
  if (d < 3600) return t('time.min', { n: Math.floor(d / 60) });
  if (d < 86400) return t('time.hour', { n: Math.floor(d / 3600) });
  return fmtDate(ts);
}
function toast(msg) {
  const el = $('#toast');
  el.textContent = msg; el.classList.add('show');
  clearTimeout(toast._t); toast._t = setTimeout(() => el.classList.remove('show'), 2600);
}

/* Ícones SVG desenhados à mão (traço), para não depender de fontes de ícones. */
const ICONS = {
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z"/>',
  star: '<path d="M12 3l2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3 6.4 20.2l1.1-6.2L3 9.6l6.2-.9z"/>',
  folder: '<path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>',
  file: '<path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8z"/><path d="M14 3v5h5"/>',
  doc: '<path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
  video: '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3z"/>',
  audio: '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>',
  code: '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16"/>',
  sheet: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M4 9h16M4 15h16M10 3v18"/>',
  slide: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M12 16v4M8 20h8"/>',
  archive: '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10a2 2 0 002 2h10a2 2 0 002-2V9M10 13h4"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 018 0v4"/>',
  play: '<path d="M7 4l13 8-13 8z"/>', pause: '<path d="M7 4h4v16H7zM13 4h4v16h-4z"/>',
  next: '<path d="M5 4l10 8-10 8zM18 4v16"/>', prev: '<path d="M19 4L9 12l10 8zM6 4v16"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
  save: '<path d="M5 3h11l3 3v15H5z"/><path d="M8 3v5h8V3M8 21v-7h8v7"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18"/>',
  wifi: '<path d="M2 9a15 15 0 0120 0M5 12.5a10 10 0 0114 0M8.5 16a5 5 0 017 0"/><circle cx="12" cy="19.5" r="1"/>',
  terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M13 15h4"/>',
  palette: '<path d="M12 3a9 9 0 100 18c1 0 1.5-.8 1.5-1.6 0-.9-.6-1.4-.6-2.2 0-.9.7-1.6 1.6-1.6H17a4 4 0 004-4c0-4.8-4-8.6-9-8.6z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10" cy="7" r="1"/><circle cx="15" cy="7.5" r="1"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
  db: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  sliders: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5"/>',
  up: '<path d="M12 19V5M5 12l7-7 7 7"/>',
};
function icon(name, cls = '') {
  return `<svg class="ic ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ICONS.file}</svg>`;
}
const KIND_ICON = { video: 'video', audio: 'audio', image: 'image', code: 'code', pdf: 'doc', doc: 'doc', text: 'doc', sheet: 'sheet', slide: 'slide', archive: 'archive', folder: 'folder', other: 'file' };
const kindIcon = k => icon(KIND_ICON[k] || 'file');

/** Chamada à API. Envia o cabeçalho X-Farol (proteção CSRF exigida pelo servidor). */
async function api(path, opts = {}) {
  const o = { method: opts.method || 'GET', headers: { 'X-Farol': '1' }, credentials: 'same-origin' };
  if (opts.body !== undefined) {
    if (opts.raw) { o.body = opts.body; o.headers['Content-Type'] = opts.type; }
    else { o.body = JSON.stringify(opts.body); o.headers['Content-Type'] = 'application/json'; }
  }
  const r = await fetch(path, o);
  let data = null;
  try { data = await r.json(); } catch { /* resposta sem JSON */ }
  if (r.status === 401 && !opts.allow401) { showLogin(); throw new Error('auth'); }
  if (!r.ok) {
    const e = new Error((data && data.error) || `http_${r.status}`);
    e.data = data; throw e;
  }
  return data;
}
/** Mostra um erro traduzido (códigos vêm do servidor). */
function showError(e) {
  if (e.message === 'auth') return;
  const key = 'err.' + e.message;
  let msg = S.dict[key] ? t(key) : t('err.generic', { code: e.message });
  if (e.data && e.data.detail) msg += ` — ${e.data.detail}`;
  toast(msg);
}
const fileUrl = (p, dl) => `/api/file?path=${encodeURIComponent(p)}${dl ? '&dl=1' : ''}`;

/* ---------------------------------------------------------------- 2. i18n */
async function loadLang(lang) {
  if (!['pt-BR', 'en', 'es'].includes(lang)) lang = 'pt-BR';
  const r = await fetch(`/static/i18n/${lang}.json`);
  S.dict = await r.json(); S.lang = lang;
  document.documentElement.lang = lang;
  applyI18n();
}
/** t('chave', {n: 3}) -> texto traduzido com {n} substituído. */
function t(key, vars = {}) {
  let s = S.dict[key] ?? key;
  for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, v);
  return s;
}
function applyI18n(root = document) {
  $$('[data-i18n]', root).forEach(el => { el.textContent = t(el.dataset.i18n); });
  $$('[data-i18n-ph]', root).forEach(el => { el.placeholder = t(el.dataset.i18nPh); });
  $$('[data-i18n-title]', root).forEach(el => { el.title = t(el.dataset.i18nTitle); el.setAttribute('aria-label', el.title); });
  $$('[data-icon]', root).forEach(el => { if (!el.firstChild) el.innerHTML = icon(el.dataset.icon); });
}

/* ---------------------------------------------------------- 3. Aparência */
// Fundos prontos: cor base + 3 "orbes" de luz desfocados (animáveis).
const PRESETS = {
  aurora:   ['#070b14', '#2f6bff', '#00c2a8', '#8b3dff'],
  sunset:   ['#140a10', '#ff5e62', '#ff9966', '#b23aee'],
  ocean:    ['#04121c', '#0077b6', '#00b4d8', '#3a0ca3'],
  forest:   ['#06120c', '#2d6a4f', '#95d5b2', '#1b4332'],
  candy:    ['#160a18', '#ff6ec7', '#7873f5', '#4ade80'],
  graphite: ['#0d0f13', '#3a3f4b', '#5b6170', '#22252d'],
  dawn:     ['#f4f1ee', '#ffd6a5', '#bde0fe', '#ffc8dd'],
  mint:     ['#eef7f3', '#b7efc5', '#9ad1d4', '#e0c3fc'],
};

function applyUI(ui) {
  const root = document.documentElement, body = document.body;
  let theme = ui.theme;
  if (theme === 'auto') theme = matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  root.dataset.theme = theme;
  root.dataset.font = ui.font || 'system';
  root.dataset.density = ui.density || 'comfortable';
  root.dataset.tiles = ui.tile_style || 'glass';
  root.style.setProperty('--accent', ui.accent || '#5b8cff');
  root.style.setProperty('--accent-ink', contrastInk(ui.accent || '#5b8cff'));
  root.style.setProperty('--blur', `${ui.blur ?? 14}px`);
  body.classList.toggle('animated', !!ui.animated);

  const bg = $('#bg'), b = ui.background || { type: 'preset', value: 'aurora' };
  bg.className = ''; bg.style.backgroundImage = ''; bg.style.backgroundColor = '';
  if (b.type === 'image') {
    bg.style.backgroundImage = `url("/api/wallpaper/${encodeURIComponent(b.value)}")`;
  } else if (b.type === 'color') {
    bg.style.backgroundColor = b.value;
  } else {
    const p = PRESETS[b.value] || PRESETS.aurora;
    bg.className = 'preset';
    bg.style.backgroundColor = p[0];
    bg.style.setProperty('--c1', p[1]); bg.style.setProperty('--c2', p[2]); bg.style.setProperty('--c3', p[3]);
  }
  const logo = ui.logo_text || 'Farol';
  ['#hero-logo', '#top-logo', '#login-logo'].forEach(s => { const el = $(s); if (el) el.textContent = logo; });
  document.title = logo;
  $('#clock').classList.toggle('hidden', ui.show_clock === false);
}
/** Escolhe texto preto ou branco conforme o brilho da cor de destaque. */
function contrastInk(hex) {
  const n = parseInt(hex.slice(1), 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255;
  return (r * 299 + g * 587 + b * 114) / 1000 > 150 ? '#111' : '#fff';
}

/* ------------------------------------------------- 4. Login e inicialização */
async function boot() {
  let info;
  try { info = await api('/api/session', { allow401: true }); }
  catch { document.body.classList.remove('booting'); return; }
  await loadLang(localStorage.getItem('farol-lang') || info.language);
  applyUI(info.ui);
  document.body.classList.remove('booting');
  if (info.authenticated) await enterApp(); else showLogin();
}

function showLogin() {
  disconnectTerm();
  $('#app').classList.add('hidden');
  $$('.overlay, .drawer').forEach(e => e.classList.add('hidden'));
  $('#player').classList.add('hidden'); $('#pl-audio').pause();
  $('#login').classList.remove('hidden');
  $('#login-lang').value = S.lang;
  setTimeout(() => $('#login-pass').focus(), 50);
}

$('#login-form').addEventListener('submit', async ev => {
  ev.preventDefault();
  const err = $('#login-error'); err.textContent = '';
  try {
    await api('/api/login', { method: 'POST', body: { password: $('#login-pass').value }, allow401: true });
    $('#login-pass').value = '';
    await enterApp();
  } catch (e) {
    err.textContent = e.message === 'locked' ? t('login.locked', { s: e.data.retry }) : t('login.wrong');
  }
});
$('#login-lang').addEventListener('change', e => { localStorage.setItem('farol-lang', e.target.value); loadLang(e.target.value); });

async function enterApp() {
  const data = await api('/api/bootstrap');
  S.settings = data.settings; S.favorites = data.favorites; S.recent = data.recent; S.stats = data.stats; S.dev = data.dev;
  localStorage.removeItem('farol-lang');
  if (S.lang !== S.settings.language) await loadLang(S.settings.language);
  applyUI(S.settings.ui);
  $('#login').classList.add('hidden');
  $('#app').classList.remove('hidden');
  renderActions(); renderChips(); renderTabs();
  route();
}

/** Botões do canto superior (configurações, rede, modo dev, sair). */
function renderActions() {
  const devOn = S.settings.dev.enabled;
  const html = `
    <button class="icon-btn" data-go="network" title="${esc(t('net.title'))}">${icon('wifi')}</button>
    ${devOn ? `<button class="icon-btn" data-go="dev" title="${esc(t('dev.title'))}">${icon('terminal')}</button>` : ''}
    <button class="icon-btn" data-act="ai" title="${esc(t('ai.title'))}">${icon('spark')}</button>
    <button class="icon-btn" data-act="settings" title="${esc(t('settings.title'))}">${icon('gear')}</button>
    <button class="icon-btn" data-act="logout" title="${esc(t('common.logout'))}">${icon('lock')}</button>`;
  $$('[data-actions]').forEach(n => { n.innerHTML = html; });
}

// Delegação de cliques para botões com data-go / data-act / data-close.
document.addEventListener('click', ev => {
  const go = ev.target.closest('[data-go]');
  if (go) {
    ev.preventDefault();
    $('#settings').classList.add('hidden');   // fecha as configurações ao navegar
    location.hash = go.dataset.go === 'home' ? '#/' : `#/${go.dataset.go}`;
    return;
  }
  const act = ev.target.closest('[data-act]');
  if (act) {
    const a = act.dataset.act;
    if (a === 'settings') openSettings();
    else if (a === 'ai') toggleAI(true);
    else if (a === 'logout') api('/api/logout', { method: 'POST' }).finally(showLogin);
    return;
  }
  const cl = ev.target.closest('[data-close]');
  if (cl) closePanel(cl.dataset.close);
});
function closePanel(id) {
  if (id === 'viewer') return closeViewer();
  $('#' + id).classList.add('hidden');
}

/* ----------------------------------------------------------------- 5. Rotas */
// Usamos o "hash" da URL para o botão Voltar do navegador funcionar.
function route() {
  const h = location.hash || '#/';
  const [path, qs] = h.slice(1).split('?');
  const params = new URLSearchParams(qs || '');
  const pages = { home: '#home', search: '#results', browse: '#browse', network: '#network', dev: '#dev' };
  let page = 'home';
  if (path.startsWith('/search')) page = 'search';
  else if (path.startsWith('/browse')) page = 'browse';
  else if (path.startsWith('/network')) page = 'network';
  else if (path.startsWith('/dev')) page = S.settings.dev.enabled ? 'dev' : 'home';
  Object.entries(pages).forEach(([k, sel]) => $(sel).classList.toggle('hidden', k !== page));
  const top = page !== 'home';
  $('#topbar').classList.toggle('hidden', !top);
  document.body.classList.toggle('topbar', top);
  // Obs.: a sessão do terminal continua viva ao trocar de página (volte em #/dev).
  if (page !== 'search') $$('[data-search] input').forEach(i => { i.value = ''; });   // limpa a busca fora dos resultados
  if (page === 'home') renderHome();
  if (page === 'search') {
    S.q = params.get('q') || ''; S.kind = params.get('kind') || 'all';
    $$('[data-search] input').forEach(i => { i.value = S.q; });
    runSearch(true);
  }
  if (page === 'browse') browse(params.get('p') || '');
  if (page === 'network') loadNetwork();
  if (page === 'dev') openDev();
  window.scrollTo(0, 0);
}
window.addEventListener('hashchange', () => { if (!$('#app').classList.contains('hidden')) route(); });
const goSearch = (q, kind = S.kind) => { location.hash = `#/search?q=${encodeURIComponent(q)}&kind=${kind}`; };

/* ---------------------------------------------- 6. Home, busca e resultados */
const KINDS = [['all', 'search'], ['docs', 'doc'], ['image', 'image'], ['video', 'video'], ['audio', 'audio'], ['code', 'code'], ['archive', 'archive']];

function renderChips() {
  $('#home-chips').innerHTML = KINDS.slice(1).map(([k, ic]) =>
    `<button class="chip" data-kind="${k}">${icon(ic)} ${esc(t('kind.' + k))}</button>`).join('');
  $$('#home-chips .chip').forEach(b => b.onclick = () => goSearch($('#home [data-search] input').value, b.dataset.kind));
}
function renderTabs() {
  $('#kind-tabs').innerHTML = KINDS.map(([k, ic]) =>
    `<button class="tab" role="tab" data-kind="${k}">${icon(ic)} ${esc(t('kind.' + k))}</button>`).join('');
  $$('#kind-tabs .tab').forEach(b => b.onclick = () => goSearch(S.q, b.dataset.kind));
}

// Envio das caixas de busca (home e barra superior).
$$('[data-search]').forEach(f => f.addEventListener('submit', ev => {
  ev.preventDefault();
  const q = f.q.value.trim();
  if (q) goSearch(q, f.closest('#home') ? 'all' : S.kind);
}));
// Busca instantânea enquanto digita (só na barra superior, com atraso de 300ms).
$('#topbar input').addEventListener('input', ev => {
  clearTimeout(S._typing);
  S._typing = setTimeout(() => {
    const q = ev.target.value.trim();
    if (q && q !== S.q) history.replaceState(null, '', `#/search?q=${encodeURIComponent(q)}&kind=${S.kind}`), S.q = q, runSearch(true);
  }, 300);
});

async function renderHome() {
  const ui = S.settings.ui;
  $('#greeting').textContent = ui.greeting || greetingByHour();
  tickClock();
  // Atualiza favoritos/recentes/estatísticas.
  try {
    const d = await api('/api/bootstrap');
    S.favorites = d.favorites; S.recent = d.recent; S.stats = d.stats; S.settings = d.settings;
  } catch (e) { return; }
  // Favoritos
  $('#fav-tiles').innerHTML = S.favorites.length ? S.favorites.map(f => `
    <div class="tile glass" role="button" tabindex="0" data-path="${esc(f.path)}" data-kind="${esc(f.kind)}" data-name="${esc(f.label)}">
      <div class="tile-ic k-${esc(f.kind)}">${kindIcon(f.kind)}</div>
      <span class="lbl">${esc(f.label)}</span>
      <button class="icon-btn x" data-unfav="${esc(f.path)}" title="${esc(t('common.remove'))}">${icon('close')}</button>
    </div>`).join('') : `<p class="empty">${esc(t('home.no_favorites'))}</p>`;
  $$('#fav-tiles .tile').forEach(el => el.onclick = ev => {
    if (ev.target.closest('[data-unfav]')) return;
    const it = { path: el.dataset.path, kind: el.dataset.kind, name: el.dataset.name };
    if (it.kind === 'folder') location.hash = `#/browse?p=${encodeURIComponent(it.path)}`; else openFile(it);
  });
  $$('[data-unfav]').forEach(b => b.onclick = async () => {
    S.favorites = await api(`/api/favorites?path=${encodeURIComponent(b.dataset.unfav)}`, { method: 'DELETE' });
    renderHome();
  });
  // Pastas
  const roots = S.settings.roots;
  $('#folder-tiles').innerHTML = roots.map(r => `
    <button class="tile glass" style="--tile:${esc(r.color)}" data-root="${esc(r.path)}">
      <div class="tile-ic">${icon(r.network ? 'globe' : 'folder')}</div>
      <span class="lbl">${esc(r.name)}</span>
      ${r.readonly ? `<span class="badge" title="${esc(t('folders.readonly'))}">${icon('lock')}</span>` : ''}
    </button>`).join('') + `<button class="tile glass add" id="add-folder-tile"><div class="tile-ic">${icon('plus')}</div><span class="lbl">${esc(t('folders.add'))}</span></button>`;
  $$('[data-root]').forEach(b => b.onclick = () => { location.hash = `#/browse?p=${encodeURIComponent(b.dataset.root)}`; });
  $('#add-folder-tile').onclick = () => openSettings('folders');
  // Recentes
  $('#recent-list').innerHTML = S.recent.length ? S.recent.slice(0, 6).map(resultHTML).join('') : `<p class="empty">${esc(t('home.no_recent'))}</p>`;
  bindResults($('#recent-list'), S.recent);
  // Estatísticas
  const st = S.stats;
  $('#home-stats').textContent = t('home.stats', { n: st.total.toLocaleString(S.lang), f: roots.length });
}
function greetingByHour() {
  const h = new Date().getHours();
  return t(h < 12 ? 'greet.morning' : h < 18 ? 'greet.afternoon' : 'greet.evening');
}
function tickClock() {
  $('#clock').textContent = new Date().toLocaleString(S.lang, { weekday: 'long', hour: '2-digit', minute: '2-digit' });
}
setInterval(() => { if (!$('#home').classList.contains('hidden')) tickClock(); }, 15000);

/** Converte o trecho do servidor (\x02...\x03) em HTML seguro com <mark>. */
function snippetHTML(snip) {
  return esc(snip || '').replace(/\x02/g, '<mark>').replace(/\x03/g, '</mark>');
}
function resultHTML(it, i) {
  const thumb = it.kind === 'image'
    ? `<img loading="lazy" src="${fileUrl(it.path)}" alt="">` : kindIcon(it.kind);
  return `
    <button class="result glass" data-i="${i}">
      <div class="r-ic k-${esc(it.kind)}">${thumb}</div>
      <div class="r-main">
        <div class="r-name">${esc(it.name)}</div>
        <div class="r-path" title="${esc(it.path)}">&lrm;${esc(it.path)}&lrm;</div>
        ${it.snip ? `<div class="r-snip">${snippetHTML(it.snip)}</div>` : ''}
      </div>
      <div class="r-side"><span>${fmtSize(it.size)}</span><span>${fmtDate(it.mtime)}</span></div>
    </button>`;
}
function bindResults(container, list) {
  $$('.result', container).forEach(el => el.onclick = () => {
    const it = list[+el.dataset.i];
    if (it.kind === 'audio') queueFrom(list, it); else openFile(it);
  });
}

async function runSearch(reset) {
  if (reset) { S.offset = 0; S.results = []; $('#result-list').innerHTML = ''; }
  $$('#kind-tabs .tab').forEach(b => b.classList.toggle('active', b.dataset.kind === S.kind));
  if (!S.q) { $('#result-meta').textContent = ''; return; }
  try {
    const r = await api(`/api/search?q=${encodeURIComponent(S.q)}&kind=${S.kind}&limit=30&offset=${S.offset}`);
    S.total = r.total;
    S.results = (S.results || []).concat(r.items);
    $('#result-meta').textContent = t('search.meta', { n: r.total.toLocaleString(S.lang), ms: r.ms });
    if (!S.results.length) {
      $('#result-list').innerHTML = `<div class="glass card empty">${esc(t('search.none', { q: S.q }))}${S.settings.ai.enabled ? ` <button class="btn" id="ask-ai-empty">${icon('spark')} ${esc(t('ai.ask_this'))}</button>` : ''}</div>`;
      const b = $('#ask-ai-empty'); if (b) b.onclick = () => { toggleAI(true); askAI(S.q); };
    } else {
      $('#result-list').innerHTML = S.results.map(resultHTML).join('');
      bindResults($('#result-list'), S.results);
    }
    $('#more-btn').classList.toggle('hidden', S.results.length >= S.total);
  } catch (e) { showError(e); }
}
$('#more-btn').onclick = () => { S.offset += 30; runSearch(false); };

/* ---------------------------------------------------- 7. Navegação de pastas */
async function browse(path) {
  try {
    const d = await api(`/api/browse?path=${encodeURIComponent(path)}`);
    // Migalhas (caminho clicável)
    let crumbs = `<button data-p="">${icon('folder')} ${esc(t('home.folders'))}</button>`;
    if (d.root) {
      const rootPath = d.root.path, rel = d.path.slice(rootPath.length).split(/[\\/]/).filter(Boolean);
      let acc = rootPath;
      crumbs += ` › <button data-p="${esc(rootPath)}">${esc(d.root.name)}</button>`;
      rel.forEach(part => { acc += (acc.endsWith('/') || acc.endsWith('\\') ? '' : (acc.includes('\\') ? '\\' : '/')) + part; crumbs += ` › <button data-p="${esc(acc)}">${esc(part)}</button>`; });
      crumbs += ` <button class="icon-btn" id="fav-folder" title="${esc(t('viewer.favorite'))}">${icon('star')}</button>`;
    }
    $('#crumbs').innerHTML = crumbs;
    $$('#crumbs [data-p]').forEach(b => b.onclick = () => { location.hash = `#/browse?p=${encodeURIComponent(b.dataset.p)}`; });
    const fb = $('#fav-folder');
    if (fb) fb.onclick = async () => { await api('/api/favorites', { method: 'POST', body: { path: d.path } }); toast(t('viewer.favorited')); };

    const items = d.items;
    $('#browse-grid').innerHTML = items.length ? items.map((it, i) => {
      const k = it.is_dir ? 'folder' : it.kind;
      const thumb = k === 'image' ? `<img loading="lazy" src="${fileUrl(it.path)}" alt="">` : kindIcon(k);
      const off = it.online === false ? ` <span class="dot off" title="offline"></span>` : '';
      return `<button class="gf glass" data-i="${i}"><div class="thumb k-${k}" ${it.color ? `style="color:${esc(it.color)}"` : ''}>${thumb}</div><div class="nm">${off}${esc(it.name)}</div></button>`;
    }).join('') : `<p class="empty">${esc(t('browse.empty'))}</p>`;
    $$('#browse-grid .gf').forEach(el => el.onclick = () => {
      const it = items[+el.dataset.i];
      if (it.is_dir) location.hash = `#/browse?p=${encodeURIComponent(it.path)}`;
      else if (it.kind === 'audio') queueFrom(items.filter(x => x.kind === 'audio'), it);
      else openFile(it);
    });
  } catch (e) { showError(e); }
}

/* ------------------------------------------------------- 8. Visualizador */
async function openFile(it) {
  S.viewerItem = it; S.editorDirty = false;
  $('#v-name').textContent = it.name;
  $('#v-path').textContent = it.path;
  $('#v-icon').className = `vh-icon k-${it.kind}`;
  $('#v-icon').innerHTML = kindIcon(it.kind);
  const isFav = S.favorites.some(f => f.path === it.path);
  $('#v-actions').innerHTML = `
    ${S.settings.ai.enabled ? `<button class="icon-btn" id="v-ai" title="${esc(t('ai.ask_file'))}">${icon('spark')}</button>` : ''}
    <button class="icon-btn ${isFav ? 'on' : ''}" id="v-fav" title="${esc(t('viewer.favorite'))}">${icon('star')}</button>
    <button class="icon-btn" id="v-folder" title="${esc(t('viewer.open_folder'))}">${icon('folder')}</button>
    <a class="icon-btn" href="${fileUrl(it.path, 1)}" title="${esc(t('viewer.download'))}">${icon('download')}</a>
    <button class="icon-btn" data-close="viewer" title="${esc(t('common.close'))}">${icon('close')}</button>`;
  $('#v-fav').onclick = toggleFavorite;
  $('#v-folder').onclick = () => {
    const sep = it.path.includes('\\') ? '\\' : '/';
    closeViewer(); location.hash = `#/browse?p=${encodeURIComponent(it.path.slice(0, it.path.lastIndexOf(sep)) || sep)}`;
  };
  if ($('#v-ai')) $('#v-ai').onclick = () => { toggleAI(true); $('#ai-input').value = t('ai.summarize'); $('#ai-input').dataset.path = it.path; $('#ai-input').focus(); };

  const body = $('#v-body'); body.innerHTML = '';
  const url = fileUrl(it.path);
  $('#viewer').classList.remove('hidden');
  switch (it.kind) {
    case 'video':
      body.innerHTML = `<video src="${url}" controls autoplay playsinline></video>`; break;
    case 'image': {
      body.innerHTML = `<img src="${url}" alt="${esc(it.name)}">`;
      const img = $('img', body); img.onclick = () => img.classList.toggle('zoom'); break;
    }
    case 'audio':
      body.innerHTML = `<div class="audio-view"><div class="disc">${icon('audio')}</div><strong>${esc(it.name)}</strong><button class="btn primary" id="v-play">${icon('play')} ${esc(t('player.play'))}</button></div>`;
      $('#v-play').onclick = () => { queueFrom([it], it); closeViewer(); }; break;
    case 'pdf':
      body.innerHTML = `<iframe src="${url}" title="PDF"></iframe>`; break;
    default:
      await loadTextPreview(it, body);
  }
}
async function loadTextPreview(it, body) {
  try {
    const p = await api(`/api/preview?path=${encodeURIComponent(it.path)}`);
    if (['code', 'text'].includes(p.kind) && p.ext !== 'rtf') renderEditor(body, it, p);
    else body.innerHTML = `<div class="doc-text">${esc(p.text || t('viewer.no_text'))}</div>`;
  } catch (e) {
    body.innerHTML = `<div class="no-preview">${kindIcon(it.kind)}<p>${esc(t('viewer.no_preview'))}</p><a class="btn" href="${fileUrl(it.path, 1)}">${icon('download')} ${esc(t('viewer.download'))}</a></div>`;
  }
}
async function toggleFavorite() {
  const it = S.viewerItem, isFav = S.favorites.some(f => f.path === it.path);
  S.favorites = isFav
    ? await api(`/api/favorites?path=${encodeURIComponent(it.path)}`, { method: 'DELETE' })
    : await api('/api/favorites', { method: 'POST', body: { path: it.path } });
  $('#v-fav').classList.toggle('on', !isFav);
  toast(t(isFav ? 'viewer.unfavorited' : 'viewer.favorited'));
}
function closeViewer() {
  if (S.editorDirty && !confirm(t('editor.discard'))) return;
  $('#viewer').classList.add('hidden');
  $('#v-body').innerHTML = '';     // para vídeo/áudio ao fechar
  S.viewerItem = null; S.editorDirty = false;
}
$('#viewer').addEventListener('click', ev => { if (ev.target.id === 'viewer') closeViewer(); });

/* Editor de código/texto: textarea + numeração de linhas, Ctrl+S salva. */
function renderEditor(body, it, p) {
  const size = +(localStorage.getItem('farol-ed-size') || 14);
  body.innerHTML = `
    <div class="editor" style="--ed-size:${size}px">
      <div class="editor-bar">
        <span>${esc(p.ext.toUpperCase())} · ${esc(p.encoding)}</span>
        <span id="ed-state"></span>
        <span style="margin-left:auto"></span>
        <button class="btn" id="ed-smaller">A−</button><button class="btn" id="ed-bigger">A+</button>
        <label class="check"><input type="checkbox" id="ed-wrap"> ${esc(t('editor.wrap'))}</label>
        ${p.editable ? `<button class="btn primary" id="ed-save">${icon('save')} ${esc(t('editor.save'))}</button>`
                     : `<span>${icon('lock')} ${esc(t(p.readonly_root ? 'editor.readonly' : 'editor.too_big'))}</span>`}
      </div>
      <div class="editor-area"><div class="gutter" id="ed-gutter"></div><textarea id="ed-text" spellcheck="false" ${p.editable ? '' : 'readonly'}></textarea></div>
    </div>`;
  const ta = $('#ed-text'), gut = $('#ed-gutter'), state = $('#ed-state');
  ta.value = p.text;
  const lines = () => { gut.textContent = Array.from({ length: ta.value.split('\n').length }, (_, i) => i + 1).join('\n'); };
  lines();
  ta.addEventListener('scroll', () => { gut.scrollTop = ta.scrollTop; });
  ta.addEventListener('input', () => { lines(); S.editorDirty = true; state.textContent = '● ' + t('editor.modified'); state.className = 'dirty'; });
  ta.addEventListener('keydown', ev => {
    if (ev.key === 'Tab') {   // Tab insere recuo em vez de sair do campo
      ev.preventDefault();
      const s = ta.selectionStart, e = ta.selectionEnd;
      ta.setRangeText('    ', s, e, 'end'); ta.dispatchEvent(new Event('input'));
    }
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 's') { ev.preventDefault(); save(); }
  });
  $('#ed-wrap').onchange = e => ta.classList.toggle('wrap', e.target.checked);
  const setSize = d => { const n = Math.max(10, Math.min(28, size + d)); localStorage.setItem('farol-ed-size', n); $('.editor').style.setProperty('--ed-size', n + 'px'); };
  $('#ed-smaller').onclick = () => setSize(-1); $('#ed-bigger').onclick = () => setSize(1);
  async function save() {
    if (!p.editable) return;
    try {
      await api('/api/save', { method: 'POST', body: { path: it.path, content: ta.value, encoding: p.encoding } });
      S.editorDirty = false; state.textContent = '✓ ' + t('editor.saved'); state.className = '';
      toast(t('editor.saved'));
    } catch (e) { showError(e); }
  }
  if ($('#ed-save')) $('#ed-save').onclick = save;
}

/* ------------------------------------------------------ 9. Player de música */
const audio = $('#pl-audio');
function queueFrom(list, start) {
  S.queue = list.filter(x => x.kind === 'audio');
  S.qi = Math.max(0, S.queue.findIndex(x => x.path === start.path));
  playIndex(S.qi);
}
function playIndex(i) {
  if (i < 0 || i >= S.queue.length) return;
  S.qi = i;
  const it = S.queue[i];
  audio.src = fileUrl(it.path);
  audio.play().catch(() => toast(t('player.unsupported')));
  $('#pl-title').textContent = it.name;
  $('#player').classList.remove('hidden');
}
$('#pl-play').onclick = () => (audio.paused ? audio.play() : audio.pause());
$('#pl-next').onclick = () => playIndex(S.qi + 1);
$('#pl-prev').onclick = () => (audio.currentTime > 3 ? (audio.currentTime = 0) : playIndex(S.qi - 1));
$('#pl-close').onclick = () => { audio.pause(); $('#player').classList.add('hidden'); };
$('#pl-vol').oninput = e => { audio.volume = e.target.value / 100; };
$('#pl-seek').oninput = e => { if (audio.duration) audio.currentTime = audio.duration * e.target.value / 1000; };
audio.onplay = () => { $('#pl-play').innerHTML = icon('pause'); };
audio.onpause = () => { $('#pl-play').innerHTML = icon('play'); };
audio.onended = () => playIndex(S.qi + 1);
audio.ontimeupdate = () => {
  if (audio.duration) $('#pl-seek').value = audio.currentTime / audio.duration * 1000;
  $('#pl-time').textContent = `${fmtTime(audio.currentTime)} / ${fmtTime(audio.duration)} · ${S.qi + 1}/${S.queue.length}`;
};
audio.volume = .8;

/* ------------------------------------------------------- 10. Assistente IA */
function toggleAI(show) {
  const p = $('#ai-panel');
  p.classList.toggle('hidden', !show);
  if (!show) return;
  if (!S.settings.ai.enabled) {
    $('#ai-msgs').innerHTML = `<div class="msg bot">${esc(t('ai.disabled'))}<div class="srcs"><button id="ai-setup">${esc(t('ai.configure'))}</button></div></div>`;
    $('#ai-setup').onclick = () => openSettings('ai');
  } else if (!$('#ai-msgs').children.length || $('#ai-setup')) {
    $('#ai-msgs').innerHTML = `<div class="msg bot">${esc(t('ai.hello'))}</div>`;
  }
  $('#ai-input').focus();
}
$('#ai-form').addEventListener('submit', ev => { ev.preventDefault(); const q = $('#ai-input').value.trim(); if (q) askAI(q); });
$('#ai-input').addEventListener('keydown', ev => { if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); $('#ai-form').requestSubmit(); } });

async function askAI(question) {
  if (!S.settings.ai.enabled) return toggleAI(true);
  const box = $('#ai-msgs'), input = $('#ai-input');
  const path = input.dataset.path; delete input.dataset.path;
  input.value = '';
  box.insertAdjacentHTML('beforeend', `<div class="msg user">${esc(question)}</div><div class="msg bot typing" id="ai-wait">${esc(t('ai.thinking'))}</div>`);
  box.scrollTop = box.scrollHeight;
  try {
    const r = await api('/api/ai/ask', { method: 'POST', body: { question, path } });
    $('#ai-wait').remove();
    const srcs = r.sources.map((s, i) => `<button data-src="${i}">[${i + 1}] ${esc(s.name)}</button>`).join('');
    box.insertAdjacentHTML('beforeend', `<div class="msg bot">${esc(r.answer)}${srcs ? `<div class="srcs">${srcs}</div>` : ''}</div>`);
    $$('[data-src]', box.lastElementChild).forEach(b => b.onclick = () => openFile(r.sources[+b.dataset.src]));
  } catch (e) {
    $('#ai-wait')?.remove();
    const msg = S.dict['err.' + e.message] ? t('err.' + e.message) : e.message;
    box.insertAdjacentHTML('beforeend', `<div class="msg bot err">${esc(msg)}${e.data?.detail ? '\n' + esc(e.data.detail) : ''}</div>`);
  }
  box.scrollTop = box.scrollHeight;
}

/* --------------------------------------------------------------- 11. Rede */
async function loadNetwork() {
  try {
    const list = await api('/api/network/sessions');
    $('#net-sessions').innerHTML = list.map(s => `
      <div class="tr">
        <span><span class="dot"></span><code>${esc(s.ip)}</code>${s.current ? `<span class="tag">${esc(t('net.you'))}</span>` : ''}</span>
        <span class="muted">${esc(browserName(s.agent))}</span>
        <span class="muted">${esc(t('net.last_seen'))}: ${esc(ago(s.last_seen))}</span>
        ${s.current ? '<span></span>' : `<button class="btn danger" data-kick="${esc(s.id)}">${esc(t('net.kick'))}</button>`}
      </div>`).join('');
    $$('[data-kick]').forEach(b => b.onclick = async () => { await api(`/api/network/sessions/${b.dataset.kick}`, { method: 'DELETE' }); loadNetwork(); });
  } catch (e) { showError(e); }
  $('#net-scan').classList.toggle('hidden', !S.settings.network.scan_enabled);
}
/** Identifica o navegador/sistema de forma simples a partir do User-Agent. */
function browserName(ua = '') {
  const b = /Edg\//.test(ua) ? 'Edge' : /Chrome\//.test(ua) ? 'Chrome' : /Firefox\//.test(ua) ? 'Firefox' : /Safari\//.test(ua) ? 'Safari' : ua.split(' ')[0] || '?';
  const o = /Windows/.test(ua) ? 'Windows' : /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iOS' : /Mac OS/.test(ua) ? 'macOS' : /Linux/.test(ua) ? 'Linux' : '';
  return o ? `${b} · ${o}` : b;
}
$('#net-scan').onclick = async () => {
  const btn = $('#net-scan'); btn.disabled = true; btn.textContent = t('net.scanning');
  try {
    const d = await api('/api/network/scan', { method: 'POST' });
    $('#net-meta').textContent = d.subnet ? t('net.meta', { n: d.devices.length, subnet: d.subnet, ms: d.ms }) : t('net.no_lan');
    $('#net-devices').innerHTML = d.devices.map(x => `
      <div class="tr">
        <span><span class="dot"></span><code>${esc(x.ip)}</code>${x.self ? `<span class="tag">${esc(t('net.this_pc'))}</span>` : ''}${x.gateway ? `<span class="tag">${esc(t('net.router'))}</span>` : ''}</span>
        <code class="muted">${esc(x.mac || '—')}</code>
        <span>${esc(x.name || t('net.unknown'))}</span><span></span>
      </div>`).join('');
  } catch (e) { showError(e); }
  btn.disabled = false; btn.textContent = t('net.scan');
};

/* ------------------------------------------------------------ 12. Modo Dev */
function openDev() {
  const sel = $('#dev-target');
  sel.innerHTML = `<option value="">${esc(t('dev.local'))}</option>` +
    S.settings.dev.ssh_hosts.map(h => `<option value="${esc(h.id)}">SSH · ${esc(h.name)}</option>`).join('');
  renderSSHList();
  if (!S.term && window.Terminal) {
    S.term = new window.Terminal({ cursorBlink: true, fontFamily: 'ui-monospace, Menlo, Consolas, monospace', fontSize: 14, theme: { background: '#0d1017' } });
    S.fit = new window.FitAddon.FitAddon();
    S.term.loadAddon(S.fit);
    S.term.open($('#term'));
    S.term.onData(d => { if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify({ t: 'i', d })); });
    S.term.writeln(t('dev.welcome'));
    window.addEventListener('resize', fitTerm);
  }
  setTimeout(fitTerm, 50);
}
function fitTerm() {
  if (!S.term || $('#dev').classList.contains('hidden')) return;
  S.fit.fit();
  if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify({ t: 'r', c: S.term.cols, r: S.term.rows }));
}
$('#dev-connect').onclick = () => {
  disconnectTerm();
  if (!S.term) return toast(t('err.generic', { code: 'xterm' }));
  S.term.clear();
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const host = $('#dev-target').value;
  S.ws = new WebSocket(`${proto}://${location.host}/api/dev/term?host=${encodeURIComponent(host)}&cols=${S.term.cols}&rows=${S.term.rows}`);
  S.ws.onmessage = e => S.term.write(e.data);
  S.ws.onclose = e => { if (e.code === 4403) S.term.writeln('\r\n' + t('err.dev_disabled')); };
  S.ws.onopen = () => S.term.focus();
};
$('#dev-disconnect').onclick = disconnectTerm;
function disconnectTerm() { if (S.ws) { S.ws.close(); S.ws = null; } }

function renderSSHList() {
  const hosts = S.settings.dev.ssh_hosts;
  $('#ssh-list').innerHTML = hosts.length ? hosts.map(h => `
    <div class="tr"><strong>${esc(h.name)}</strong><code>${esc(h.user ? h.user + '@' : '')}${esc(h.host)}:${esc(h.port)}</code>
    <span class="muted">${esc(h.key_path || '')}</span><button class="btn danger" data-delhost="${esc(h.id)}">${icon('trash')}</button></div>`).join('')
    : `<p class="empty">${esc(t('dev.no_hosts'))}</p>`;
  $$('[data-delhost]').forEach(b => b.onclick = async () => {
    S.settings = await api(`/api/dev/hosts/${b.dataset.delhost}`, { method: 'DELETE' }); openDev();
  });
}
$('#ssh-form').addEventListener('submit', async ev => {
  ev.preventDefault();
  const f = ev.target, body = Object.fromEntries(new FormData(f));
  try { S.settings = await api('/api/dev/hosts', { method: 'POST', body }); f.reset(); f.port.value = 22; openDev(); }
  catch (e) { showError(e); }
});

/* ------------------------------------------------------ 13. Configurações */
const TABS = [['general', 'sliders'], ['appearance', 'palette'], ['folders', 'folder'], ['index', 'db'], ['ai', 'spark'], ['network', 'wifi'], ['security', 'shield'], ['dev', 'terminal']];

function openSettings(tab = 'general') {
  $('#settings').classList.remove('hidden');
  $('#settings-nav').innerHTML = TABS.map(([k, ic]) => `<button data-tab="${k}">${icon(ic)} ${esc(t('settings.' + k))}</button>`).join('');
  $$('#settings-nav button').forEach(b => b.onclick = () => showTab(b.dataset.tab));
  showTab(tab);
}
$('#settings').addEventListener('click', ev => { if (ev.target.id === 'settings') $('#settings').classList.add('hidden'); });

/** Salva uma alteração parcial e reaplica a interface. */
async function saveSettings(patch, msg = true) {
  try {
    S.settings = await api('/api/settings', { method: 'POST', body: patch });
    applyUI(S.settings.ui);
    if (patch.language) { await loadLang(patch.language); renderActions(); renderChips(); renderTabs(); }
    if (msg) toast(t('common.saved'));
  } catch (e) { showError(e); }
}
function seg(name, value, options) {
  return `<div class="seg" data-seg="${name}">${options.map(([v, l]) => `<button type="button" data-v="${v}" class="${v === value ? 'active' : ''}">${esc(l)}</button>`).join('')}</div>`;
}
function bindSeg(root, fn) {
  $$('[data-seg]', root).forEach(s => $$('button', s).forEach(b => b.onclick = () => {
    $$('button', s).forEach(x => x.classList.toggle('active', x === b)); fn(s.dataset.seg, b.dataset.v);
  }));
}

function showTab(tab) {
  $$('#settings-nav button').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  const body = $('#settings-body'), st = S.settings, ui = st.ui;
  const tabs = {
    /* --- Geral --- */
    general: () => `
      <label class="field"><span>${t('general.language')}</span>
        ${seg('language', st.language, [['pt-BR', 'Português'], ['en', 'English'], ['es', 'Español']])}</label>
      <label class="field"><span>${t('general.logo')}</span><input class="input" id="s-logo" maxlength="24" value="${esc(ui.logo_text)}"></label>
      <label class="field"><span>${t('general.greeting')}</span><input class="input" id="s-greet" maxlength="80" value="${esc(ui.greeting)}" placeholder="${esc(greetingByHour())}"></label>
      <label class="check field"><input type="checkbox" id="s-clock" ${ui.show_clock ? 'checked' : ''}> ${t('general.clock')}</label>
      <p class="muted small">Farol ${esc(st.version)} · ${esc(t('general.mode_' + st.mode))}</p>`,
    /* --- Aparência --- */
    appearance: () => `
      <div class="field"><span>${t('look.theme')}</span>${seg('theme', ui.theme, [['dark', t('look.dark')], ['light', t('look.light')], ['auto', t('look.auto')]])}</div>
      <div class="field"><span>${t('look.accent')}</span><div class="swatches">
        ${['#5b8cff', '#00c2a8', '#ff5e7e', '#ffb020', '#a970ff', '#3fcf74', '#ff7a45'].map(c => `<button class="swatch" style="background:${c};width:34px;height:34px;border-radius:50%" data-accent="${c}" title="${c}"></button>`).join('')}
        <input type="color" id="s-accent" value="${esc(ui.accent)}"></div></div>
      <div class="field"><span>${t('look.background')}</span><div class="swatches">
        ${Object.entries(PRESETS).map(([k, p]) => `<button class="swatch ${ui.background.type === 'preset' && ui.background.value === k ? 'active' : ''}" data-preset="${k}" title="${k}" style="background:radial-gradient(circle at 20% 20%,${p[1]},transparent 60%),radial-gradient(circle at 80% 40%,${p[2]},transparent 60%),radial-gradient(circle at 40% 100%,${p[3]},${p[0]})"></button>`).join('')}
        <input type="color" id="s-bgcolor" title="${esc(t('look.solid'))}" value="${ui.background.type === 'color' ? esc(ui.background.value) : '#101420'}">
        <label class="btn">${icon('image')} ${t('look.upload')}<input type="file" id="s-wall" accept="image/png,image/jpeg,image/webp,image/gif" hidden></label>
      </div></div>
      <label class="check field"><input type="checkbox" id="s-anim" ${ui.animated ? 'checked' : ''}> ${t('look.animated')}</label>
      <div class="field"><span>${t('look.blur')} (<b id="blur-v">${ui.blur}</b>px)</span><input type="range" id="s-blur" min="0" max="40" value="${ui.blur}"></div>
      <div class="field"><span>${t('look.tiles')}</span>${seg('tile_style', ui.tile_style, [['glass', t('look.glass')], ['solid', t('look.solid_tiles')], ['outline', t('look.outline')]])}</div>
      <div class="field"><span>${t('look.font')}</span>${seg('font', ui.font, [['system', t('look.f_system')], ['rounded', t('look.f_rounded')], ['serif', t('look.f_serif')], ['mono', t('look.f_mono')]])}</div>
      <div class="field"><span>${t('look.density')}</span>${seg('density', ui.density, [['comfortable', t('look.comfortable')], ['compact', t('look.compact')]])}</div>`,
    /* --- Pastas --- */
    folders: () => `
      <div class="table">${st.roots.map(r => `
        <div class="tr">
          <span><input type="color" value="${esc(r.color)}" data-rcolor="${r.id}" style="width:26px;height:22px;vertical-align:middle"> <strong>${esc(r.name)}</strong>${r.network ? `<span class="tag">${t('folders.network')}</span>` : ''}</span>
          <code class="muted" title="${esc(r.path)}" style="overflow:hidden;text-overflow:ellipsis">${esc(r.path)}</code>
          <label class="check"><input type="checkbox" data-rro="${r.id}" ${r.readonly ? 'checked' : ''}> ${t('folders.readonly')}</label>
          <button class="btn danger" data-rdel="${r.id}">${icon('trash')}</button>
        </div>`).join('') || `<p class="empty">${t('folders.none')}</p>`}</div>
      <h3 style="margin-top:22px">${t('folders.add')}</h3>
      <form id="root-form" class="field">
        <input class="input" name="path" required placeholder="${esc(t('folders.path_ph'))}">
        <div class="row wrap"><input class="input small" name="name" placeholder="${esc(t('folders.name'))}">
          <input type="color" name="color" value="#5b8cff">
          <label class="check"><input type="checkbox" name="network"> ${t('folders.network')}</label>
          <label class="check"><input type="checkbox" name="readonly"> ${t('folders.readonly')}</label>
          <button class="btn primary">${icon('plus')} ${t('common.add')}</button></div>
      </form>
      <div class="warn">${t('folders.network_help')}</div>`,
    /* --- Índice --- */
    index: () => `
      <div class="glass card" id="idx-status">…</div>
      <button class="btn primary" id="idx-run">${icon('db')} ${t('index.run')}</button>
      <div class="field" style="margin-top:18px"><span>${t('index.interval')}</span>
        <input class="input small" type="number" min="0" max="1440" id="s-interval" value="${st.index.interval_minutes}"></div>
      <div class="field"><span>${t('index.max_mb')}</span>
        <input class="input small" type="number" min="1" max="500" id="s-maxmb" value="${st.index.max_content_mb}"></div>
      <label class="check field"><input type="checkbox" id="s-hidden" ${st.index.include_hidden ? 'checked' : ''}> ${t('index.hidden')}</label>`,
    /* --- IA --- */
    ai: () => `
      <div class="warn">${t('ai.privacy')}</div>
      <label class="check field"><input type="checkbox" id="ai-enabled" ${st.ai.enabled ? 'checked' : ''}> ${t('ai.enable')}</label>
      <div class="field"><span>${t('ai.provider')}</span>
        ${seg('provider', st.ai.provider, [['ollama', 'Ollama (offline)'], ['anthropic', 'Claude'], ['openai', 'ChatGPT'], ['openai_compatible', t('ai.compatible')]])}</div>
      <label class="field"><span>${t('ai.model')}</span><input class="input" id="ai-model" value="${esc(st.ai.model)}"></label>
      <label class="field"><span>${t('ai.base_url')}</span><input class="input" id="ai-url" value="${esc(st.ai.base_url)}" placeholder="${esc(t('ai.base_url_ph'))}"></label>
      <label class="field"><span>${t('ai.key')} ${st.ai.has_key ? '✓' : ''}</span><input class="input" type="password" id="ai-key" autocomplete="off" placeholder="${esc(st.ai.has_key ? t('ai.key_saved') : 'sk-...')}"></label>
      <label class="field"><span>${t('ai.context')}</span><input class="input small" type="number" min="0" max="15" id="ai-ctx" value="${st.ai.context_files}"></label>
      <div class="row"><button class="btn primary" id="ai-save">${icon('save')} ${t('common.save')}</button>
        ${st.ai.has_key ? `<button class="btn danger" id="ai-clear">${t('ai.clear_key')}</button>` : ''}</div>
      <p class="muted small" style="margin-top:14px">${t('ai.models_hint')}</p>`,
    /* --- Rede --- */
    network: () => `
      <label class="check field"><input type="checkbox" id="s-scan" ${st.network.scan_enabled ? 'checked' : ''}> ${t('net.enable_scan')}</label>
      <button class="btn" data-go="network">${icon('wifi')} ${t('net.open')}</button>`,
    /* --- Segurança --- */
    security: () => `
      <form id="pw-form" class="field">
        <span>${t('sec.change')}</span>
        <input class="input" type="password" name="current" required placeholder="${esc(t('sec.current'))}" autocomplete="current-password">
        <input class="input" type="password" name="new" required minlength="8" placeholder="${esc(t('sec.new'))}" autocomplete="new-password">
        <input class="input" type="password" name="confirm" required minlength="8" placeholder="${esc(t('sec.confirm'))}" autocomplete="new-password">
        <button class="btn primary">${t('sec.change')}</button>
      </form>
      <label class="field"><span>${t('sec.session_hours')}</span><input class="input small" type="number" min="1" max="720" id="s-hours" value="${st.session_hours}"></label>
      <div class="warn">${t('sec.tips')}</div>`,
    /* --- Modo Dev --- */
    dev: () => `
      <div class="warn">${t('dev.warning')}</div>
      ${S.dev.disabled_by_env ? `<p class="error">${t('err.dev_blocked')}</p>` : `
      <p>${t('dev.status')}: <strong>${st.dev.enabled ? t('common.on') : t('common.off')}</strong></p>
      <form id="dev-form" class="field">
        <input class="input" type="password" name="password" required placeholder="${esc(t('dev.confirm_pw'))}" autocomplete="current-password">
        <input class="input" name="shell" value="${esc(st.dev.shell)}" placeholder="${esc(t('dev.shell_ph'))}">
        <button class="btn ${st.dev.enabled ? 'danger' : 'primary'}">${t(st.dev.enabled ? 'dev.disable' : 'dev.enable')}</button>
      </form>
      <p class="muted small">${t('dev.platform', { os: S.dev.os, ssh: S.dev.ssh_available ? '✓' : '✗', pty: S.dev.pty ? '✓' : '✗' })}</p>`}`,
  };
  body.innerHTML = tabs[tab]();
  bindTab(tab, body);
}

function bindTab(tab, body) {
  const st = S.settings;
  if (tab === 'general') {
    bindSeg(body, (k, v) => saveSettings({ language: v }).then(() => openSettings('general')));
    $('#s-logo').onchange = e => saveSettings({ ui: { logo_text: e.target.value || 'Farol' } });
    $('#s-greet').onchange = e => saveSettings({ ui: { greeting: e.target.value } });
    $('#s-clock').onchange = e => saveSettings({ ui: { show_clock: e.target.checked } });
  }
  if (tab === 'appearance') {
    bindSeg(body, (k, v) => saveSettings({ ui: { [k]: v } }, false));
    $$('[data-accent]').forEach(b => b.onclick = () => { $('#s-accent').value = b.dataset.accent; saveSettings({ ui: { accent: b.dataset.accent } }, false); });
    $('#s-accent').onchange = e => saveSettings({ ui: { accent: e.target.value } }, false);
    $$('[data-preset]').forEach(b => b.onclick = () => {
      $$('[data-preset]').forEach(x => x.classList.toggle('active', x === b));
      saveSettings({ ui: { background: { type: 'preset', value: b.dataset.preset } } }, false);
    });
    $('#s-bgcolor').onchange = e => saveSettings({ ui: { background: { type: 'color', value: e.target.value } } }, false);
    $('#s-wall').onchange = async e => {
      const f = e.target.files[0]; if (!f) return;
      try { S.settings = await api('/api/wallpaper', { method: 'POST', raw: true, body: f, type: f.type }); applyUI(S.settings.ui); toast(t('common.saved')); }
      catch (err) { showError(err); }
    };
    $('#s-anim').onchange = e => saveSettings({ ui: { animated: e.target.checked } }, false);
    $('#s-blur').oninput = e => { $('#blur-v').textContent = e.target.value; document.documentElement.style.setProperty('--blur', e.target.value + 'px'); };
    $('#s-blur').onchange = e => saveSettings({ ui: { blur: +e.target.value } }, false);
  }
  if (tab === 'folders') {
    $('#root-form').onsubmit = async ev => {
      ev.preventDefault();
      const f = ev.target;
      try {
        S.settings = await api('/api/roots', { method: 'POST', body: { path: f.path.value, name: f.name.value, color: f.color.value, network: f.network.checked, readonly: f.readonly.checked } });
        toast(t('folders.added')); showTab('folders');
      } catch (e) { showError(e); }
    };
    $$('[data-rdel]').forEach(b => b.onclick = async () => {
      if (!confirm(t('folders.confirm_remove'))) return;
      S.settings = await api(`/api/roots/${b.dataset.rdel}`, { method: 'DELETE' }); showTab('folders');
    });
    $$('[data-rro]').forEach(c => c.onchange = async () => { S.settings = await api(`/api/roots/${c.dataset.rro}`, { method: 'POST', body: { readonly: c.checked } }); });
    $$('[data-rcolor]').forEach(c => c.onchange = async () => { S.settings = await api(`/api/roots/${c.dataset.rcolor}`, { method: 'POST', body: { color: c.value } }); });
  }
  if (tab === 'index') {
    const refresh = async () => {
      if ($('#idx-status') === null) return;
      const d = await api('/api/index/status'), s = d.status;
      const kinds = Object.entries(d.stats.kinds).map(([k, v]) => `${t('kind_s.' + k)}: ${v.count.toLocaleString(S.lang)}`).join(' · ');
      $('#idx-status').innerHTML = `
        <p><strong>${s.running ? '⏳ ' + t('index.running') : '✓ ' + t('index.idle')}</strong></p>
        <p class="muted small">${t('index.progress', { s: s.scanned.toLocaleString(S.lang), i: s.indexed.toLocaleString(S.lang), r: s.removed })}</p>
        ${s.current ? `<p class="muted small" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(s.current)}</p>` : ''}
        <p class="small">${t('index.total', { n: d.stats.total.toLocaleString(S.lang) })}</p><p class="muted small">${esc(kinds)}</p>
        ${s.errors.length ? `<details class="small"><summary>${t('index.errors', { n: s.errors.length })}</summary><pre style="white-space:pre-wrap">${esc(s.errors.join('\n'))}</pre></details>` : ''}`;
      if (s.running) setTimeout(refresh, 1500);
    };
    refresh();
    $('#idx-run').onclick = async () => { await api('/api/index/run', { method: 'POST' }); setTimeout(refresh, 300); };
    $('#s-interval').onchange = e => saveSettings({ index: { interval_minutes: +e.target.value } });
    $('#s-maxmb').onchange = e => saveSettings({ index: { max_content_mb: +e.target.value } });
    $('#s-hidden').onchange = e => saveSettings({ index: { include_hidden: e.target.checked } });
  }
  if (tab === 'ai') {
    let provider = st.ai.provider;
    const defaults = { ollama: 'llama3.1', anthropic: 'claude-sonnet-5-5', openai: 'gpt-4.1-mini', openai_compatible: '' };
    bindSeg(body, (k, v) => { provider = v; if (!$('#ai-model').value || Object.values(defaults).includes($('#ai-model').value)) $('#ai-model').value = defaults[v]; });
    $('#ai-save').onclick = () => saveSettings({ ai: {
      enabled: $('#ai-enabled').checked, provider, model: $('#ai-model').value, base_url: $('#ai-url').value,
      api_key: $('#ai-key').value, context_files: +$('#ai-ctx').value,
    } }).then(() => { renderActions(); showTab('ai'); });
    if ($('#ai-clear')) $('#ai-clear').onclick = () => saveSettings({ ai: { clear_key: true } }).then(() => showTab('ai'));
  }
  if (tab === 'network') {
    $('#s-scan').onchange = e => saveSettings({ network: { scan_enabled: e.target.checked } });
  }
  if (tab === 'security') {
    $('#pw-form').onsubmit = async ev => {
      ev.preventDefault();
      const f = ev.target;
      if (f.new.value !== f.confirm.value) return toast(t('sec.mismatch'));
      try { await api('/api/password', { method: 'POST', body: { current: f.current.value, new: f.new.value } }); f.reset(); toast(t('sec.changed')); }
      catch (e) { showError(e); }
    };
    $('#s-hours').onchange = e => saveSettings({ session_hours: +e.target.value });
  }
  if (tab === 'dev' && $('#dev-form')) {
    $('#dev-form').onsubmit = async ev => {
      ev.preventDefault();
      const f = ev.target;
      try {
        S.settings = await api('/api/dev/enable', { method: 'POST', body: { password: f.password.value, enabled: !st.dev.enabled, shell: f.shell.value } });
        toast(t(S.settings.dev.enabled ? 'dev.enabled_msg' : 'dev.disabled_msg'));
        if (!S.settings.dev.enabled) { disconnectTerm(); if (location.hash.startsWith('#/dev')) location.hash = '#/'; }
        renderActions(); showTab('dev');
      } catch (e) { showError(e); }
    };
  }
}

/* ------------------------------------------------- 14. Atalhos de teclado */
document.addEventListener('keydown', ev => {
  const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName) || document.activeElement.closest('.xterm');
  if (ev.key === 'Escape') {
    if (!$('#viewer').classList.contains('hidden')) closeViewer();
    else if (!$('#settings').classList.contains('hidden')) $('#settings').classList.add('hidden');
    else if (!$('#ai-panel').classList.contains('hidden')) toggleAI(false);
    return;
  }
  if (typing) return;
  if (ev.key === '/' || ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'k')) {
    ev.preventDefault();
    const inp = $('#home').classList.contains('hidden') ? $('#topbar input') : $('#home [data-search] input');
    inp.focus(); inp.select();
  }
  if (ev.key === ' ' && !$('#player').classList.contains('hidden') && $('#viewer').classList.contains('hidden')) {
    ev.preventDefault(); $('#pl-play').click();
  }
});
matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => { if (S.settings) applyUI(S.settings.ui); });

applyI18n();
boot();
