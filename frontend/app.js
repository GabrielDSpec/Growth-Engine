let contentAnalysisPollActive = false;
let videos = [];
let dashboard = { metrics: { videos_analisados: 0, views_top_15_display: '0', taxa_likes: null }, videos: [], last_sync_at: null };
let cutSources = [];
let selectedCutSource = null;
let cutDurationRange = { min: 30, max: 60 };
let cutOptionalSettings = { captions: false };
let captionDefaults = { style: 'clean', font: 'Arial', size: 54, position: 'bottom', singleLine: false, primaryColor: '#FFFFFF', highlightColor: '#FFE45C', strokeColor: '#000000', strokeSize: 3, backgroundColor: '#000000', backgroundAlpha: 50 };
let captionGallery = [];
let captionFonts = ['Arial', 'Montserrat', 'Poppins', 'Bebas Neue', 'DejaVu Sans'];
const captionStyleLabel = style => style.animation === 'karaoke' ? `${style.name} · Karaoke` : style.name;
const captionColorValue = value => ({ black: '#000000', white: '#FFFFFF', coral: '#FF4B5B' }[String(value || '').toLowerCase()] || value || '#000000');
const captionColorSwatches = [['#000000', 'Preto'], ['#FFFFFF', 'Branco'], ['#FF4B5B', 'Coral'], ['#FFE45C', 'Amarelo'], ['#3B82F6', 'Azul']];
function createCaptionColorControl(inputAttributes) {
  const input = createElement('input', inputAttributes);
  const current = createElement('span', { className: 'caption-color-current', style: `background-color: ${input.value}` });
  const swatches = createElement('div', { className: 'caption-color-swatches' }, captionColorSwatches.map(([value, label]) => createElement('button', { type: 'button', className: 'caption-color-swatch', 'data-caption-color': value, title: label, 'aria-label': label, style: `--swatch-color: ${value}` })));
  input.addEventListener('input', () => { current.style.backgroundColor = input.value; });
  return { input, control: createElement('div', { className: 'caption-color-control' }, [input, current, swatches]) };
}
let cutSuggestions = [];
let persistedCuts = [];
const selectedCandidateIds = new Set();
let transcriptionJob = null;
let cutJob = null;
const activeCutOperations = new Map();
const captionBatchJobs = new Map();
let uploadProgress = null;
let scheduledVideos = [];
let libraryVideos = [];
let libraryFilter = 'all';
let librarySort = 'recent';
let libraryDetail = null;
let manualAnalysisTask = { status: 'idle', progress: 0, message: 'Nenhuma análise manual executada', eta_seconds: null };
let projectionPeriod = '1_month';
let connectedProfiles = [];
let locationSettings = { bairro: '', cidade: '', estado: '' };
let radarData = null;
let opportunities = [];
let profileTask = { status: 'idle', progress: 0, processed: 0, total: 0, message: 'Nenhum perfil gerado', eta_seconds: null };
let opportunityTask = { status: 'idle', progress: 0, message: 'Nenhuma sugestão gerada', eta_seconds: null };
let notifications = { notificacoes: [], nao_lidas: 0 };
let notificationSnapshotReady = false;
let notificationIds = new Set();
let searchResults = [];
let contentAnalysisStatus = { status: 'idle', processed: 0, total: 0, cache: { pendentes: 0 } };
let autopsyData = { metrics: {}, top_performers: [], flops: [], semantic: {} };
let autopsyFilters = { top: 'all', flop: 'all' };
let autopsyPickerVideos = [];
let activeProfileId = Number(localStorage.getItem('growth-engine-profile-id') || 1);
let profileCatalog = [];
let profileSwitchInProgress = false;
let isAdmin = false;
const activeJobStorageKey = () => `growth-engine-active-job:${activeProfileId}`;
function rememberActiveJob(kind, job) { localStorage.setItem(activeJobStorageKey(), JSON.stringify({ kind, job })); }
function forgetActiveJob(jobId) {
  try {
    const saved = JSON.parse(localStorage.getItem(activeJobStorageKey()) || 'null');
    if (!jobId || saved?.job?.id === jobId) localStorage.removeItem(activeJobStorageKey());
  } catch (error) { localStorage.removeItem(activeJobStorageKey()); }
}
const nativeFetch = window.fetch.bind(window);
window.fetch = (input, init = {}) => {
  const url = typeof input === 'string' ? input : input.url;
  const headers = new Headers(init.headers || {});
  if (url.startsWith('/api/') && url !== '/api/profiles' && url !== '/api/profiles/active' && !headers.has('X-Profile-Id')) headers.set('X-Profile-Id', String(activeProfileId));
  return nativeFetch(input, { ...init, headers });
};
const demoVideos = [
  { title: 'O conteúdo ruim está vencendo', type: 'Longo', views: '12,4k', likes: '804', date: '17 set 2026', score: '6,5%' },
  { title: 'A verdade sobre criar conteúdo', type: 'Longo', views: '9,8k', likes: '611', date: '11 set 2026', score: '6,2%' },
  { title: 'O erro que todo criador comete', type: 'Longo', views: '7,2k', likes: '398', date: '03 set 2026', score: '5,5%' },
  { title: 'Qualidade não garante views', type: 'Short', views: '42,1k', likes: '2,8k', date: '30 ago 2026', score: '6,7%' },
  { title: 'Marketing não é manipulação', type: 'Short', views: '35,6k', likes: '2,1k', date: '25 ago 2026', score: '5,9%' },
];

const state = { view: 'overview', rankingType: 'video' };
const appView = document.querySelector('#app-view');
const breadcrumb = document.querySelector('#breadcrumb-current');
const labels = { overview: 'Visão geral', ranking: 'Ranking', autopsy: 'Autópsia', suggestions: 'Próximos vídeos', radar: 'Radar local', opportunities: 'Oportunidades', cuts: 'Central de cortes', library: 'Biblioteca', publishing: 'Publicação', settings: 'Configurações', admin: 'Painel Admin' };
const savedTheme = localStorage.getItem('growth-engine-theme') || 'light';
document.documentElement.dataset.theme = savedTheme;

function icon(name) { return `<i data-lucide="${name}"></i>`; }
function refreshIcons() { if (window.lucide) lucide.createIcons(); }
async function loadNotifications() {
  try {
    const response = await fetch('/api/notifications');
    if (response.ok) {
      const nextNotifications = await response.json();
      const freshNotifications = notificationSnapshotReady
        ? (nextNotifications.notificacoes || []).filter(item => !notificationIds.has(item.id))
        : [];
      notifications = nextNotifications;
      notificationIds = new Set((notifications.notificacoes || []).map(item => item.id));
      notificationSnapshotReady = true;
      freshNotifications.reverse().forEach(item => showToast(`${item.titulo}: ${item.mensagem}`));
    }
    const dot = document.querySelector('#notification-dot');
    if (dot) dot.classList.toggle('visible', notifications.nao_lidas > 0);
  } catch (error) {
  }
}
async function loadProfileCatalog() {
  const response = await nativeFetch('/api/profiles', { cache: 'no-store' });
  if (!response.ok) throw new Error('Perfis indisponíveis');
  profileCatalog = (await response.json()).profiles || [];
  if (!profileCatalog.some(profile => profile.id === activeProfileId) && profileCatalog.length) activeProfileId = profileCatalog[0].id;
  localStorage.setItem('growth-engine-profile-id', String(activeProfileId));
  mountProfileSelector(profileCatalog);
  updateGoogleIdentity(profileCatalog.find(profile => profile.id === activeProfileId));
  await loadCurrentUser();
}
async function loadCurrentUser() {
  try {
    const response = await fetch('/api/me', { cache: 'no-store' });
    const payload = response.ok ? await response.json() : {};
    isAdmin = payload.is_admin === true;
  } catch (error) {
    isAdmin = false;
  }
  const adminNav = document.querySelector('#admin-nav');
  if (adminNav) adminNav.hidden = !isAdmin;
  if (!isAdmin && state.view === 'admin') render('overview');
}
function mountProfileSelector(profiles) {
  const chip = document.querySelector('.user-chip');
  if (!chip) return;
  chip.dataset.action = 'profile-toggle';
  chip.setAttribute('role', 'button');
  chip.setAttribute('tabindex', '0');
  chip.setAttribute('aria-label', 'Alternar perfil');
  document.querySelector('#profile-menu')?.remove();
  const menu = createElement('div', { id: 'profile-menu', className: 'profile-menu', hidden: 'true' });
  profiles.forEach(profile => {
    const option = createElement('button', { type: 'button', className: 'profile-option', 'data-action': 'profile-option', 'data-profile-id': profile.id }, [
      createElement('span', { textContent: profile.canal_nome || profile.nome || `Perfil ${profile.id}` }),
      createElement('small', { textContent: profile.nome || profile.google_account_email || profile.canal_url || '' }),
    ]);
    menu.appendChild(option);
  });
  menu.appendChild(createElement('div', { className: 'profile-menu-divider' }));
  menu.appendChild(createElement('button', { type: 'button', className: 'profile-option profile-menu-action', 'data-action': 'profile-add', textContent: 'Adicionar perfil' }));
  menu.appendChild(createElement('button', { type: 'button', className: 'profile-option profile-menu-action', 'data-action': 'profile-reauthorize', textContent: 'Renovar permissões YouTube' }));
  menu.appendChild(createElement('button', { type: 'button', className: 'profile-option profile-menu-action danger', 'data-action': 'profile-disconnect', textContent: 'Desconectar conta Google' }));
  if (activeProfileId !== 1) menu.appendChild(createElement('button', { type: 'button', className: 'profile-option profile-menu-action danger', 'data-action': 'profile-remove', textContent: 'Remover perfil atual' }));
  document.body.appendChild(menu);
  chip.onclick = () => {
    const rect = chip.getBoundingClientRect();
    menu.style.top = `${rect.bottom + 8}px`;
    menu.style.right = `${Math.max(12, window.innerWidth - rect.right)}px`;
    menu.hidden = !menu.hidden;
  };
}
async function selectProfile(profileId) {
  const nextProfileId = Number(profileId);
  const profileMenu = document.querySelector('#profile-menu');
  if (profileMenu) profileMenu.hidden = true;
  if (profileSwitchInProgress || nextProfileId === activeProfileId) {
    return;
  }
  profileSwitchInProgress = true;
  try {
    const response = await nativeFetch('/api/profiles/active', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ perfil_id: nextProfileId }) });
    if (!response.ok) {
      showToast('Não foi possível alternar o perfil.');
      return;
    }
    activeProfileId = nextProfileId;
    localStorage.setItem('growth-engine-profile-id', String(activeProfileId));
    await loadCurrentUser();
    videos = [];
    cutSources = [];
    selectedCutSource = null;
    cutSuggestions = [];
    persistedCuts = [];
    transcriptionJob = null;
    cutJob = null;
    updateGoogleIdentity(profileCatalog.find(profile => profile.id === activeProfileId));
    render();
    await loadDashboard();
    if (state.view === 'cuts') await loadCutSources();
    if (state.view === 'publishing') await loadScheduled();
    await loadNotifications();
  } catch (error) {
    showToast('Não foi possível carregar o perfil selecionado.');
  } finally {
    mountProfileSelector(profileCatalog);
    profileSwitchInProgress = false;
  }
}
async function addProfile() {
  window.location.href = '/oauth/google/start';
}
function reauthorizeActiveProfile() {
  window.location.href = `/oauth/google/start?perfil_id=${encodeURIComponent(activeProfileId)}&reauthorize=1`;
}
async function removeActiveProfile() {
  if (activeProfileId === 1) return showToast('O Perfil Padrão não pode ser removido.');
  if (!window.confirm('Remover este perfil e todos os dados associados?')) return;
  const response = await fetch('/api/profiles/remove', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ perfil_id: activeProfileId }) });
  if (!response.ok) return showToast('Não foi possível remover o perfil.');
  activeProfileId = 1;
  localStorage.setItem('growth-engine-profile-id', '1');
  await loadProfileCatalog();
  await loadDashboard();
}
async function disconnectActiveProfile() {
  const profile = profileCatalog.find(item => Number(item.id) === activeProfileId);
  const label = profile?.canal_nome || profile?.nome || 'esta conta';
  if (!window.confirm(`Desconectar ${label}? Os dados do perfil serão preservados, mas será necessário autorizar o Google novamente para sincronizar ou publicar.`)) return;
  const response = await fetch('/api/profiles/disconnect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ perfil_id: activeProfileId }) });
  if (!response.ok) return showToast('Não foi possível desconectar a conta Google.');
  document.querySelector('#profile-menu')?.remove();
  await loadProfileCatalog();
  showToast('Conta Google desconectada.');
}
function createElement(tagName, attributes = {}, children = []) {
  const element = document.createElement(tagName);
  Object.entries(attributes).forEach(([name, value]) => {
    if (value === null || value === undefined) return;
    if (name === 'className') element.className = value;
    else if (name === 'textContent') element.textContent = value;
    else element.setAttribute(name, String(value));
  });
  const childList = Array.isArray(children) ? children : [children];
  childList.flat(Infinity).forEach(child => {
    if (child === null || child === undefined) return;
    element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  });
  return element;
}
function setText(element, value) {
  if (element) element.textContent = value === null || value === undefined ? '' : String(value);
  return element;
}
function setSafeLink(anchor, value) {
  if (!anchor) return anchor;
  try {
    const url = new URL(String(value || ''), window.location.origin);
    if (!['http:', 'https:'].includes(url.protocol)) throw new Error('protocolo bloqueado');
    anchor.href = url.href;
    anchor.target = '_blank';
    anchor.rel = 'noopener noreferrer';
  } catch (error) {
    anchor.href = '#';
    anchor.removeAttribute('target');
    anchor.removeAttribute('rel');
    anchor.setAttribute('aria-disabled', 'true');
  }
  return anchor;
}
function clearElement(element) {
  if (!element) return element;
  while (element.firstChild) element.removeChild(element.firstChild);
  return element;
}
function createVideoThumbnail(video, compact = false) {
  const wrapper = createElement('span', { className: `video-thumbnail ${compact ? 'video-thumbnail-compact' : ''}` });
  const image = createElement('img', { src: video.thumbnail_local_url || video.thumbnail_url || '', alt: '', loading: 'lazy' });
  const remoteUrl = video.thumbnail_url || '';
  const fallbackUrl = video.thumbnail_local_url || '';
  image.addEventListener('error', () => {
    if (image.dataset.fallbackTried !== 'true' && fallbackUrl && image.src !== new URL(fallbackUrl, window.location.href).href) {
      image.dataset.fallbackTried = 'true';
      image.src = remoteUrl;
      return;
    }
    image.remove();
    wrapper.classList.add('is-missing');
    wrapper.appendChild(createElement('strong', { textContent: String(video.titulo || video.title || 'Vídeo').slice(0, 1).toUpperCase() }));
  }, { once: false });
  wrapper.appendChild(image);
  return wrapper;
}
function toggleNotifications() {
  let panel = document.querySelector('#notifications-panel');
  if (panel) { panel.remove(); return; }
  panel = document.createElement('div');
  panel.id = 'notifications-panel';
  const header = createElement('div', { className: 'notifications-header' }, [
    createElement('strong', { textContent: 'Notificações' }),
    createElement('span', {}, [
      createElement('button', { 'data-action': 'read-all-notifications', textContent: 'Ler todas', ...(notifications.nao_lidas ? {} : { disabled: 'true' }) }),
      createElement('button', { 'data-action': 'clear-read', textContent: 'Limpar lidas' }),
      createElement('button', { 'data-action': 'notifications', textContent: 'Fechar' }),
    ]),
  ]);
  panel.appendChild(header);
  const list = createElement('div', { className: 'notifications-list' });
  notifications.notificacoes.forEach(item => {
    const row = createElement('button', {
      className: `notification-row ${item.lida ? '' : 'unread'}`,
      'data-action': 'read-notification',
      'data-notification-id': item.id,
    }, [
      createElement('strong', { textContent: item.titulo }),
      createElement('span', { textContent: item.mensagem }),
      createElement('small', { textContent: formatDateTime(item.criada_em) }),
    ]);
    list.appendChild(row);
  });
  if (!notifications.notificacoes.length) list.appendChild(createElement('p', { className: 'notifications-empty', textContent: 'Nenhuma notificação.' }));
  panel.appendChild(list);
  document.body.appendChild(panel);
  refreshIcons();
}
async function openSearch() {
  let panel = document.querySelector('#search-panel');
  if (panel) { panel.remove(); return; }
  panel = document.createElement('div');
  panel.id = 'search-panel';
  const input = createElement('input', {
    id: 'global-search-input',
    type: 'search',
    placeholder: 'Buscar vídeos, temas e oportunidades...',
    autofocus: 'true',
  });
  const results = createElement('div', { id: 'search-results', className: 'search-results' }, [
    createElement('p', { textContent: 'Digite para buscar no canal.' }),
  ]);
  panel.appendChild(createElement('div', { className: 'search-box' }, [
    createElement('i', { 'data-lucide': 'search' }),
    input,
  ]));
  panel.appendChild(results);
  document.body.appendChild(panel);
  refreshIcons();
  input.addEventListener('input', () => renderSearchResults(input.value));
  input.focus();
}
async function renderSearchResults(query) {
  const resultsElement = document.querySelector('#search-results');
  const normalized = query.trim().toLowerCase();
  if (!resultsElement || !normalized) {
    if (resultsElement) {
      clearElement(resultsElement);
      resultsElement.appendChild(createElement('p', { textContent: 'Digite para buscar no canal.' }));
    }
    return;
  }
  if (!searchResults.length) {
    try {
      const [rankingResponse, opportunitiesResponse] = await Promise.all([
        fetch('/api/ranking?limit=100'),
        fetch('/api/opportunities'),
      ]);
      const ranking = rankingResponse.ok ? (await rankingResponse.json()).videos || [] : [];
      const opportunityItems = opportunitiesResponse.ok ? (await opportunitiesResponse.json()).oportunidades || [] : [];
      searchResults = [
        ...ranking.map(item => ({ kind: 'Vídeo', title: item.title, detail: `${item.type} · ${item.views_display} views`, action: 'ranking' })),
        ...opportunityItems.map(item => ({ kind: 'Oportunidade', title: item.titulo, detail: `Score ${item.score || 0}/100`, action: 'opportunities' })),
      ];
    } catch (error) {
      clearElement(resultsElement);
      resultsElement.appendChild(createElement('p', { textContent: 'Não foi possível carregar a busca.' }));
      return;
    }
  }
  const matches = searchResults.filter(item => `${item.title} ${item.detail}`.toLowerCase().includes(normalized)).slice(0, 12);
  clearElement(resultsElement);
  if (!matches.length) {
    resultsElement.appendChild(createElement('p', { textContent: 'Nenhum resultado encontrado.' }));
    return;
  }
  matches.forEach(item => resultsElement.appendChild(createElement('button', {
    className: 'search-result',
    'data-action': 'search-result',
    'data-result-action': item.action,
  }, [
    createElement('span', { textContent: item.kind }),
    createElement('strong', { textContent: item.title }),
    createElement('small', { textContent: item.detail }),
  ])));
}
async function readNotification(id) {
  await fetch('/api/notifications/read', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id }) });
  await loadNotifications();
  const panel = document.querySelector('#notifications-panel');
  if (panel) { panel.remove(); toggleNotifications(); }
}
async function clearReadNotifications() {
  const response = await fetch('/api/notifications/clear-read', { method: 'POST' });
  if (!response.ok) return showToast('Não foi possível limpar as notificações lidas.');
  const payload = await response.json();
  notifications = payload;
  notificationIds = new Set((notifications.notificacoes || []).map(item => item.id));
  notificationSnapshotReady = true;
  const dot = document.querySelector('#notification-dot');
  if (dot) dot.classList.toggle('visible', notifications.nao_lidas > 0);
  const panel = document.querySelector('#notifications-panel');
  if (panel) panel.remove();
  showToast(payload.removidas ? `${payload.removidas} notificação(ões) lida(s) removida(s).` : 'Não havia notificações lidas para remover.');
}
async function readAllNotifications() {
  let response = await fetch('/api/notifications/read-all', { method: 'POST' });
  let payload;
  if (response.status === 404) {
    const unread = (notifications.notificacoes || []).filter(item => !item.lida);
    const results = await Promise.all(unread.map(item => fetch('/api/notifications/read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: item.id }),
    })));
    if (results.some(result => !result.ok)) return showToast('Não foi possível marcar todas as notificações como lidas.');
    await loadNotifications();
    payload = { ...notifications, marcadas: unread.length };
  } else {
    if (!response.ok) return showToast('Não foi possível marcar todas as notificações como lidas.');
    payload = await response.json();
  }
  notifications = payload;
  notificationIds = new Set((notifications.notificacoes || []).map(item => item.id));
  notificationSnapshotReady = true;
  const dot = document.querySelector('#notification-dot');
  if (dot) dot.classList.toggle('visible', notifications.nao_lidas > 0);
  const panel = document.querySelector('#notifications-panel');
  if (panel) { panel.remove(); toggleNotifications(); }
  showToast(payload.marcadas ? `${payload.marcadas} notificação(ões) marcada(s) como lida(s).` : 'Não havia notificações não lidas.');
}
function showToast(message) {
  const container = document.querySelector('#toast');
  if (!container) return;
  const item = createElement('div', { className: 'toast-item', role: 'status', textContent: message });
  container.appendChild(item);
  requestAnimationFrame(() => item.classList.add('show'));
  setTimeout(() => {
    item.classList.remove('show');
    item.addEventListener('transitionend', () => item.remove(), { once: true });
  }, 3000);
}
function metric(label, value, meta, neutral = false) { return `<div class="metric-card"><span class="metric-label">${label}</span><strong class="metric-value">${value}</strong><span class="metric-meta ${neutral ? 'neutral' : ''}">${meta}</span></div>`; }
function button(label, iconName, cls = 'secondary', action = '') { return `<button class="button ${cls}" data-action="${action}">${icon(iconName)}${label}</button>`; }
function formatRate(value) { return value === null || value === undefined ? 'sem dados' : `${String(value).replace('.', ',')}%`; }
function formatCount(value) {
  if (value === null || value === undefined || value === '') return 'sem dados';
  const number = Number(value);
  if (!Number.isFinite(number)) return 'sem dados';
  return new Intl.NumberFormat('pt-BR', { notation: 'compact', maximumFractionDigits: 1 }).format(number);
}
function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character])); }
function formatLocation(location) {
  const title = value => String(value || '').toLowerCase().split(/\s+/).filter(Boolean).map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
  const state = String(location?.estado || '').toUpperCase();
  return [title(location?.bairro), title(location?.cidade), state].filter(Boolean).join(' - ');
}
function formatDateTime(value) {
  if (!value) return 'data indisponível';
  const timestamp = new Date(`${String(value).replace(' ', 'T')}Z`);
  if (Number.isNaN(timestamp.getTime())) return 'data indisponível';
  const parts = new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(timestamp).reduce((result, part) => {
    result[part.type] = part.value;
    return result;
  }, {});
  return `${parts.hour}:${parts.minute} · ${parts.day}/${parts.month}/${parts.year}`;
}
function parseJobDiagnostics(job) {
  const raw = job?.diagnostics || job?.resultado_json;
  if (!raw) return null;
  try {
    const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw;
    return parsed?.analysis ? parsed : { analysis: parsed };
  } catch (error) { return null; }
}
function formatElapsedSeconds(seconds) {
  if (!Number.isFinite(Number(seconds))) return 'n/d';
  const total = Math.max(0, Math.round(Number(seconds)));
  return `${Math.floor(total / 60)}m ${String(total % 60).padStart(2, '0')}s`;
}
function jobElapsedSeconds(job) {
  if (Number.isFinite(Number(job?.elapsed_seconds))) return Number(job.elapsed_seconds);
  const rawStartedAt = job?.started_at || job?.startedAt;
  const startedAt = Number.isFinite(Number(rawStartedAt)) ? Number(rawStartedAt) : Date.parse(rawStartedAt || '');
  if (!Number.isFinite(startedAt) || startedAt <= 0) return null;
  return Math.max(0, Math.round((Date.now() - startedAt) / 1000));
}
function jobEtaSeconds(job, elapsedSeconds) {
  if (Number.isFinite(Number(job?.eta_seconds))) return Number(job.eta_seconds);
  if (job?.kind === 'captions' || job?.tipo === 'caption_render') {
    const estimatedDuration = Number(job?.estimated_duration_seconds);
    if (!Number.isFinite(estimatedDuration)) return null;
    return Number.isFinite(elapsedSeconds) ? Math.max(1, Math.round(estimatedDuration - elapsedSeconds)) : estimatedDuration;
  }
  const progress = Number(job?.progress || 0);
  if (!Number.isFinite(elapsedSeconds) || progress <= 0 || progress >= 100) return null;
  return Math.max(1, Math.round(elapsedSeconds * (100 - progress) / progress));
}
function buildInsights() {
  const topVideo = videos[0];
  const metrics = dashboard.metrics;
  const rate = formatRate(metrics.taxa_likes);
  const analysis = contentAnalysisStatus;
  const pending = analysis.cache?.pendentes ?? metrics.analises_conteudo_pendentes ?? 0;
  let analysisText;
  if (analysis.status === 'running') {
    analysisText = `Análise em andamento: ${analysis.processed || 0}/${analysis.total || '?'} vídeos processados. ${pending} vídeos longos permanecem na fila.`;
  } else if (analysis.status === 'failed') {
    analysisText = `A análise parou com erro. ${pending} vídeos longos continuam pendentes; verifique o status antes de tentar novamente.`;
  } else if (pending) {
    analysisText = `${pending} vídeos longos aguardam análise. Rode a Autópsia para transformar roteiros reais em padrões, ideias e cortes priorizados.`;
  } else {
    analysisText = 'Conteúdo analisado; o próximo passo é transformar os padrões em ideias e cortes priorizados.';
  }
  return [
    { title: 'Sinal de alcance', text: topVideo ? `${topVideo.title} lidera o ranking com ${topVideo.views_display || topVideo.views} visualizações. Use esse vídeo como referência de tema e embalagem.` : 'Sincronize o canal para descobrir quais vídeos realmente lideram o alcance.' },
    { title: 'Sinal de engajamento', text: metrics.taxa_likes === null ? 'Ainda não há likes suficientes para calcular uma taxa confiável.' : `A taxa média observada é ${rate}. Compare esse número por formato antes de repetir um padrão.` },
    { title: 'Próximo passo operacional', text: analysisText },
  ];
}
function updateGoogleIdentity(profile) {
  if (!profile) return;
  const name = document.querySelector('#google-account-name');
  const avatar = document.querySelector('#google-avatar');
  const workspaceName = document.querySelector('#workspace-name');
  const workspaceAvatar = document.querySelector('#workspace-avatar');
  const displayName = profile.canal_nome || profile.nome || profile.google_account_email || 'Conta Google';
  const workspaceLabel = profile.canal_nome || profile.nome || 'Perfil ativo';
  if (workspaceName) workspaceName.textContent = workspaceLabel;
  if (workspaceAvatar) workspaceAvatar.textContent = workspaceLabel.slice(0, 2).toUpperCase();
  if (name) name.textContent = displayName;
  if (avatar && profile.avatar_url) {
    avatar.textContent = '';
    const image = document.createElement('img');
    image.src = `/api/profiles/google/avatar?perfil_id=${encodeURIComponent(activeProfileId)}`;
    image.alt = '';
    image.addEventListener('error', () => {
      image.remove();
      avatar.textContent = displayName.slice(0, 1).toUpperCase();
    }, { once: true });
    avatar.appendChild(image);
  } else if (avatar) {
    avatar.textContent = displayName.slice(0, 1).toUpperCase();
  }
}
async function loadGoogleIdentity() {
  try {
    const response = await fetch('/api/profiles/google/status');
    const profiles = response.ok ? (await response.json()).profiles || [] : [];
    connectedProfiles = profiles;
    updateGoogleIdentity(profiles.find(profile => Number(profile.perfil_id) === activeProfileId) || profiles[0]);
  } catch (error) {
  }
}
async function loadLocationSettings() {
  try {
    const response = await fetch('/api/radar/location');
    if (response.ok) locationSettings = await response.json();
    if (connectedProfiles.length && !locationSettings.cidade && !localStorage.getItem('growth-engine-location-seen')) {
      render('settings');
      showToast('Informe sua localização para ativar o radar local.');
    }
  } catch (error) {
  }
}
async function saveLocationSettings() {
  const body = {
    bairro: document.querySelector('#location-bairro')?.value || '',
    cidade: document.querySelector('#location-cidade')?.value || '',
    estado: document.querySelector('#location-estado')?.value || '',
  };
  if (!body.cidade) return showToast('Informe pelo menos a cidade.');
  const response = await fetch('/api/radar/location', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!response.ok) return showToast('Não foi possível salvar a localização.');
  locationSettings = await response.json();
  localStorage.setItem('growth-engine-location-seen', '1');
  showToast('Localização salva. Radar local ativado.');
}
async function loadRadar() {
  try {
    const response = await fetch('/api/radar?force=1', { cache: 'no-store' });
    if (!response.ok) throw new Error('Radar indisponível');
    radarData = await response.json();
  } catch (error) {
    radarData = { localizacao_configurada: false, oportunidades: [] };
    showToast('Não foi possível atualizar o Radar.');
  }
  renderRadar();
}
async function loadOpportunities(renderView = true) {
  try {
    const response = await fetch('/api/opportunities');
    opportunities = response.ok ? (await response.json()).oportunidades || [] : [];
    opportunities.sort((left, right) => Number(right.score || 0) - Number(left.score || 0));
  } catch (error) {
    opportunities = [];
  }
  if (renderView) renderOpportunities();
  if (renderView) loadProfileTask();
  if (renderView) loadOpportunityTask();
}
async function generateOpportunities() {
  try {
    const response = await fetch('/api/opportunities/generate', { method: 'POST' });
    const payload = await response.json();
    if (!response.ok) return showToast(payload.error || 'Não foi possível iniciar as sugestões dos Top 15.');
    opportunityTask = { ...opportunityTask, ...payload, status: 'running', progress: 0, eta_seconds: null, message: payload.message || 'Preparando geração de ideias' };
    if (state.view === 'autopsy') renderAutopsy();
    else renderOpportunities();
    showToast('Geração de ideias iniciada.');
    pollOpportunityTask();
  } catch (error) {
    showToast(`Não foi possível iniciar as ideias: ${error.message}`);
  }
}
async function loadOpportunityTask() {
  try {
    const response = await fetch('/api/opportunities/status');
    opportunityTask = await response.json();
    if (state.view === 'autopsy') renderAutopsy();
    if (state.view === 'opportunities') renderOpportunities();
    if (opportunityTask.status === 'running') setTimeout(loadOpportunityTask, 1000);
  } catch (error) {
  }
}
async function pollOpportunityTask() {
  try {
    const response = await fetch('/api/opportunities/status');
    opportunityTask = await response.json();
    if (state.view === 'autopsy') renderAutopsy();
    if (state.view === 'opportunities') renderOpportunities();
    if (opportunityTask.status === 'running') {
      setTimeout(pollOpportunityTask, 1000);
    } else {
      await loadOpportunities(false);
      if (state.view === 'autopsy') renderAutopsy();
      else renderOpportunities();
      showToast(opportunityTask.message || 'Geração de ideias concluída.');
    }
  } catch (error) {
    setTimeout(pollOpportunityTask, 1500);
  }
}
async function loadProfileTask() {
  try {
    const response = await fetch('/api/content-profile/status');
    profileTask = await response.json();
    renderOpportunities();
    if (profileTask.status === 'running') setTimeout(loadProfileTask, 1800);
  } catch (error) {
  }
}
async function pollProfileStatus() {
  try {
    const response = await fetch('/api/content-profile/status');
    profileTask = await response.json();
    renderOpportunities();
    if (profileTask.status === 'running') {
      setTimeout(pollProfileStatus, 1800);
    }
  } catch (error) {
  }
}
async function startProfileRebuild() {
  const response = await fetch('/api/content-profile/rebuild', { method: 'POST' });
  if (!response.ok) return showToast('Não foi possível iniciar o perfil semântico.');
  profileTask = { status: 'running', processed: 0, total: 3, progress: 0, eta_seconds: null, message: 'Preparando perfil semântico' };
  renderOpportunities();
  pollProfileStatus();
}
function domIcon(name) { return createElement('i', { 'data-lucide': name }); }
function domButton(label, iconName, cls, action, extraAttributes = {}) {
  return createElement('button', { className: `button ${cls}`, 'data-action': action, ...extraAttributes }, [domIcon(iconName), label]);
}
function domText(tagName, className, value) {
  return createElement(tagName, { className, textContent: value });
}
function captionPreviewScale(stage) {
  return Math.max(0.1, stage.getBoundingClientRect().width / 1080);
}
function scaleCaptionShadow(shadow, scale) {
  return String(shadow || '').replace(/(-?\d+(?:\.\d+)?)px/g, (_, value) => `${(Number(value) * scale).toFixed(2)}px`);
}
function fitSingleLineCaption(stage, text, requestedSize) {
  if (text.style.whiteSpace !== 'nowrap') return;
  const fit = () => {
    const maxWidth = stage.getBoundingClientRect().width * 0.84;
    let fittedSize = requestedSize;
    text.style.fontSize = `${fittedSize}px`;
    while (text.getBoundingClientRect().width > maxWidth && fittedSize > 8) {
      fittedSize *= 0.94;
      text.style.fontSize = `${fittedSize}px`;
    }
  };
  fit();
  requestAnimationFrame(() => { fit(); requestAnimationFrame(fit); });
}
function setupCaptionPreview(stage, text, cut, positionControl) {
  stage.classList.add('caption-preview-interactive');
  if (cut?.id || cut?.cut_id) {
    const cutId = Number(cut.cut_id || cut.id);
    const captionReady = cut.legenda_status === 'concluido' && cut.legenda_caminho;
    const mediaVersion = captionReady ? (cut.legenda_caminho || cut.atualizado_em) : (cut.caminho_saida || cut.atualizado_em);
    const media = createElement('video', { className: 'caption-preview-media', loop: 'true', playsinline: 'true', preload: 'metadata' });
    media.muted = true;
    media.defaultMuted = true;
    media.volume = 0;
    media.addEventListener('loadeddata', () => { media.play().catch(() => {}); }, { once: true });
    media.src = `/api/cuts/file?id=${encodeURIComponent(cutId)}&captions=${captionReady ? '1' : '0'}&perfil_id=${encodeURIComponent(activeProfileId)}&v=${encodeURIComponent(mediaVersion || '')}`;
    stage.insertBefore(media, stage.firstChild);
  }
  text.style.position = 'absolute';
  text.style.left = '50%';
  text.style.transform = 'translate(-50%, -50%)';
  const applyPosition = (position, exactY = null, exactX = null) => {
    const top = exactY !== null && exactY !== undefined ? `${exactY}%` : position === 'top' ? '22%' : position === 'center' ? '50%' : '78%';
    const left = exactX !== null && exactX !== undefined ? `${exactX}%` : '50%';
    text.style.top = top;
    text.style.left = left;
    if (positionControl) positionControl.value = position;
    if (exactY !== null && exactY !== undefined) text.dataset.positionY = String(exactY);
    else delete text.dataset.positionY;
    if (exactX !== null && exactX !== undefined) text.dataset.positionX = String(exactX);
    else delete text.dataset.positionX;
  };
  applyPosition(positionControl?.value || 'bottom');
  let dragging = false;
  text.addEventListener('pointerdown', event => { dragging = true; text.setPointerCapture?.(event.pointerId); event.preventDefault(); });
  text.addEventListener('pointermove', event => {
    if (!dragging) return;
    const bounds = stage.getBoundingClientRect();
    const horizontalRatio = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width));
    const ratio = Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height));
    text.style.left = `${(horizontalRatio * 100).toFixed(2)}%`;
    text.style.top = `${(ratio * 100).toFixed(2)}%`;
    text.dataset.positionX = (horizontalRatio * 100).toFixed(2);
    text.dataset.positionY = (ratio * 100).toFixed(2);
  });
  text.addEventListener('pointerup', () => { dragging = false; });
  text.addEventListener('pointercancel', () => { dragging = false; });
  if (typeof ResizeObserver === 'function') new ResizeObserver(() => stage.dispatchEvent(new Event('caption-preview-resize'))).observe(stage);
  return applyPosition;
}
function replaceView(element) {
  clearElement(appView);
  appView.appendChild(element);
  refreshIcons();
}
function renderRadarCard(item) {
  const article = createElement('article', { className: 'opportunity-card' });
  const labels = createElement('div', { className: 'opportunity-labels' }, [
    domText('span', 'suggestion-type', item.categoria || 'oportunidade'),
    domText('span', 'semantic-score', `Relevância ${item.relevancia_score || 0}/100`),
  ]);
  const title = domText('h3', '', item.titulo_curto || item.titulo || '');
  title.title = item.titulo || '';
  article.append(labels, title, domText('p', '', item.motivo || 'Verifique a relevância para o canal.'));
  const meta = createElement('div', { className: 'opportunity-meta' });
  const links = createElement('span');
  const sourceLink = setSafeLink(createElement('a'), item.link);
  sourceLink.append('Fonte ', domIcon('arrow-up-right'));
  const mapLink = setSafeLink(createElement('a'), item.mapa_url);
  mapLink.append('Mapa ', domIcon('map'));
  links.append(sourceLink, document.createTextNode(' '), mapLink);
  meta.append(domText('span', '', item.fonte || 'fonte externa'), links);
  article.appendChild(meta);
  return article;
}
function renderRadar() {
  const localRows = (radarData?.oportunidades_locais || []).filter(item => item.titulo).map(renderRadarCard);
  const nicheRows = (radarData?.oportunidades_nicho || []).filter(item => item.titulo).map(renderRadarCard);
  const locationText = formatLocation(radarData?.localizacao);
  const root = createElement('div', { className: 'view-card active' });
  const header = createElement('div', { className: 'page-header' }, [
    createElement('div', {}, [domText('span', 'eyebrow', 'Central / radar'), domText('h1', '', 'O que merece virar pauta?'), domText('p', '', 'Dois radares separados: oportunidades graváveis perto de você e notícias recentes dos temas com maior relevância no canal.')]),
    createElement('div', { className: 'header-actions' }, [domButton('Atualizar Radar', 'refresh-cw', 'secondary', 'radar-refresh'), domButton('Configurar localização', 'map-pin', 'lime', 'settings')]),
  ]);
  const local = createElement('details', { className: 'radar-section', open: 'true' }, [createElement('summary', {}, [domText('span', '', 'Radar local'), domText('small', '', locationText || 'localização não configurada')])]);
  if (radarData?.localizacao_configurada) {
    const grid = createElement('div', { className: 'opportunity-grid' });
    localRows.forEach(row => grid.appendChild(row));
    if (!localRows.length) grid.appendChild(domText('div', 'panel empty-state', 'Nenhuma oportunidade local encontrada nos últimos 7 dias.'));
    local.appendChild(grid);
  } else local.appendChild(createElement('div', { className: 'panel empty-state' }, [domText('h2', '', 'Localização necessária'), domText('p', '', 'Informe bairro e cidade em Configurações para ativar eventos próximos.') ]));
  const niche = createElement('details', { className: 'radar-section', open: 'true' }, [createElement('summary', {}, [domText('span', '', 'Radar de nicho'), domText('small', '', (radarData?.temas_do_canal || []).join(' · '))])]);
  const nicheGrid = createElement('div', { className: 'opportunity-grid' });
  nicheRows.forEach(row => nicheGrid.appendChild(row));
  if (!nicheRows.length) nicheGrid.appendChild(domText('div', 'panel empty-state', 'Nenhuma notícia recente de nicho encontrada.'));
  niche.appendChild(nicheGrid);
  root.append(header, local, niche);
  replaceView(root);
}
function renderOpportunityProgress() {
  if (opportunityTask.status === 'running') {
    const eta = opportunityTask.eta_seconds == null ? 'calculando ETA...' : `ETA aproximado: ${formatElapsedSeconds(opportunityTask.eta_seconds)}`;
    return createElement('div', { className: 'progress-box opportunity-progress' }, [
      createElement('div', { className: 'progress-head' }, [domText('span', '', opportunityTask.message || 'Gerando ideias'), domText('strong', '', `${opportunityTask.progress || 0}%`)]),
      createElement('div', { className: 'progress-track' }, [createElement('span', { style: `width:${opportunityTask.progress || 0}%` })]),
      domText('p', 'task-meta', eta),
    ]);
  }
  if (opportunityTask.status === 'failed') return domText('div', 'progress-box task-error', `Falha ao gerar ideias: ${opportunityTask.message}`);
  if (opportunityTask.status === 'completed') return domText('div', 'opportunity-complete-note', opportunityTask.message || 'Ideias geradas e prontas para revisão.');
  return null;
}
function renderOpportunities() {
  const root = createElement('div', { className: 'view-card active' });
  root.appendChild(createElement('div', { className: 'page-header' }, [createElement('div', {}, [domText('span', 'eyebrow', 'Central / oportunidades'), domText('h1', '', 'Transforme sinais em pautas.'), domText('p', '', 'Estas sugestões vêm exclusivamente da Autópsia dos Top 15, não do Radar.')]), createElement('div', { className: 'header-actions' }, [domButton(opportunityTask.status === 'running' ? 'Gerando ideias...' : 'Gerar sugestões dos Top 15', opportunityTask.status === 'running' ? 'loader-circle' : 'sparkles', 'lime', 'generate-opportunities', { disabled: opportunityTask.status === 'running' })])]));
  const opportunityProgress = renderOpportunityProgress();
  if (opportunityProgress) root.appendChild(opportunityProgress);
  if (profileTask.status === 'running') {
    const progress = createElement('div', { className: 'progress-box' }, [createElement('div', { className: 'progress-head' }, [domText('span', '', profileTask.message), domText('strong', '', `${profileTask.progress || 0}%`)]), createElement('div', { className: 'progress-track' }, [createElement('span', { style: `width:${profileTask.progress || 0}%` })]), domText('p', 'task-meta', `${profileTask.processed}/${profileTask.total} etapas · ${profileTask.eta_seconds == null ? 'calculando término...' : `termina em ~${Math.max(1, profileTask.eta_seconds)}s`}`)]);
    root.appendChild(progress);
  }
  if (profileTask.status === 'failed') root.appendChild(domText('div', 'progress-box task-error', `Falha: ${profileTask.message}`));
  const grid = createElement('div', { className: 'opportunity-grid' });
    opportunities.forEach(item => {
    const evidence = item.evidence || {};
    const videoIds = evidence.video_ids || [];
    const videoNames = evidence.video_names || {};
    const baseText = videoIds.map(id => videoNames[id] ? `${videoNames[id]} (${id})` : id).join(' · ') || 'Vídeos-base não informados';
    const evidenceText = evidence.trechos?.[0] || item.origem_resumo || 'Evidência da Autópsia dos Top 15 registrada no briefing.';
    const article = createElement('article', { className: 'opportunity-card' }, [domText('p', 'opportunity-score-text', `Score ${item.score || 0}/100`), domText('h3', '', item.titulo), domText('p', '', item.contexto || 'Sem contexto adicional.'), domText('small', 'opportunity-evidence-source', `Base: ${baseText}`), domText('p', 'opportunity-evidence', `Evidência: ${evidenceText}`)]);
    const meta = createElement('div', { className: 'opportunity-meta' }, [domText('span', '', item.fonte || 'autoria interna')]);
    meta.appendChild(createElement('button', { className: 'text-link', 'data-action': 'briefing', 'data-opportunity-id': item.id }, ['VER BRIEFING ', domIcon('arrow-up-right')]));
    article.appendChild(meta);
    grid.appendChild(article);
  });
  if (!opportunities.length) grid.appendChild(domText('div', 'panel empty-state', 'Nenhuma sugestão gerada. Clique em Gerar sugestões dos Top 15.'));
  root.appendChild(grid);
  replaceView(root);
}
async function showBriefingPanel(opportunityId) {
  try {
    const response = await fetch(`/api/opportunities/${opportunityId}/briefing`);
    if (!response.ok) throw new Error('Briefing indisponível');
    const briefing = await response.json();
    document.querySelector('#briefing-panel')?.remove();
    const panel = createElement('aside', { id: 'briefing-panel', className: 'briefing-panel' });
    const evidence = briefing.evidencia || {};
    const names = evidence.video_names || {};
    const ids = evidence.video_ids || [];
    const sources = ids.map(id => names[id] ? `${names[id]} (${id})` : id).join(' · ') || 'Não informado';
    const close = createElement('button', { className: 'briefing-close', 'data-action': 'close-briefing', textContent: 'Fechar' });
    panel.append(createElement('div', { className: 'briefing-header' }, [domText('strong', '', 'Briefing da Oportunidade'), close]), domText('h2', '', briefing.titulo_provisorio), domText('p', 'briefing-origin', `Origem: ${briefing.origem_tipo || 'autopsia_top15'}`), domText('p', '', briefing.promessa), domText('p', '', `Abertura: ${briefing.abertura}`), domText('h3', '', 'Vídeos-base'), domText('p', '', sources), domText('h3', '', 'Evidência literal'), createElement('ul', {}, (evidence.trechos || []).map(text => createElement('li', { textContent: text }))), domText('p', '', `Views: ${evidence.views || 0} · Likes: ${evidence.likes || 0}`), domText('h3', '', 'Versão para Short'), domText('p', '', briefing.versao_short));
    document.body.appendChild(panel);
  } catch (error) {
    showToast('Não foi possível carregar o briefing.');
  }
}
function renderDynamicInsights() {
  const insights = buildInsights();
  const quote = document.querySelector('.insight-quote');
  const source = document.querySelector('.insight-source');
  if (quote) quote.textContent = insights[0].text;
  if (source) source.textContent = `${dashboard.metrics.videos_analisados} vídeos analisados · taxa média de likes ${formatRate(dashboard.metrics.taxa_likes)}`;
  const list = document.querySelector('.insight-list');
  if (list) {
    clearElement(list);
    insights.forEach((insight, index) => list.appendChild(createElement('div', { className: 'insight-row' }, [domText('span', 'insight-index', `0${index + 1}`), createElement('div', {}, [domText('strong', '', insight.title), domText('p', '', insight.text)])])));
  }
  const queueItems = document.querySelectorAll('.queue-item');
  const analysisQueue = queueItems[0];
  if (analysisQueue) {
    const pending = dashboard.metrics.analises_conteudo_pendentes || 0;
    const title = analysisQueue.querySelector('.queue-copy strong');
    const detail = analysisQueue.querySelector('.queue-copy span');
    if (title) title.textContent = 'Analisar vídeos longos';
    if (detail) detail.textContent = pending ? `${pending} pendentes de conteúdo` : 'Conteúdo analisado; gerar ideias';
  }
}
function formatSyncTime(value) {
  if (!value) return 'nunca sincronizada';
  const timestamp = new Date(`${value.replace(' ', 'T')}Z`);
  if (Number.isNaN(timestamp.getTime())) return 'data indisponível';
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp.getTime()) / 60000));
  if (minutes < 1) return 'agora';
  if (minutes === 1) return 'há 1 min';
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours === 1) return 'há 1 h';
  if (hours < 24) return `há ${hours} h`;
  const days = Math.floor(hours / 24);
  return days === 1 ? 'há 1 dia' : `há ${days} dias`;
}
function formatEta(seconds) {
  if (seconds === null || seconds === undefined) return 'calculando término...';
  if (seconds < 60) return `termina em ~${Math.max(1, seconds)}s`;
  const minutes = Math.ceil(seconds / 60);
  return `termina em ~${minutes} min`;
}
function updateSyncStatus() {
  const element = document.querySelector('#sync-last-updated');
  if (element) element.textContent = formatSyncTime(dashboard.last_sync_at);
  const queueItems = document.querySelectorAll('.queue-item');
  const queueSyncTime = queueItems[1]?.querySelector('.queue-copy span');
  if (queueSyncTime) queueSyncTime.textContent = `Última atualização ${formatSyncTime(dashboard.last_sync_at)}`;
}
function updateSyncProgress(payload) {
  const queueItems = document.querySelectorAll('.queue-item');
  const queueSyncTime = queueItems[1]?.querySelector('.queue-copy span');
  if (!queueSyncTime) return;
  if (payload.status === 'running') {
    if (payload.message?.startsWith('Buscando ')) {
      queueSyncTime.textContent = `${payload.message} · calculando total...`;
      return;
    }
    const progress = payload.total ? `${payload.progress}% · ` : '';
    queueSyncTime.textContent = `${progress}${payload.processed}/${payload.total || '?'} vídeos · ${formatEta(payload.eta_seconds)}`;
  } else if (payload.status === 'failed') {
    queueSyncTime.textContent = 'falha na sincronização';
  }
}
function updateContentProgress(payload) {
  contentAnalysisStatus = payload;
  renderDynamicInsights();
  const queueItems = document.querySelectorAll('.queue-item');
  const detail = queueItems[0]?.querySelector('.queue-copy span');
  if (!detail || payload.status !== 'running') return;
  const eta = payload.eta_seconds === null || payload.eta_seconds === undefined ? 'calculando término...' : payload.eta_seconds < 60 ? `termina em ~${Math.max(1, payload.eta_seconds)}s` : `termina em ~${Math.ceil(payload.eta_seconds / 60)} min`;
  detail.textContent = `${payload.progress || 0}% · ${payload.processed}/${payload.total || '?'} vídeos · ${eta}`;
}
async function pollContentStatus() {
  try {
    const response = await fetch('/api/content-analysis/status');
    const payload = await response.json();
    updateContentProgress(payload);
    if (payload.status === 'running') setTimeout(pollContentStatus, 1800);
  } catch (error) {
  }
}
async function loadDashboard() {
  try {
    const response = await fetch('/api/dashboard');
    if (!response.ok) throw new Error('dashboard indisponível');
    dashboard = await response.json();
    videos = dashboard.videos || [];
    render(state.view);
    updateSyncStatus();
    renderDynamicInsights();
    loadGoogleIdentity();
  } catch (error) {
    videos = [];
    showToast('Central visual carregada; sincronize o canal para obter dados reais.');
  }
}
setInterval(() => {
  if (!document.hidden && state.view === 'overview') loadDashboard();
}, 30000);
setInterval(() => {
  if (!document.hidden) loadNotifications();
}, 15000);
async function loadSyncStatus() {
  try {
    const response = await fetch('/api/sync/status');
    const payload = await response.json();
    if (payload.status === 'running') {
      updateSyncProgress(payload);
      setTimeout(pollSync, 1500);
    }
  } catch (error) {
  }
}
setInterval(updateSyncStatus, 60000);
async function loadRanking(tipo = state.rankingType) {
  state.rankingType = tipo;
  try {
    const query = tipo ? `?tipo=${tipo}&limit=15` : '?limit=15';
    const response = await fetch(`/api/ranking${query}`);
    if (!response.ok) throw new Error('ranking indisponível');
    const payload = await response.json();
    videos = payload.videos || [];
    renderRanking();
  } catch (error) {
    videos = [];
    renderRanking();
    showToast('Não foi possível carregar este ranking.');
  }
}
async function loadCutSources() {
  cutSources = [];
  selectedCutSource = null;
  persistedCuts = [];
  cutSuggestions = [];
  selectedCandidateIds.clear();
  try {
    await loadCaptionStyles();
    const response = await fetch('/api/cut-sources');
    if (!response.ok) throw new Error('fontes indisponíveis');
    const payload = await response.json();
    cutSources = payload.videos || [];
    selectedCutSource = cutSources[0] || null;
    if (cutSources.length) {
      const cutsResponse = await fetch(`/api/cuts?video_id=${encodeURIComponent(selectedCutSource.id)}`, { headers: { 'X-Profile-Id': String(activeProfileId) } });
      const cuts = cutsResponse.ok ? (await cutsResponse.json()).cortes || [] : [];
      persistedCuts = cuts.filter(cut => cut.status !== 'excluido' && String(cut.video_id) === String(selectedCutSource.id));
      await selectCutSource(selectedCutSource.id);
      await restoreActiveCutJobs();
      return;
    }
    await restoreActiveCutJobs();
    renderCuts();
  } catch (error) {
    cutSources = [];
    selectedCutSource = null;
    renderCuts();
    showToast('Não foi possível carregar os vídeos para corte.');
  }
}
async function loadCaptionStyles() {
  const builtInCaptionStyles = [
    { style_id: 'clean', name: 'Clean', style: 'clean', font: 'Arial', size: 54, position: 'bottom', stroke_color: 'black', stroke_size: 3 },
    { style_id: 'bold', name: 'Bold', style: 'bold', font: 'Arial', size: 60, position: 'bottom', stroke_color: 'black', stroke_size: 4 },
    { style_id: 'highlight', name: 'Highlight', style: 'highlight', font: 'Arial', size: 56, position: 'bottom', stroke_color: 'black', stroke_size: 3, animation: 'karaoke' },
  ];
  try {
    const response = await fetch('/api/caption-styles', { headers: { 'X-Profile-Id': String(activeProfileId) } });
    if (!response.ok) throw new Error('estilos indisponíveis');
    const styles = (await response.json()).styles || [];
    const stylesById = new Map([...builtInCaptionStyles, ...styles].map(style => [style.style_id, style]));
    captionGallery = [...stylesById.values()];
    const fontsResponse = await fetch('/api/caption-fonts', { headers: { 'X-Profile-Id': String(activeProfileId) } });
    if (fontsResponse.ok) captionFonts = [...new Set([...captionFonts, ...((await fontsResponse.json()).fonts || [])])];
  } catch (error) {
    captionGallery = builtInCaptionStyles;
  }
}
async function importCaptionStyle() {
  const input = document.querySelector('#caption-style-file');
  const file = input?.files?.[0];
  if (!file) return showToast('Escolha um arquivo JSON de estilo.');
  try {
    const payload = JSON.parse(await file.text());
    const response = await fetch('/api/caption-styles/import', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Profile-Id': String(activeProfileId) }, body: JSON.stringify(payload) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Não foi possível importar o estilo.');
    await loadCaptionStyles();
    renderCuts();
    showToast(`Estilo ${result.style.name} importado.`);
  } catch (error) { showToast(error.message || 'JSON de estilo inválido.'); }
}
async function importCaptionFont() {
  const input = document.querySelector('#caption-font-file');
  const file = input?.files?.[0];
  if (!file) return showToast('Escolha uma fonte TTF, OTF ou TTC.');
  try {
    const formData = new FormData();
    formData.append('file', file);
    const response = await fetch('/api/caption-fonts/import', { method: 'POST', headers: { 'X-Profile-Id': String(activeProfileId) }, body: formData });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Não foi possível importar a fonte.');
    await loadCaptionStyles();
    renderCuts();
    showToast(`Fonte ${result.font.name} importada.`);
  } catch (error) { showToast(error.message || 'Fonte inválida.'); }
}
async function restoreActiveCutJobs() {
  try {
    const response = await fetch('/api/jobs/active');
    let jobs = response.ok ? (await response.json()).jobs || [] : [];
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(activeJobStorageKey()) || 'null'); } catch (error) { localStorage.removeItem(activeJobStorageKey()); }
    if (!jobs.length && saved?.job?.id) {
      const savedResponse = await fetch(`/api/jobs/${encodeURIComponent(saved.job.id)}`);
      const savedJob = savedResponse.ok ? await savedResponse.json() : null;
      if (isLiveJob(savedJob)) {
        jobs = [{ ...savedJob, tipo: saved.kind === 'transcription' ? 'transcription' : saved.job.kind === 'captions' ? 'caption_render' : 'cut', cut_ids: saved.job.cut_ids || saved.job.cutIds }];
      } else {
        forgetActiveJob(saved.job.id);
        if (cutJob?.id === saved.job.id) cutJob = null;
        if (transcriptionJob?.id === saved.job.id) transcriptionJob = null;
      }
    }
    if (!jobs.length) {
      cutJob = null;
      transcriptionJob = null;
    }
    const transcription = jobs.find(job => job.tipo === 'transcription');
    const processing = jobs.find(job => job.tipo !== 'transcription');
    if (transcription && !transcriptionJob) {
      transcriptionJob = { id: transcription.job_id || transcription.id, status: transcription.status, progress: transcription.progresso ?? transcription.progress ?? 0, message: transcription.mensagem || transcription.message || 'Transcrição em andamento', video_id: transcription.video_id, perfil_id: transcription.perfil_id || activeProfileId };
      pollTranscriptionJob();
    }
    if (processing && !cutJob) {
      let checkpoint = {};
      try { checkpoint = typeof processing.checkpoint_json === 'string' ? JSON.parse(processing.checkpoint_json) : (processing.checkpoint_json || {}); } catch (error) { checkpoint = {}; }
      const isCaptionJob = processing.tipo === 'caption_render' || checkpoint.kind === 'captions';
      cutJob = { id: processing.job_id || processing.id, kind: isCaptionJob ? 'captions' : processing.tipo, status: processing.status, progress: processing.progresso ?? processing.progress ?? 0, message: processing.mensagem || processing.message || 'Processamento em andamento', video_id: processing.video_id, perfil_id: processing.perfil_id || activeProfileId, started_at: processing.iniciado_em || processing.criado_em, stage: processing.etapa, cut_ids: processing.cut_ids || checkpoint.cut_ids || (checkpoint.cut_id ? [checkpoint.cut_id] : undefined), eta_seconds: processing.eta_seconds, estimated_duration_seconds: processing.estimated_duration_seconds || checkpoint.estimated_duration_seconds };
      pollCutJob();
    }
    if (transcription || processing) renderCuts();
  } catch (error) {
  }
}
async function loadScheduled() {
  try {
    const response = await fetch('/api/publishing/scheduled');
    if (!response.ok) throw new Error('agendamentos indisponíveis');
    scheduledVideos = (await response.json()).videos || [];
    renderPublishing();
  } catch (error) {
    scheduledVideos = [];
    renderPublishing();
    showToast('Não foi possível carregar os agendamentos.');
  }
}
async function loadLibrary() {
  try {
    const params = new URLSearchParams();
    if (libraryFilter !== 'all') params.set('tipo', libraryFilter);
    params.set('ordem', librarySort);
    const query = `?${params.toString()}`;
    const response = await fetch(`/api/library/videos${query}`);
    if (!response.ok) throw new Error('biblioteca indisponível');
    libraryVideos = (await response.json()).videos || [];
    libraryDetail = null;
  } catch (error) {
    libraryVideos = [];
    showToast('Não foi possível carregar a Biblioteca.');
  }
  renderLibrary();
}
async function loadLibraryDetail(videoId) {
  try {
    const [response, statusResponse] = await Promise.all([
      fetch(`/api/library/video?video_id=${encodeURIComponent(videoId)}`),
      fetch(`/api/content-analysis/video/status?video_id=${encodeURIComponent(videoId)}`),
    ]);
    if (!response.ok) throw new Error('análise indisponível');
    libraryDetail = await response.json();
    manualAnalysisTask = statusResponse.ok ? await statusResponse.json() : { status: 'idle', progress: 0, message: 'Nenhuma análise manual executada', eta_seconds: null };
    renderLibraryDetail();
    if (manualAnalysisTask.status === 'queued' || manualAnalysisTask.status === 'running') pollManualAnalysis(videoId);
  } catch (error) {
    showToast('Não foi possível carregar a análise deste vídeo.');
  }
}
async function analyzeLibraryVideo(videoId) {
  try {
    const response = await fetch('/api/content-analysis/video', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ video_id: videoId }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'análise indisponível');
    manualAnalysisTask = { ...payload, status: payload.status || 'queued', progress: payload.progress || 0, message: payload.message || 'Análise na fila', eta_seconds: payload.eta_seconds ?? null };
    renderLibraryDetail();
    showToast('Análise refinada iniciada.');
    pollManualAnalysis(videoId);
  } catch (error) {
    showToast(`Não foi possível analisar o vídeo: ${error.message}`);
  }
}
async function pollManualAnalysis(videoId) {
  const response = await fetch(`/api/content-analysis/video/status?video_id=${encodeURIComponent(videoId)}`);
  if (!response.ok) return;
  manualAnalysisTask = await response.json();
  renderLibraryDetail();
  if (manualAnalysisTask.status === 'queued' || manualAnalysisTask.status === 'running') {
    setTimeout(() => pollManualAnalysis(videoId), 1000);
  } else if (manualAnalysisTask.status === 'completed') {
    await loadLibraryDetail(videoId);
  } else if (manualAnalysisTask.status === 'failed') {
    showToast(`Falha na análise: ${manualAnalysisTask.message}`);
  }
}
async function loadProfiles() {
  try {
    const response = await fetch('/api/profiles/google/status');
    connectedProfiles = response.ok ? (await response.json()).profiles || [] : [];
  } catch (error) {
    connectedProfiles = [];
  }
  renderSettings();
  loadLocationSettings();
}
async function startSync() {
  try {
    const response = await fetch('/api/sync', { method: 'POST' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível iniciar a sincronização.');
    showToast('Sincronização iniciada.');
    pollSync();
  } catch (error) {
    showToast(error.message);
  }
}
async function pollSync() {
  const response = await fetch('/api/sync/status');
  const payload = await response.json();
  if (payload.status === 'running') {
    updateSyncProgress(payload);
    setTimeout(pollSync, 1500);
    return;
  }
  await loadDashboard();
  showToast(payload.message);
}
async function loadAutopsyPickerVideos() {
  const response = await fetch('/api/library/videos?ordem=recent');
  if (!response.ok) throw new Error('Não foi possível carregar os vídeos do perfil.');
  return (await response.json()).videos || [];
}
function openAutopsyPicker(videos) {
  return new Promise(resolve => {
    const selectedIds = new Set();
    let typeFilter = 'all';
    const backdrop = createElement('div', { className: 'cut-modal-backdrop autopsy-picker-backdrop' });
    const panel = createElement('section', { className: 'cut-modal autopsy-picker-modal', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'autopsy-picker-title' });
    const filters = createElement('div', { className: 'autopsy-picker-filters', role: 'tablist', 'aria-label': 'Filtrar vídeos da autópsia' });
    const list = createElement('div', { className: 'autopsy-picker-list' });
    const selectionNote = domText('span', 'autopsy-picker-selection', '0 vídeos selecionados');
    const selectAllButton = domButton('Selecionar todos', 'check-check', 'secondary', 'autopsy-select-all');
    const finish = value => { backdrop.remove(); resolve(value); };
    const filteredVideos = () => videos.filter(video => typeFilter === 'all' || video.tipo === typeFilter);
    const renderList = () => {
      clearElement(list);
      filteredVideos().forEach(video => {
        const selected = selectedIds.has(video.video_id);
        const item = createElement('button', { type: 'button', className: `autopsy-picker-item ${selected ? 'is-selected' : ''}`, 'aria-pressed': selected ? 'true' : 'false' }, [
          createVideoThumbnail(video, true),
          createElement('span', { className: 'autopsy-picker-item-copy' }, [createElement('strong', { textContent: video.titulo || 'Sem título' }), createElement('small', { textContent: `${video.tipo === 'short' ? 'Short' : 'Vídeo longo'} · ${formatCount(Number(video.views || 0))} views` })]),
          createElement('span', { className: 'autopsy-picker-check', 'aria-hidden': 'true' }, [domIcon(selected ? 'check' : 'plus')]),
        ]);
        item.addEventListener('click', () => { if (selectedIds.has(video.video_id)) selectedIds.delete(video.video_id); else selectedIds.add(video.video_id); renderList(); });
        list.appendChild(item);
      });
      if (!list.children.length) list.appendChild(domText('p', 'empty-state', 'Nenhum vídeo encontrado para este filtro.'));
      selectionNote.textContent = `${selectedIds.size} vídeo(s) selecionado(s)`;
      const visible = filteredVideos();
      selectAllButton.textContent = selectedIds.size === visible.length && visible.length ? 'Desmarcar todos' : 'Selecionar todos';
    };
    [['all', 'Todos'], ['short', 'Shorts'], ['video', 'Vídeos longos']].forEach(([value, label]) => {
      const button = domButton(label, 'list', `autopsy-picker-filter ${value === typeFilter ? 'is-active' : ''}`, 'autopsy-picker-filter-action');
      button.addEventListener('click', () => { typeFilter = value; filters.querySelectorAll('button').forEach(item => item.classList.toggle('is-active', item === button)); renderList(); });
      filters.appendChild(button);
    });
    selectAllButton.addEventListener('click', () => {
      const visible = filteredVideos();
      const allSelected = visible.length > 0 && visible.every(video => selectedIds.has(video.video_id));
      visible.forEach(video => allSelected ? selectedIds.delete(video.video_id) : selectedIds.add(video.video_id));
      renderList();
    });
    panel.appendChild(createElement('div', { className: 'cut-modal-header' }, [domText('h2', '', 'Escolha os vídeos da autópsia'), domButton('Fechar', 'x', 'ghost', 'close-autopsy-picker')]));
    panel.appendChild(domText('p', 'schedule-modal-lead', 'Selecione os vídeos que terão transcrição e análise forense. Você poderá combinar Shorts e vídeos longos.'));
    panel.appendChild(createElement('div', { className: 'autopsy-picker-toolbar' }, [filters, selectAllButton]));
    panel.appendChild(list);
    panel.appendChild(createElement('div', { className: 'autopsy-picker-footer' }, [selectionNote, createElement('div', { className: 'schedule-modal-actions' }, [domButton('Voltar', 'arrow-left', 'secondary', 'close-autopsy-picker'), domButton('Analisar vídeos selecionados', 'play', 'primary', 'confirm-autopsy-picker')])]));
    backdrop.appendChild(panel);
    document.body.appendChild(backdrop);
    panel.addEventListener('click', event => {
      const action = event.target.closest('[data-action]')?.dataset.action;
      if (action === 'close-autopsy-picker') finish(null);
      if (action === 'confirm-autopsy-picker') {
        if (!selectedIds.size) return showToast('Selecione pelo menos um vídeo para prosseguir.');
        finish([...selectedIds]);
      }
    });
    backdrop.addEventListener('click', event => { if (event.target === backdrop) finish(null); });
    renderList();
    refreshIcons();
  });
}
async function startContentAnalysis() {
  try {
    autopsyPickerVideos = await loadAutopsyPickerVideos();
    if (!autopsyPickerVideos.length) return showToast('Este perfil ainda não possui vídeos para analisar.');
    const videoIds = await openAutopsyPicker(autopsyPickerVideos);
    if (!videoIds) return;
    await startContentAnalysisForIds(videoIds);
  } catch (error) {
    showToast(error.message);
  }
}
async function startContentAnalysisForIds(videoIds) {
  const response = await fetch('/api/content-analysis/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ video_ids: videoIds }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível iniciar a análise.');
    contentAnalysisStatus = { ...contentAnalysisStatus, ...payload, status: 'running', progress: 0, message: payload.message || 'Preparando análise de conteúdo' };
    renderAutopsy();
    refreshIcons();
    showToast(`Análise de ${videoIds.length} vídeo(s) iniciada.`);
    pollContentAnalysis();
}
async function analyzeAutopsySelection(videoIds) {
  if (contentAnalysisStatus.status === 'running') return showToast('Já existe uma análise em andamento. Aguarde a conclusão.');
  try {
    await startContentAnalysisForIds(videoIds);
  } catch (error) {
    showToast(error.message);
  }
}
async function pollContentAnalysis() {
  if (contentAnalysisPollActive) return;
  contentAnalysisPollActive = true;
  try {
    const response = await fetch('/api/content-analysis/status');
    const payload = await response.json();
    contentAnalysisStatus = payload;
    updateContentProgress(payload);
    await loadAutopsy();
    if (state.view === 'autopsy') renderAutopsy();
    if (payload.status === 'running') {
      setTimeout(() => {
        contentAnalysisPollActive = false;
        pollContentAnalysis();
      }, 1800);
    } else if (payload.status === 'completed') {
      contentAnalysisPollActive = false;
      await loadAutopsy();
      showToast(`${payload.processed || 0} vídeo(s) analisado(s). Resultados atualizados na Autópsia.`);
    } else if (payload.status === 'failed') {
      contentAnalysisPollActive = false;
      showToast(`Falha na análise: ${payload.message || 'erro desconhecido'}`);
    } else {
      contentAnalysisPollActive = false;
    }
  } catch (error) {
    contentAnalysisPollActive = false;
  }
}
async function loadAutopsy() {
  try {
    const response = await fetch('/api/autopsy');
    if (!response.ok) throw new Error('Autópsia indisponível');
    autopsyData = await response.json();
  } catch (error) {
    autopsyData = { metrics: {}, top_performers: [], flops: [], semantic: {} };
    showToast('Não foi possível carregar os dados da Autópsia.');
  }
  if (state.view === 'autopsy') {
    renderAutopsy();
    refreshIcons();
  }
}
async function selectCutSource(videoId) {
  selectedCutSource = cutSources.find(video => video.id === videoId) || null;
  cutSuggestions = [];
  if (!selectedCutSource) return;
  try {
    const response = await fetch(`/api/transcription?video_id=${encodeURIComponent(videoId)}`);
    selectedCutSource.transcription = response.ok ? await response.json() : null;
  } catch (error) {
    selectedCutSource.transcription = null;
  }
  try {
    const response = await fetch(`/api/cuts?video_id=${encodeURIComponent(videoId)}`, { headers: { 'X-Profile-Id': String(activeProfileId) } });
    persistedCuts = response.ok
      ? ((await response.json()).cortes || []).filter(cut => cut.status !== 'excluido' && String(cut.video_id) === String(videoId))
      : [];
  } catch (error) {
    persistedCuts = [];
  }
  selectedCutSource.contentSummary = { status: 'loading', summary: 'Gerando resumo do conteúdo...' };
  renderCuts();
  loadSelectedContentSummary(videoId);
  await prepareMissingCutDescriptions();
}
async function loadSelectedContentSummary(videoId) {
  try {
    const response = await fetch(`/api/transcription/summary?video_id=${encodeURIComponent(videoId)}`);
    const payload = response.ok ? await response.json() : { status: 'unavailable', summary: 'Resumo de conteúdo indisponível no momento.' };
    if (selectedCutSource?.id === videoId) {
      selectedCutSource.contentSummary = payload;
      renderCuts();
    }
  } catch (error) {
    if (selectedCutSource?.id === videoId) {
      selectedCutSource.contentSummary = { status: 'unavailable', summary: 'Resumo de conteúdo indisponível no momento.' };
      renderCuts();
    }
  }
}
async function prepareMissingCutDescriptions() {
  if (!selectedCutSource?.id) return;
  const cuts = persistedCuts.filter(cut => cut.video_id === selectedCutSource.id && !String(cut.descricao_publicacao || '').trim());
  if (!cuts.length) return;
  try {
    showToast('Gerando descrições editoriais para o YouTube...');
    const response = await fetch('/api/cuts/generate-descriptions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cut_ids: cuts.map(cut => Number(cut.id || cut.cut_id)) }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível gerar as descrições.');
    const descriptions = new Map((payload.generated || []).map(item => [Number(item.cut_id), item.descricao_publicacao]));
    persistedCuts.forEach(cut => { const description = descriptions.get(Number(cut.id || cut.cut_id)); if (description) cut.descricao_publicacao = description; });
    renderCuts();
  } catch (error) {
    showToast('A descrição editorial será gerada quando a IA estiver disponível.');
  }
}
async function reloadSelectedCutData() {
  if (!selectedCutSource?.id) return;
  try {
    const [transcriptionResponse, cutsResponse] = await Promise.all([
      fetch(`/api/transcription?video_id=${encodeURIComponent(selectedCutSource.id)}`),
      fetch(`/api/cuts?video_id=${encodeURIComponent(selectedCutSource.id)}`),
    ]);
    if (transcriptionResponse.ok) selectedCutSource.transcription = await transcriptionResponse.json();
    if (cutsResponse.ok) persistedCuts = ((await cutsResponse.json()).cortes || []).filter(cut => cut.status !== 'excluido');
  } catch (error) {
  }
}
async function generateCutPreview() {
  if (!selectedCutSource) {
    showToast('Selecione um vídeo longo primeiro.');
    return;
  }
  if (!selectedCutSource.transcription?.segments?.length) {
    showToast('Este vídeo ainda não possui transcrição segmentada.');
    return;
  }
  showToast('Qwen analisando os segmentos reais...');
  try {
    const response = await fetch('/api/cuts/suggest', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ video_id: selectedCutSource.id, duracao_minima: cutDurationRange.min, duracao_maxima: cutDurationRange.max }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'falha na sugestão');
    cutJob = { id: payload.job_id, status: 'queued', progress: 0, message: 'Na fila', started_at: Date.now(), perfil_id: activeProfileId };
    rememberActiveJob('cut', cutJob);
    renderCuts();
    pollCutJob();
  } catch (error) {
    showToast(error.message);
  }
}
async function generateEditorial() {
  if (!selectedCutSource) {
    showToast('Selecione um vídeo longo primeiro.');
    return;
  }
  if (!selectedCutSource.transcription?.segments?.length) {
    showToast('Este vídeo ainda não possui transcrição segmentada.');
    return;
  }
  showToast('Gerando somente o Dossiê Editorial...');
  try {
    const response = await fetch('/api/editorial/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ video_id: selectedCutSource.id, duracao_minima: cutDurationRange.min, duracao_maxima: cutDurationRange.max }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível gerar o editorial.');
    cutJob = { id: payload.job_id, kind: 'editorial', status: 'queued', progress: 0, message: 'Editorial na fila', started_at: Date.now(), perfil_id: activeProfileId };
    rememberActiveJob('editorial', cutJob);
    renderCuts();
    pollCutJob();
  } catch (error) {
    showToast(error.message);
  }
}
async function pollCutJob() {
  if (!cutJob) return;
  try {
    const response = await fetch(`/api/jobs/${cutJob.id}`);
    const payload = await response.json();
    cutJob = { ...cutJob, ...payload };
    const hasTargetedCuts = Array.isArray(cutJob.cut_ids || cutJob.cutIds) && (cutJob.cut_ids || cutJob.cutIds).length > 0;
    if (hasTargetedCuts) refreshActiveCutCards();
    else renderCuts();
    if (payload.status === 'completed') {
      forgetActiveJob(cutJob.id);
      if (cutJob.kind === 'captions') {
        await reloadSelectedCutData();
        cutJob = null;
        renderCuts();
        showToast('Legendas geradas.');
        return;
      }
      if (cutJob.kind === 'editorial') {
        const editorialVideoId = selectedCutSource?.id;
        await loadCutSources();
        if (editorialVideoId && cutSources.some(video => String(video.id) === String(editorialVideoId))) await selectCutSource(editorialVideoId);
        cutJob = null;
        renderCuts();
        showToast('Editorial gerado. Gere os cortes quando quiser.');
        return;
      }
      if (String(payload.message || '').includes('YouTube')) {
        cutJob = null;
        await loadScheduled();
        await reloadSelectedCutData();
        renderCuts();
        showToast(payload.message);
        return;
      }
      let persistedResult = {};
      try {
        persistedResult = typeof payload.resultado_json === 'string' ? JSON.parse(payload.resultado_json) : (payload.resultado_json || {});
      } catch (error) {
        persistedResult = {};
      }
      cutSuggestions = payload.suggestions || (Array.isArray(persistedResult) ? persistedResult : persistedResult.cortes) || [];
      const validatedCount = cutSuggestions.length;
      await loadCutSources();
      cutJob = null;
      renderCuts();
      showToast(`${validatedCount} corte(s) validado(s) pela IA.`);
      return;
    }
    if (payload.status === 'needs_review' || payload.status === 'needs_review_fallback') {
      forgetActiveJob(cutJob.id);
      cutSuggestions = payload.suggestions || [];
      cutJob = { ...cutJob, diagnostics: parseJobDiagnostics(payload) };
      await reloadSelectedCutData();
      const persistedCandidates = persistedCuts.filter(cut => cut.status === 'concluido' || cut.status === 'candidato' || cut.status === 'selecionado');
      cutSuggestions = cutSuggestions.length ? cutSuggestions : persistedCandidates.map(cut => ({
        ...cut,
        cut_id: cut.id,
        inicio: Number(cut.inicio_segundos),
        fim: Number(cut.fim_segundos),
        output_path: cut.caminho_saida,
      }));
      renderCuts();
      showToast(payload.message || 'A análise precisa de revisão humana.');
      return;
    }
    if (payload.status === 'failed' || payload.status === 'interrupted' || payload.status === 'cancelled') {
      forgetActiveJob(cutJob.id);
      cutJob = { ...cutJob, ...payload, status: payload.status };
      renderCuts();
      showToast(payload.message || 'O processamento dos cortes foi interrompido.');
      return;
    }
    if (payload.status === 'cancelling') {
      setTimeout(pollCutJob, 1000);
      return;
    }
    setTimeout(pollCutJob, 1000);
  } catch (error) {
    showToast('Não foi possível acompanhar a análise.');
  }
}
async function deleteCut(cutId) {
  if (!cutId) return;
  try {
    const response = await fetch('/api/cuts/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cut_id: cutId }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível excluir o corte.');
    selectedCandidateIds.delete(cutId);
    await reloadSelectedCutData();
    cutSuggestions = cutSuggestions.filter(cut => Number(cut.cut_id || cut.id) !== cutId);
    renderCuts();
    showToast('Corte excluído da fila de revisão.');
  } catch (error) {
    showToast(error.message);
  }
}
function scheduleRecommendationText(cuts) {
  const periods = [...new Set(cuts.map(cut => cut.horario_recomendado?.periodo).filter(Boolean))];
  const days = [...new Set(cuts.flatMap(cut => cut.horario_recomendado?.dias_preferidos || []))].sort((left, right) => left - right);
  const dayNames = ['segundas', 'tercas', 'quartas', 'quintas', 'sextas', 'sabados', 'domingos'];
  if (!periods.length && !days.length) return 'A IA ainda não encontrou sinais suficientes; o canal usará os melhores horários históricos.';
  const dayText = days.length ? `Dias com maior aderência: ${days.map(day => dayNames[day]).join(', ')}.` : '';
  const periodText = periods.length ? `Período sugerido: ${periods.join(' / ')}.` : '';
  return `${periodText} ${dayText}`.trim();
}
function openPublishChoiceDialog(count) {
  return new Promise(resolve => {
    const backdrop = createElement('div', { className: 'cut-modal-backdrop publish-choice-backdrop' });
    const panel = createElement('section', { className: 'cut-modal publish-choice-modal', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'publish-choice-title' });
    let choice = 'immediate';
    const options = createElement('div', { className: 'publish-choice-options' });
    let finish = value => { backdrop.remove(); resolve(value); };
    const updateChoice = value => {
      choice = value;
      options.querySelectorAll('.publish-choice-option').forEach(option => option.classList.toggle('is-active', option.dataset.choice === value));
    };
    [['immediate', 'Postar imediatamente', 'Publicar os cortes agora, um por vez.'], ['schedule', 'Agendar publicação', 'Escolher data e horário ou usar os melhores horários do canal.']].forEach(([value, title, description]) => {
      const option = createElement('button', { type: 'button', className: `publish-choice-option ${value === choice ? 'is-active' : ''}`, 'data-choice': value }, [
        createElement('span', { className: 'publish-choice-radio' }),
        createElement('span', {}, [createElement('strong', { textContent: title }), createElement('small', { textContent: description })]),
      ]);
      option.addEventListener('click', () => updateChoice(value));
      options.appendChild(option);
    });
    panel.appendChild(createElement('div', { className: 'cut-modal-header' }, [domText('h2', '', 'Como deseja publicar?'), domButton('Fechar', 'x', 'ghost', 'close-publish-choice')]));
    panel.appendChild(domText('p', 'schedule-modal-lead', `${count} corte(s) selecionado(s). Escolha o modo de publicação para continuar.`));
    panel.appendChild(options);
    panel.appendChild(createElement('div', { className: 'schedule-modal-actions' }, [domButton('Cancelar', 'x', 'secondary', 'close-publish-choice'), domButton('OK', 'check', 'primary', 'confirm-publish-choice')]));
    backdrop.appendChild(panel);
    document.body.appendChild(backdrop);
    panel.addEventListener('click', event => {
      const action = event.target.closest('[data-action]')?.dataset.action;
      if (action === 'close-publish-choice') finish(null);
      if (action === 'confirm-publish-choice') finish(choice);
    });
    backdrop.addEventListener('click', event => { if (event.target === backdrop) finish(null); });
    refreshIcons();
  });
}
async function openRelatedVideoPicker(suggestedId = '') {
  let videos = [];
  try {
    const response = await fetch(`/api/youtube/related-videos?initial=${Date.now()}`, { cache: 'no-store', headers: { 'X-Profile-Id': String(activeProfileId) } });
    if (!response.ok) throw new Error('Não foi possível carregar os vídeos do canal.');
    videos = (await response.json()).videos || [];
  } catch (error) {
    showToast(error.message);
    return null;
  }
  return new Promise(resolve => {
    let selectedId = suggestedId;
    const backdrop = createElement('div', { className: 'cut-modal-backdrop related-video-backdrop' });
    const panel = createElement('section', { className: 'cut-modal related-video-modal', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'related-video-title' });
    const search = createElement('input', { type: 'search', className: 'related-video-search', placeholder: 'Pesquisar pelo título do vídeo...' });
    const syncStatus = domText('span', 'related-video-sync-status', 'Verificando vídeos do canal...');
    let syncPoll = null;
    let refreshPoll = null;
    let typeFilter = 'all';
    const filters = createElement('div', { className: 'related-video-filters', role: 'tablist', 'aria-label': 'Filtrar vídeos' });
    const list = createElement('div', { className: 'related-video-list' });
    const noRelatedId = '__no_related_video__';
    const renderList = () => {
      const query = search.value.trim().toLocaleLowerCase();
      clearElement(list);
      if (!query && typeFilter === 'all') {
        const noRelatedItem = createElement('button', { type: 'button', className: `related-video-item related-video-none ${selectedId === noRelatedId ? 'is-selected' : ''}`, 'data-video-id': noRelatedId }, [
          createElement('span', { className: 'related-video-thumb related-video-none-icon' }, [domIcon('unlink')]),
          createElement('span', {}, [createElement('strong', { textContent: 'Nenhum vídeo relacionado' }), createElement('small', { textContent: 'Publicar sem vincular outro vídeo' })]),
        ]);
        noRelatedItem.addEventListener('click', () => { selectedId = noRelatedId; renderList(); });
        list.appendChild(noRelatedItem);
      }
      videos.filter(video => (typeFilter === 'all' || video.tipo === typeFilter) && (!query || String(video.titulo || '').toLocaleLowerCase().includes(query))).forEach(video => {
        const item = createElement('button', { type: 'button', className: `related-video-item ${selectedId === video.video_id ? 'is-selected' : ''}`, 'data-video-id': video.video_id }, [
          createElement('span', { className: 'related-video-thumb' }, [createVideoThumbnail(video, true), domText('b', '', video.tipo === 'short' ? 'S' : 'V')]),
          createElement('span', {}, [createElement('strong', { textContent: video.titulo }), createElement('small', { textContent: `${video.tipo === 'short' ? 'Short' : 'Vídeo normal'} · ${video.status || 'disponível'}` })]),
        ]);
        item.addEventListener('click', () => { selectedId = video.video_id; renderList(); });
        list.appendChild(item);
      });
      if (!list.children.length) list.appendChild(domText('p', 'empty-state', 'Nenhum vídeo encontrado.'));
    };
    let finish = value => { backdrop.remove(); resolve(value); };
    const reloadVideos = async () => {
      try {
        const response = await fetch(`/api/youtube/related-videos?refresh=${Date.now()}`, { cache: 'no-store', headers: { 'X-Profile-Id': String(activeProfileId) } });
        if (!response.ok) throw new Error('Não foi possível atualizar os vídeos.');
        videos = (await response.json()).videos || [];
        renderList();
      } catch (error) {
        syncStatus.textContent = error.message;
      }
    };
    const syncChannel = async () => {
      refreshButton.disabled = true;
      syncStatus.textContent = 'Atualizando vídeos do canal...';
      try {
        const response = await fetch('/api/sync', { method: 'POST', headers: { 'X-Profile-Id': String(activeProfileId) } });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || 'Não foi possível sincronizar o canal.');
        if (syncPoll) clearInterval(syncPoll);
        const poll = async () => {
          const statusResponse = await fetch('/api/sync/status', { headers: { 'X-Profile-Id': String(activeProfileId) } });
          const status = await statusResponse.json();
          syncStatus.textContent = status.status === 'running' ? `Atualizando vídeos... ${status.progress || 0}%` : status.status === 'failed' ? (status.message || 'Falha ao atualizar vídeos.') : (status.message || 'Vídeos atualizados agora.');
          if (status.status !== 'running') {
            if (syncPoll) clearInterval(syncPoll);
            syncPoll = null;
            refreshButton.disabled = false;
            if (status.status === 'completed') await reloadVideos();
          }
        };
        await poll();
        const currentStatus = await (await fetch('/api/sync/status', { headers: { 'X-Profile-Id': String(activeProfileId) } })).json();
        if (currentStatus.status === 'running') syncPoll = setInterval(poll, 2500);
      } catch (error) {
        refreshButton.disabled = false;
        syncStatus.textContent = error.message;
      }
    };
    const refreshButton = domButton('Atualizar agora', 'refresh-cw', 'secondary', 'refresh-related-videos');
    panel.appendChild(createElement('div', { className: 'cut-modal-header' }, [domText('h2', '', 'Vídeo relacionado'), domButton('Fechar', 'x', 'ghost', 'close-related-video')]));
    panel.appendChild(domText('p', 'schedule-modal-lead', 'Escolha um vídeo já publicado do canal para relacionar ao Short.'));
    panel.appendChild(createElement('div', { className: 'related-video-toolbar' }, [syncStatus, refreshButton]));
    panel.appendChild(search);
    [['all', 'Todos os vídeos'], ['short', 'Somente Shorts'], ['video', 'Vídeos normais']].forEach(([value, label]) => {
      const filter = domButton(label, value === 'all' ? 'list' : value === 'short' ? 'smartphone' : 'youtube', `related-filter ${value === typeFilter ? 'is-active' : ''}`, `filter-related-${value}`);
      filter.setAttribute('role', 'tab');
      filter.addEventListener('click', () => { typeFilter = value; filters.querySelectorAll('button').forEach(button => button.classList.toggle('is-active', button === filter)); renderList(); });
      filters.appendChild(filter);
    });
    panel.appendChild(filters);
    panel.appendChild(list);
    panel.appendChild(createElement('div', { className: 'schedule-modal-actions' }, [domButton('Cancelar', 'x', 'secondary', 'close-related-video'), domButton('Confirmar escolha', 'check', 'primary', 'confirm-related-video')]));
    backdrop.appendChild(panel);
    document.body.appendChild(backdrop);
    search.addEventListener('input', renderList);
    panel.addEventListener('click', event => {
      const action = event.target.closest('[data-action]')?.dataset.action;
      if (action === 'close-related-video') finish(null);
      if (action === 'confirm-related-video') finish(selectedId === noRelatedId ? { no_related_video: true } : videos.find(video => video.video_id === selectedId) || null);
      if (action === 'refresh-related-videos') syncChannel();
    });
    backdrop.addEventListener('click', event => { if (event.target === backdrop) finish(null); });
    refreshPoll = setInterval(reloadVideos, 15000);
    const originalFinish = finish;
    finish = value => { if (syncPoll) clearInterval(syncPoll); if (refreshPoll) clearInterval(refreshPoll); originalFinish(value); };
    renderList();
    refreshIcons();
    syncChannel();
  });
}
async function saveRelatedVideoForCuts(cutIds, relatedVideo) {
  if (!relatedVideo) return;
  for (const cutId of cutIds) {
    const body = relatedVideo.no_related_video ? { cut_id: cutId, no_related_video: true } : { cut_id: cutId, video_id: relatedVideo.video_id, video_title: relatedVideo.titulo };
    const response = await fetch('/api/cuts/related-video', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!response.ok) throw new Error('Não foi possível salvar o vídeo relacionado.');
  }
  await loadNotifications();
  showToast(relatedVideo.no_related_video ? `${cutIds.length} corte(s) serão publicados sem vídeo relacionado.` : `Vídeo relacionado salvo para ${cutIds.length} corte(s).`);
}
function openScheduleDialog(cutIds, label) {
  const cuts = allReviewCuts().filter(cut => cutIds.includes(Number(cut.cut_id || cut.id)));
  return new Promise(resolve => {
    const backdrop = createElement('div', { className: 'cut-modal-backdrop schedule-modal-backdrop' });
    const panel = createElement('section', { className: 'cut-modal schedule-modal', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'schedule-modal-title' });
    const close = domButton('Fechar', 'x', 'ghost', 'close-schedule-dialog');
    panel.appendChild(createElement('div', { className: 'cut-modal-header' }, [domText('h2', '', `Agendar ${label}`), close]));
    panel.appendChild(domText('p', 'schedule-modal-lead', `${cuts.length} corte(s) selecionado(s). O horário recomendado será calculado individualmente para cada vídeo.`));
    const recommendation = createElement('div', { className: 'schedule-recommendation' }, [
      createElement('div', { className: 'schedule-recommendation-icon' }, [createElement('i', { 'data-lucide': 'sparkles' })]),
      createElement('div', {}, [domText('strong', '', 'Recomendação da IA'), domText('p', '', scheduleRecommendationText(cuts))]),
    ]);
    panel.appendChild(recommendation);
    const mode = createElement('div', { className: 'schedule-mode' });
    const recommendedId = `schedule-recommended-${Date.now()}`;
    const manualId = `schedule-manual-${Date.now()}`;
    mode.appendChild(createElement('label', { className: 'schedule-mode-option is-active' }, [
      createElement('input', { type: 'radio', name: 'schedule-mode', value: 'recommended', id: recommendedId, checked: 'checked' }),
      createElement('span', {}, [domText('strong', '', 'Usar melhor horário recomendado'), domText('small', '', 'A IA escolhe o melhor dia e horário para cada corte')]),
    ]));
    mode.appendChild(createElement('label', { className: 'schedule-mode-option' }, [
      createElement('input', { type: 'radio', name: 'schedule-mode', value: 'manual', id: manualId }),
      createElement('span', {}, [domText('strong', '', 'Definir data e horário'), domText('small', '', 'Aplicar o mesmo horário aos cortes selecionados')]),
    ]));
    panel.appendChild(mode);
    const localDateTime = new Date(Date.now() + 60 * 60 * 1000);
    localDateTime.setMinutes(Math.ceil(localDateTime.getMinutes() / 30) * 30, 0, 0);
    const localDateTimeValue = new Date(localDateTime.getTime() - localDateTime.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    const recommendedFields = createElement('div', { className: 'schedule-manual-fields' }, [
      createElement('label', {}, [domText('span', '', 'Considerar melhores horários a partir de'), createElement('input', { type: 'datetime-local', name: 'schedule-start-at', min: localDateTimeValue, value: localDateTimeValue })]),
    ]);
    panel.appendChild(recommendedFields);
    const manualFields = createElement('div', { className: 'schedule-manual-fields', hidden: 'hidden' }, [
      createElement('label', {}, [domText('span', '', 'Data'), createElement('input', { type: 'date', name: 'schedule-date', min: new Date().toISOString().slice(0, 10) })]),
      createElement('label', {}, [domText('span', '', 'Horário'), createElement('input', { type: 'time', name: 'schedule-time', value: '17:30' })]),
    ]);
    panel.appendChild(manualFields);
    let relatedVideo = null;
    const relatedLabel = domText('p', 'related-video-selection', 'Nenhum vídeo relacionado escolhido.');
    const relatedButton = domButton('Escolher vídeo relacionado', 'link', 'secondary', 'choose-related-video');
    panel.append(relatedButton, relatedLabel);
    const actions = createElement('div', { className: 'schedule-modal-actions' }, [domButton('Cancelar', 'x', 'secondary', 'close-schedule-dialog'), domButton('Confirmar agendamento', 'calendar-check', 'primary', 'confirm-schedule-dialog')]);
    panel.appendChild(actions);
    backdrop.appendChild(panel);
    document.body.appendChild(backdrop);
    refreshIcons();
    const finish = value => { backdrop.remove(); resolve(value); };
    panel.querySelectorAll('input[name="schedule-mode"]').forEach(input => input.addEventListener('change', event => {
      const isManual = event.target.value === 'manual';
      manualFields.hidden = !isManual;
      recommendedFields.hidden = isManual;
      panel.querySelectorAll('.schedule-mode-option').forEach(option => option.classList.toggle('is-active', option.querySelector('input') === event.target));
    }));
    backdrop.addEventListener('click', event => { if (event.target === backdrop) finish(null); });
    panel.addEventListener('click', event => {
      const action = event.target.closest('[data-action]')?.dataset.action;
      if (action === 'close-schedule-dialog') finish(null);
      if (action === 'choose-related-video') openRelatedVideoPicker(cuts[0]?.video_id).then(video => { if (video) { relatedVideo = video; relatedLabel.textContent = `Relacionado: ${video.titulo}`; } });
      if (action === 'confirm-schedule-dialog') {
        const isManual = panel.querySelector('input[name="schedule-mode"]:checked')?.value === 'manual';
        const date = panel.querySelector('[name="schedule-date"]')?.value || '';
        const time = panel.querySelector('[name="schedule-time"]')?.value || '';
        const startAt = panel.querySelector('[name="schedule-start-at"]')?.value || '';
        if (isManual && (!date || !time)) return showToast('Escolha a data e o horário para continuar.');
        if (!isManual && !startAt) return showToast('Escolha a data e hora inicial para a recomendação da IA.');
        finish({ ...(isManual ? { date, time } : { start_at: startAt }), related_video: relatedVideo });
      }
    });
  });
}
async function scheduleCut(cutId) {
  const schedule = await openScheduleDialog([Number(cutId)], 'este corte');
  if (!schedule) return;
  try {
    await saveRelatedVideoForCuts([Number(cutId)], schedule.related_video);
    const response = await fetch('/api/cuts/schedule', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cut_id: cutId, ...schedule }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível agendar o corte.');
    showToast(`Corte agendado para ${payload.date} às ${payload.time}.`);
    await loadScheduled();
    await reloadSelectedCutData();
    renderCuts();
  } catch (error) {
    showToast(error.message);
  }
}
async function scheduleCuts(cutIds, label = 'cortes selecionados', automatic = false) {
  const ids = [...new Set(cutIds.map(Number).filter(Boolean))];
  if (!ids.length) return showToast(`Selecione pelo menos um corte para ${label}.`);
  const schedule = automatic ? {} : await openScheduleDialog(ids, label);
  if (!schedule) return;
  try {
    await saveRelatedVideoForCuts(ids, schedule.related_video);
    const response = await fetch('/api/cuts/schedule-bulk', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cut_ids: ids, ...schedule }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível agendar os cortes.');
    cutJob = { id: payload.job_id, kind: 'publish', status: 'queued', progress: 0, message: 'Publicação na fila', cut_ids: ids };
    rememberActiveJob('cut', cutJob);
    showToast(`${label} enviados para publicação. Acompanhe a confirmação na Central.`);
    renderCuts();
    pollCutJob();
  } catch (error) { showToast(error.message); }
}
async function postSelectedCuts() {
  const ids = [...selectedCandidateIds].filter(Boolean);
  if (!ids.length) return showToast('Selecione pelo menos um corte para postar.');
  const unavailable = ids.filter(id => {
    const cut = allReviewCuts().find(item => Number(item.cut_id || item.id) === id);
    return !cut || cut.status !== 'concluido' || !(cut.output_path || cut.caminho_saida);
  });
  if (unavailable.length) return showToast(`${unavailable.length} corte(s) precisam ser renderizados antes da postagem.`);
  const publishMode = await openPublishChoiceDialog(ids.length);
  if (!publishMode) return;
  if (publishMode === 'schedule') return scheduleCuts(ids, 'cortes selecionados');
  const relatedVideo = await openRelatedVideoPicker(allReviewCuts().find(cut => Number(cut.cut_id || cut.id) === ids[0])?.video_id || '');
  try {
    await saveRelatedVideoForCuts(ids, relatedVideo);
    const response = await fetch('/api/cuts/publish-now-bulk', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cut_ids: ids }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível iniciar a postagem.');
    cutJob = { id: payload.job_id, kind: 'publish-now', status: 'queued', progress: 0, message: 'Postagem imediata na fila', cut_ids: ids };
    rememberActiveJob('cut', cutJob);
    selectedCandidateIds.clear();
    renderCuts();
    showToast(`Postagem iniciada. Job ${payload.job_id.slice(0, 8)}; acompanhe o sino de notificações.`);
    pollCutJob();
  } catch (error) { showToast(error.message); }
}
async function saveCutMetadata(cutId) {
  const title = document.querySelector('#cut-edit-title')?.value.trim() || '';
  const description = document.querySelector('#cut-edit-description')?.value.trim() || '';
  try {
    const response = await fetch('/api/cuts/metadata', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cut_id: cutId, title, description }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível salvar os metadados.');
    [...persistedCuts, ...cutSuggestions].forEach(cut => {
      if (Number(cut.cut_id || cut.id) === cutId) {
        cut.titulo = payload.titulo;
        cut.descricao_publicacao = payload.descricao_publicacao;
      }
    });
    closeCutEditor();
    renderCuts();
    showToast('Título e descrição atualizados.');
  } catch (error) { showToast(error.message); }
}
async function regenerateCutMetadata(cutId, field, button) {
  const label = field === 'title' ? 'título' : 'descrição';
  const operation = { status: 'running', progress: 0, message: `Gerando ${label}...`, started_at: Date.now(), cancelable: false };
  activeCutOperations.set(cutId, operation);
  renderCuts();
  if (button) { button.disabled = true; button.classList.add('is-loading'); }
  showToast(`Gerando ${label} com a transcrição do corte...`);
  try {
    const response = await fetch('/api/cuts/regenerate-metadata', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cut_id: cutId, field }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `Não foi possível regenerar o ${label}.`);
    const target = field === 'title' ? document.querySelector('#cut-edit-title') : document.querySelector('#cut-edit-description');
    if (target) target.value = payload.value || '';
    [...persistedCuts, ...cutSuggestions].forEach(cut => {
      if (Number(cut.cut_id || cut.id) === cutId) cut[field === 'title' ? 'titulo' : 'descricao_publicacao'] = payload.value || '';
    });
    if (!target) renderCuts();
    showToast(`${label[0].toUpperCase()}${label.slice(1)} regenerado.`);
  } catch (error) { showToast(error.message); }
  finally {
    activeCutOperations.delete(cutId);
    if (button) { button.disabled = false; button.classList.remove('is-loading'); }
    renderCuts();
  }
}
async function deleteSelectedCuts() {
  const ids = [...selectedCandidateIds].filter(Boolean);
  if (!ids.length) return showToast('Selecione pelo menos um corte para excluir.');
  if (!confirm(`Excluir ${ids.length} corte(s) selecionado(s)?`)) return;
  try {
    for (const cutId of ids) {
      const response = await fetch('/api/cuts/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cut_id: cutId }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Não foi possível excluir os cortes selecionados.');
    }
    selectedCandidateIds.clear();
    await reloadSelectedCutData();
    cutSuggestions = cutSuggestions.filter(cut => !ids.includes(Number(cut.cut_id || cut.id)));
    renderCuts();
    showToast(`${ids.length} corte(s) excluído(s).`);
  } catch (error) { showToast(error.message); }
}
function updateSelectedCutsToolbar() {
  const toolbar = document.querySelector('#selected-cuts-toolbar');
  if (!toolbar) return;
  const count = selectedCandidateIds.size;
  toolbar.hidden = count === 0;
  const label = toolbar.querySelector('.selected-cuts-count');
  if (label) label.textContent = `${count} selecionado${count === 1 ? '' : 's'}`;
}
function syncSelectionButtons() {
  document.querySelectorAll('[data-action="candidate-toggle-button"]').forEach(selectionButton => {
    const selected = selectedCandidateIds.has(Number(selectionButton.dataset.cutId));
    selectionButton.classList.toggle('selected', selected);
    selectionButton.classList.toggle('secondary', !selected);
    selectionButton.setAttribute('aria-pressed', String(selected));
    selectionButton.setAttribute('aria-label', selected ? 'Remover da seleção para postagem' : 'Selecionar para postagem');
    selectionButton.title = selected ? 'Remover da seleção para postagem' : 'Selecionar para postagem';
    clearElement(selectionButton);
    selectionButton.append(domIcon(selected ? 'circle-check' : 'circle'), selected ? 'Selecionado' : 'Postar');
  });
  refreshIcons();
  updateSelectedCutsToolbar();
  updateCycleSelectionButtons();
}
function updateCycleSelectionButtons() {
  document.querySelectorAll('[data-action="select-cycle-cuts"]').forEach(button => {
    const cycleIds = button.dataset.cutIds.split(',').map(Number).filter(Boolean);
    const selected = cycleIds.length > 0 && cycleIds.every(cutId => selectedCandidateIds.has(cutId));
    button.setAttribute('aria-pressed', String(selected));
    button.setAttribute('aria-label', selected ? 'Desselecionar todos deste ciclo' : 'Selecionar todos deste ciclo');
    button.title = selected ? 'Desselecionar todos deste ciclo' : 'Selecionar todos deste ciclo';
    clearElement(button);
    button.append(domIcon(selected ? 'check-check' : 'check-check'), selected ? 'Desselecionar todos' : 'Selecionar todos');
  });
  document.querySelectorAll('[data-action="caption-cycle-cuts"]').forEach(button => {
    const cycleIds = button.dataset.allCutIds.split(',').map(Number).filter(Boolean);
    const selectedIds = cycleIds.filter(cutId => selectedCandidateIds.has(cutId));
    button.dataset.cutIds = selectedIds.join(',');
    button.hidden = selectedIds.length < 2;
  });
  refreshIcons();
}
function toggleCycleCuts(cuts) {
  const selectableCuts = cuts.filter(cut => ['candidato', 'concluido', 'selecionado'].includes(cut.status || 'candidato'));
  const cycleIds = selectableCuts.map(cut => Number(cut.cut_id || cut.id)).filter(Boolean);
  const shouldDeselect = cycleIds.length > 0 && cycleIds.every(cutId => selectedCandidateIds.has(cutId));
  cycleIds.forEach(cutId => {
    if (shouldDeselect) selectedCandidateIds.delete(cutId);
    else selectedCandidateIds.add(cutId);
  });
  syncSelectionButtons();
  updateCycleSelectionButtons();
}
async function renderSelectedCuts() {
  const cutIds = [...selectedCandidateIds];
  if (!cutIds.length) return showToast('Selecione pelo menos um candidato para renderizar.');
  try {
    const selectResponse = await fetch('/api/cuts/select', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cut_ids: cutIds }) });
    if (!selectResponse.ok) throw new Error((await selectResponse.json()).error || 'Não foi possível salvar a seleção.');
    const response = await fetch('/api/cuts/render-selected', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cut_ids: cutIds }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível iniciar a renderização.');
    cutJob = { id: payload.job_id, status: 'queued', progress: 0, message: 'Renderização aprovada na fila', cut_ids: cutIds };
    rememberActiveJob('cut', cutJob);
    renderCuts();
    pollCutJob();
  } catch (error) {
    showToast(error.message);
  }
}
async function renderSingleCut(cutId) {
  selectedCandidateIds.add(cutId);
  await renderSelectedCuts();
}
function openCaptionDialog(cut, selectedCuts = [cut]) {
  const modal = createElement('div', { className: 'cut-modal-backdrop caption-modal-backdrop' });
  const panel = createElement('section', { className: 'cut-modal cut-metadata-modal', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'caption-modal-title' });
  const availableCaptionStyles = captionGallery.length ? captionGallery : [
    { style_id: 'clean', name: 'Clean', style: 'clean', font: 'Arial', size: 54, position: 'bottom', stroke_color: 'black', stroke_size: 3 },
    { style_id: 'bold', name: 'Bold', style: 'bold', font: 'Arial', size: 60, position: 'bottom', stroke_color: 'black', stroke_size: 4 },
    { style_id: 'highlight', name: 'Highlight', style: 'highlight', font: 'Arial', size: 56, position: 'bottom', stroke_color: 'black', stroke_size: 3, animation: 'karaoke' },
  ];
  const style = createElement('select', { id: 'caption-style-select' }, [
    ...availableCaptionStyles.map(item => createElement('option', { value: item.style_id, selected: item.style_id === captionDefaults.style ? 'true' : null }, captionStyleLabel(item))),
  ]);
  const font = createElement('select', { id: 'caption-font-select' }, captionFonts.map(name => createElement('option', { value: name, selected: captionDefaults.font === name ? 'true' : null }, name)));
  const size = createElement('input', { id: 'caption-size-select', type: 'range', min: '32', max: '160', step: '1', value: String(captionDefaults.size), 'aria-label': 'Tamanho da legenda' });
  const sizeNumber = createElement('input', { id: 'caption-size-number', type: 'number', min: '32', max: '160', step: '1', value: String(captionDefaults.size), 'aria-label': 'Tamanho da legenda em pixels' });
  const sizeValue = domText('output', 'caption-size-value', `${captionDefaults.size}px`);
  const singleLine = createElement('input', { id: 'caption-single-line-select', type: 'checkbox', checked: captionDefaults.singleLine ? 'true' : null, 'aria-label': 'Usar uma linha' });
  const position = createElement('select', { id: 'caption-position-select' }, [
    createElement('option', { value: 'bottom', selected: captionDefaults.position === 'bottom' ? 'true' : null }, 'Embaixo'),
    createElement('option', { value: 'center', selected: captionDefaults.position === 'center' ? 'true' : null }, 'Centro'),
    createElement('option', { value: 'top', selected: captionDefaults.position === 'top' ? 'true' : null }, 'Em cima'),
  ]);
  const strokeColor = createElement('select', { id: 'caption-stroke-color-select' }, [
    ['#000000', 'Preto'], ['#FFFFFF', 'Branco'], ['#FF4B5B', 'Coral'],
  ].map(([value, label]) => createElement('option', { value, selected: captionDefaults.strokeColor === value ? 'true' : null }, label)));
  const strokeSize = createElement('select', { id: 'caption-stroke-size-select' }, [0, 1, 2, 3, 4, 6, 8].map(value => createElement('option', { value: String(value), selected: value === captionDefaults.strokeSize ? 'true' : null }, `${value}px`)));
  const primaryColorControl = createCaptionColorControl({ id: 'caption-primary-color-select', type: 'color', value: captionDefaults.primaryColor });
  const highlightColorControl = createCaptionColorControl({ id: 'caption-highlight-color-select', type: 'color', value: captionDefaults.highlightColor });
  const backgroundColorControl = createCaptionColorControl({ id: 'caption-background-color-select', type: 'color', value: captionDefaults.backgroundColor });
  const primaryColor = primaryColorControl.input;
  const highlightColor = highlightColorControl.input;
  const backgroundColor = backgroundColorControl.input;
  const backgroundAlpha = createElement('input', { id: 'caption-background-alpha-select', type: 'range', min: '0', max: '100', step: '5', value: String(captionDefaults.backgroundAlpha) });
  const backgroundAlphaNumber = createElement('input', { id: 'caption-background-alpha-number', type: 'number', min: '0', max: '100', step: '1', value: String(captionDefaults.backgroundAlpha), 'aria-label': 'Opacidade do fundo em porcentagem' });
  const previewStage = createElement('div', { className: 'caption-preview-stage', role: 'img', 'aria-label': 'Preview da legenda' });
  const previewText = domText('span', 'caption-preview-text', 'A cidade muda quando a gente participa.');
  previewStage.appendChild(previewText);
  const applyPreviewPosition = setupCaptionPreview(previewStage, previewText, cut, position);
  const previewStyles = {
    clean: { color: '#ffffff', weight: '400', shadow: '0 2px 3px rgba(0, 0, 0, .95)', transform: 'none' },
    bold: { color: '#ffffff', weight: '800', shadow: '0 3px 0 #101010, 2px 0 0 #101010, -2px 0 0 #101010, 0 -2px 0 #101010', transform: 'none' },
    highlight: { color: '#ffe45c', weight: '800', shadow: '0 3px 0 #101010, 2px 0 0 #101010, -2px 0 0 #101010, 0 -2px 0 #101010', transform: 'none' },
  };
  const strokeColors = { black: '#000000', white: '#ffffff', coral: '#ff4b5b' };
  const updatePreview = () => {
    const selectedStyle = availableCaptionStyles.find(item => item.style_id === style.value);
    const preset = previewStyles[selectedStyle?.style || style.value] || previewStyles.clean;
    previewText.style.fontFamily = `'${font.value}', sans-serif`;
    const scale = captionPreviewScale(previewStage);
    previewText.style.fontSize = `${Number(size.value) * scale}px`;
    fitSingleLineCaption(previewStage, previewText, Number(size.value) * scale);
    sizeNumber.value = size.value;
    backgroundAlphaNumber.value = backgroundAlpha.value;
    sizeValue.textContent = `${size.value}px`;
    previewText.style.fontWeight = preset.weight;
    previewText.style.whiteSpace = singleLine.checked ? 'nowrap' : 'normal';
    previewText.style.maxWidth = singleLine.checked ? 'none' : '88%';
    previewText.style.color = primaryColor.value || preset.color;
    const stroke = Number(strokeSize.value);
    const strokeColorValue = captionColorValue(strokeColor.value);
    const scaledStroke = stroke * scale;
    const scaledShadow = scaleCaptionShadow(preset.shadow, scale);
    previewText.style.textShadow = stroke ? `0 ${scaledStroke}px 0 ${strokeColorValue}, ${scaledStroke}px 0 0 ${strokeColorValue}, -${scaledStroke}px 0 0 ${strokeColorValue}, 0 -${scaledStroke}px 0 ${strokeColorValue}, ${scaledShadow}` : scaledShadow;
    applyPreviewPosition(position.value, previewText.dataset.positionY, previewText.dataset.positionX);
    previewStage.style.justifyContent = 'center';
    previewStage.style.alignItems = 'center';
    previewText.dataset.style = style.value;
  };
  style.addEventListener('change', () => {
    const selectedStyle = availableCaptionStyles.find(item => item.style_id === style.value);
    if (selectedStyle) {
      font.value = selectedStyle.font;
      size.value = String(Math.min(160, selectedStyle.size));
      singleLine.checked = Boolean(selectedStyle.uma_linha);
      position.value = selectedStyle.position;
      strokeColor.value = captionColorValue(selectedStyle.stroke_color);
      strokeSize.value = String(selectedStyle.stroke_size);
      primaryColor.value = selectedStyle.primary_color || primaryColor.value;
      highlightColor.value = selectedStyle.highlight_color || highlightColor.value;
      backgroundColor.value = selectedStyle.background_color || backgroundColor.value;
      backgroundAlpha.value = String(selectedStyle.background_alpha ?? backgroundAlpha.value);
    }
    updatePreview();
  });
  [style, font, size, sizeNumber, position, singleLine, strokeColor, strokeSize, primaryColor, highlightColor, backgroundColor, backgroundAlpha, backgroundAlphaNumber].forEach(control => control.addEventListener('change', updatePreview));
  size.addEventListener('input', updatePreview);
  sizeNumber.addEventListener('input', () => { size.value = sizeNumber.value; updatePreview(); });
  backgroundAlphaNumber.addEventListener('input', () => { backgroundAlpha.value = backgroundAlphaNumber.value; updatePreview(); });
  backgroundAlpha.addEventListener('input', () => { backgroundAlphaNumber.value = backgroundAlpha.value; updatePreview(); });
  previewStage.addEventListener('caption-preview-resize', updatePreview);
  position.addEventListener('change', () => { delete previewText.dataset.positionX; delete previewText.dataset.positionY; updatePreview(); });
  updatePreview();
  const close = domButton('Fechar', 'x', 'secondary', 'close-caption-dialog');
  panel.appendChild(createElement('div', { className: 'cut-modal-header' }, [domText('h2', '', 'Gerar legendas'), close]));
  panel.appendChild(domText('p', 'schedule-modal-lead', 'O vídeo original será preservado e uma nova versão será criada.'));
  const captionQuickSettings = createElement('div', { className: 'caption-settings-grid caption-quick-settings' }, [
    createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Estilo'), style]),
    createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Tamanho'), size, createElement('div', { className: 'caption-number-control' }, [sizeNumber, sizeValue])]),
    createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Posição'), position]),
    createElement('label', { className: 'cut-metadata-field caption-checkbox-field' }, [singleLine, domText('span', '', 'Uma linha')]),
    createElement('div', { className: 'caption-position-actions' }, [domButton('Centralizar legenda', 'crosshair', 'secondary', 'caption-center-preview'), domButton('Centralizar horizontalmente', 'move-horizontal', 'secondary', 'caption-center-horizontal')]),
  ]);
  const captionAdvancedSettings = createElement('details', { className: 'caption-advanced-settings' }, [
    createElement('summary', {}, [domText('span', '', 'Ajustes avançados'), domText('small', '', 'Fonte, contorno e cores')]),
    createElement('div', { className: 'caption-settings-grid' }, [
      createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Fonte'), font]),
    createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Cor do stroke'), strokeColor]),
    createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Espessura do stroke'), strokeSize]),
    createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Cor base'), primaryColorControl.control]),
    createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Cor destaque'), highlightColorControl.control]),
    createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Cor do fundo'), backgroundColorControl.control]),
    createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Opacidade do fundo'), backgroundAlpha, createElement('div', { className: 'caption-number-control' }, [backgroundAlphaNumber, domText('span', '', '%')])]),
    ]),
  ]);
  panel.appendChild(createElement('div', { className: 'caption-preview-block' }, [domText('strong', '', 'Veja como vai ficar'), previewStage]));
  panel.appendChild(captionQuickSettings);
  panel.appendChild(captionAdvancedSettings);
  panel.appendChild(createElement('div', { className: 'caption-transcript-action' }, [domButton('Ler transcrição do corte', 'file-text', 'secondary', 'read-cut-transcript', { 'data-cut-id': Number(cut.cut_id || cut.id) })]));
  const cutIds = selectedCuts.map(item => Number(item.cut_id || item.id)).filter(Boolean);
  panel.appendChild(createElement('div', { className: 'schedule-modal-actions' }, [domButton('Cancelar', 'x', 'secondary', 'close-caption-dialog'), domButton(cutIds.length > 1 ? `Gerar ${cutIds.length} legendas` : 'Gerar legendas', 'captions', 'lime', 'generate-captions', { 'data-cut-ids': cutIds.join(',') })]));
  modal.appendChild(panel);
  document.body.appendChild(modal);
  modal.addEventListener('click', event => { if (event.target === modal) modal.remove(); });
}
function formatCutTranscriptTime(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
}
async function openCutTranscriptReader(cut) {
  document.querySelector('.cut-transcript-reader-backdrop')?.remove();
  const modal = createElement('div', { className: 'cut-modal-backdrop cut-transcript-reader-backdrop' });
  const panel = createElement('section', { className: 'cut-modal cut-transcript-reader', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'cut-transcript-reader-title' });
  const close = domButton('Fechar', 'x', 'secondary', 'close-cut-transcript');
  const content = createElement('div', { className: 'cut-transcript-reader-content' }, [domText('p', 'empty-state', 'Carregando transcrição...')]);
  const saveButton = domButton('Salvar e voltar ao ajuste', 'save', 'lime', 'save-cut-transcript', { 'data-cut-id': Number(cut.cut_id || cut.id) });
  panel.append(createElement('div', { className: 'cut-modal-header' }, [domText('h2', '', 'Transcrição do corte'), close]), domText('p', 'schedule-modal-lead', 'Corrija as palavras neste trecho e salve antes de gerar a legenda.'), content, createElement('div', { className: 'schedule-modal-actions' }, [domButton('Fechar', 'x', 'secondary', 'close-cut-transcript'), saveButton]));
  modal.appendChild(panel);
  document.body.appendChild(modal);
  const finish = () => modal.remove();
  modal.addEventListener('click', event => {
    if (event.target === modal || event.target.closest('[data-action="close-cut-transcript"]')) finish();
  });
  try {
    const [transcriptionResponse, editedResponse] = await Promise.all([
      fetch(`/api/transcription?video_id=${encodeURIComponent(cut.video_id)}`, { headers: { 'X-Profile-Id': String(activeProfileId) } }),
      fetch(`/api/cuts/caption-transcript?cut_id=${encodeURIComponent(Number(cut.cut_id || cut.id))}`, { headers: { 'X-Profile-Id': String(activeProfileId) } }),
    ]);
    const payload = await transcriptionResponse.json();
    const editedPayload = editedResponse.ok ? await editedResponse.json() : { segments: [] };
    if (!transcriptionResponse.ok) throw new Error(payload.error || 'Não foi possível carregar a transcrição.');
    const start = Number(cut.inicio_segundos ?? cut.inicio ?? 0);
    const end = Number(cut.fim_segundos ?? cut.fim ?? Number.POSITIVE_INFINITY);
    const segments = (payload.segments || []).filter(segment => Number(segment.fim) > start && Number(segment.inicio) < end);
    clearElement(content);
    if (!segments.length) {
      const message = String(payload.text || '').trim()
        ? 'A transcrição existe, mas não possui segmentos temporizados para este corte. Refaça a transcrição ou envie um SRT para editar por trecho.'
        : 'Este vídeo não possui uma transcrição disponível. Gere a transcrição ou envie um arquivo SRT antes de ajustar a legenda.';
      content.appendChild(domText('p', 'empty-state', message));
      return;
    }
    const editedByIndex = new Map((editedPayload.segments || []).map(segment => [Number(segment.indice), segment.texto]));
    segments.forEach((segment, index) => {
      const segmentIndex = Number(segment.indice ?? index);
      const relativeStart = Math.max(0, Number(segment.inicio) - start);
      const relativeEnd = Math.max(relativeStart, Number(segment.fim) - start);
      content.appendChild(createElement('article', { className: 'cut-transcript-line' }, [
        domText('time', '', `${formatCutTranscriptTime(relativeStart)} - ${formatCutTranscriptTime(relativeEnd)}`),
        createElement('textarea', { className: 'cut-transcript-edit', 'data-segment-index': String(segmentIndex), rows: '2', maxlength: '2000' }, editedByIndex.has(segmentIndex) ? editedByIndex.get(segmentIndex) : (segment.texto || '')),
      ]));
    });
    saveButton.addEventListener('click', async () => {
      const segmentsToSave = [...content.querySelectorAll('[data-segment-index]')].map(input => ({ indice: Number(input.dataset.segmentIndex), texto: input.value }));
      saveButton.disabled = true;
      try {
        const response = await fetch('/api/cuts/caption-transcript', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Profile-Id': String(activeProfileId) }, body: JSON.stringify({ cut_id: Number(cut.cut_id || cut.id), segments: segmentsToSave }) });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Não foi possível salvar a transcrição.');
        showToast('Transcrição do corte salva. Ela será usada na próxima geração de legenda.');
        finish();
      } catch (error) { showToast(error.message); }
      finally { saveButton.disabled = false; }
    });
  } catch (error) {
    clearElement(content);
    content.appendChild(domText('p', 'empty-state', error.message));
  }
}
async function generateCutCaptions(cutId, options, modal) {
  try {
    const response = await fetch('/api/cuts/generate-captions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cut_id: cutId, ...options }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível iniciar a geração de legendas.');
    modal?.remove();
    cutJob = { id: payload.job_id, kind: 'captions', status: 'queued', progress: 0, message: 'Legendas na fila', started_at: Date.now(), perfil_id: activeProfileId, cut_ids: [cutId], estimated_duration_seconds: payload.estimated_duration_seconds };
    rememberActiveJob('cut', cutJob);
    renderCuts();
    pollCutJob();
  } catch (error) { showToast(error.message); }
}
async function generateCaptionsForCuts(cutIds, options, modal) {
  const ids = [...new Set(cutIds.map(Number).filter(Boolean))];
  if (ids.length < 2) return generateCutCaptions(ids[0], options, modal);
  try {
    const settled = await Promise.allSettled(ids.map(async cutId => {
      const response = await fetch('/api/cuts/generate-captions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cut_id: cutId, ...options }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `Não foi possível iniciar a legenda do corte ${cutId}.`);
      return { cutId, payload };
    }));
    const results = settled.filter(item => item.status === 'fulfilled').map(item => item.value);
    const failures = settled.filter(item => item.status === 'rejected');
    if (!results.length) throw new Error(failures[0]?.reason?.message || 'Não foi possível iniciar as legendas.');
    modal?.remove();
    results.forEach(({ cutId, payload }) => {
      activeCutOperations.set(cutId, { id: payload.job_id, kind: 'captions', status: 'queued', progress: 0, message: 'Legendas na fila', started_at: Date.now(), cut_ids: [cutId], estimated_duration_seconds: payload.estimated_duration_seconds });
      captionBatchJobs.set(payload.job_id, cutId);
    });
    renderCuts();
    pollCaptionBatchJobs();
    showToast(`${results.length} legendas enviadas para processamento${failures.length ? `; ${failures.length} não iniciada(s)` : ''}.`);
  } catch (error) { showToast(error.message); }
}
let captionBatchPolling = false;
async function pollCaptionBatchJobs() {
  if (captionBatchPolling || !captionBatchJobs.size) return;
  captionBatchPolling = true;
  try {
    const completed = [];
    for (const [jobId, cutId] of captionBatchJobs) {
      const response = await fetch(`/api/jobs/${jobId}`);
      if (!response.ok) continue;
      const payload = await response.json();
      const operation = activeCutOperations.get(cutId) || {};
      activeCutOperations.set(cutId, { ...operation, ...payload, id: jobId, kind: 'captions', cut_ids: [cutId] });
      if (['completed', 'failed', 'interrupted', 'cancelled'].includes(payload.status)) completed.push({ jobId, cutId, status: payload.status });
    }
    completed.forEach(({ jobId, cutId }) => { captionBatchJobs.delete(jobId); activeCutOperations.delete(cutId); });
    refreshActiveCutCards();
    if (completed.some(item => item.status === 'completed')) await reloadSelectedCutData();
    if (captionBatchJobs.size) setTimeout(pollCaptionBatchJobs, 1000);
    else renderCuts();
  } catch (error) {
    if (captionBatchJobs.size) setTimeout(pollCaptionBatchJobs, 1000);
  } finally { captionBatchPolling = false; }
}
function renderCutCard(cut, options = {}) {
  const cutId = Number(cut.cut_id || cut.id);
  const activeOperation = activeCutOperationFor(cutId);
  if (activeOperation) return renderCutProcessingCard(cut, activeOperation, options);
  const status = cut.status || 'candidato';
  const outputAvailable = status === 'concluido' && (cut.output_path || cut.caminho_saida);
  const canSelect = ['candidato', 'concluido', 'selecionado'].includes(status);
  const score = Math.max(0, Math.min(100, Number(cut.score_vaca_roxa || 0)));
  const title = cut.titulo || 'Corte editorial';
  const captionReady = cut.legenda_status === 'concluido' && cut.legenda_caminho;
  const card = createElement('article', { className: `cut-card ${options.candidate ? 'candidate-row' : ''}`, 'data-cut-id': String(cutId) });
  const header = createElement('div', { className: 'cut-card-header' }, [domText('span', 'cut-status', options.statusLabel || (status === 'concluido' ? 'Renderizado' : 'Para revisar'))]);
  const scoreBadge = domText('span', 'score-meter', score.toFixed(0));
  scoreBadge.style.setProperty('--cut-score', String(score));
  const preview = createElement('div', { className: 'cut-preview' }, [scoreBadge]);
  if (outputAvailable) {
    const video = createElement('video', { className: 'cut-player', controls: 'true', preload: 'metadata' });
    const mediaVersion = captionReady ? (cut.legenda_caminho || cut.atualizado_em) : (cut.caminho_saida || cut.atualizado_em);
    video.src = `/api/cuts/file?id=${encodeURIComponent(cutId)}&captions=${captionReady ? '1' : '0'}&perfil_id=${encodeURIComponent(activeProfileId)}&v=${encodeURIComponent(mediaVersion || '')}`;
    video.setAttribute('aria-label', `Prévia de ${cut.titulo || 'corte'}`);
    preview.insertBefore(video, scoreBadge);
    const previewButton = domButton('', 'maximize-2', 'secondary', 'fullscreen-cut-preview', { 'data-cut-id': cutId, title: 'Ver corte em tela cheia' });
    previewButton.classList.add('cut-preview-expand');
    previewButton.setAttribute('aria-label', 'Ver corte em tela cheia');
    preview.appendChild(previewButton);
  } else if (status === 'falhou') {
    preview.appendChild(domText('p', 'cut-error', cut.erro || cut.error || 'A renderização falhou.'));
  }
  const actions = createElement('div', { className: 'cut-card-actions' }, [
    domButton('Editar título', 'pencil', 'secondary', 'edit-cut', { 'data-cut-id': cutId }),
    domButton('Gerar título', 'sparkles', 'secondary', 'regenerate-cut-metadata', { 'data-cut-id': cutId, 'data-field': 'title' }),
    domButton('Gerar descrição', 'sparkles', 'secondary', 'regenerate-cut-metadata', { 'data-cut-id': cutId, 'data-field': 'description' }),
  ]);
  if (canSelect) {
    const selected = selectedCandidateIds.has(cutId);
    const selectButton = domButton(selected ? 'Selecionado' : 'Selecionar', selected ? 'circle-check' : 'circle', selected ? 'selected' : 'secondary', 'candidate-toggle-button', { 'data-cut-id': cutId, 'aria-pressed': String(selected), title: selected ? 'Remover da seleção para postagem' : 'Selecionar para postagem' });
    selectButton.classList.add('cut-select-toggle');
    selectButton.setAttribute('aria-label', selected ? 'Remover da seleção para postagem' : 'Selecionar para postagem');
    actions.appendChild(selectButton);
  }
  if (canSelect && !outputAvailable) actions.appendChild(domButton('Renderizar', 'scissors', 'secondary', 'render-cut', { 'data-cut-id': cutId }));
  if (cut.arquivo_origem || outputAvailable) actions.appendChild(domButton(captionReady ? 'Refazer legendas' : 'Gerar legendas', 'captions', 'secondary', 'caption-cut', { 'data-cut-id': cutId }));
  if (captionReady) {
    const captionLink = setSafeLink(createElement('a', { className: 'button secondary' }), `/api/cuts/file?id=${encodeURIComponent(cutId)}&captions=1&perfil_id=${encodeURIComponent(activeProfileId)}`);
    captionLink.setAttribute('download', `${title.replace(/[^a-z0-9]+/gi, '_')}_legendas.mp4`);
    captionLink.append(domIcon('download'), ' Baixar legendado');
    actions.appendChild(captionLink);
  }
  if (outputAvailable) {
    const download = setSafeLink(createElement('a', { className: 'button secondary' }), `/api/cuts/file?id=${encodeURIComponent(cutId)}&perfil_id=${encodeURIComponent(activeProfileId)}`);
    download.setAttribute('download', `${title.replace(/[^a-z0-9]+/gi, '_')}.mp4`);
    download.append(domIcon('download'), ' Baixar MP4');
    actions.appendChild(download);
    actions.appendChild(domButton('Agendar postagem', 'calendar-plus', 'secondary', 'schedule-cut', { 'data-cut-id': cutId }));
  }
  if (canSelect || outputAvailable) actions.appendChild(domButton('Excluir', 'trash-2', 'danger', 'delete-cut', { 'data-cut-id': cutId }));
  const publicationDetails = createElement('details', { className: 'cut-publication-details', 'data-publication-cut-id': String(cutId) }, [
    createElement('summary', { className: 'cut-publication-summary' }, ['Descrição para o YouTube', domIcon('chevron-down')]),
    domText('p', 'cut-publication-description', publicationDescription(cut)),
  ]);
  card.append(header, domText('h3', 'cut-title', title), preview, publicationDetails, actions);
  return card;
}
function openCutPreview(cut) {
  const cutId = Number(cut.cut_id || cut.id);
  const captionReady = cut.legenda_status === 'concluido' && cut.legenda_caminho;
  document.querySelectorAll('video').forEach(video => video.pause());
  document.querySelector('.cut-preview-backdrop')?.remove();
  const modal = createElement('div', { className: 'cut-modal-backdrop cut-preview-backdrop' });
  const panel = createElement('section', { className: 'cut-modal cut-preview-modal', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'cut-preview-title' });
  const close = domButton('Fechar', 'x', 'secondary', 'close-cut-preview');
  const video = createElement('video', { className: 'cut-preview-full', controls: 'true', preload: 'metadata', playsinline: 'true' });
  const mediaVersion = captionReady ? (cut.legenda_caminho || cut.atualizado_em) : (cut.caminho_saida || cut.atualizado_em);
  video.src = `/api/cuts/file?id=${encodeURIComponent(cutId)}&captions=${captionReady ? '1' : '0'}&perfil_id=${encodeURIComponent(activeProfileId)}&v=${encodeURIComponent(mediaVersion || '')}`;
  video.setAttribute('aria-label', `Corte em tamanho real: ${cut.titulo || 'corte'}`);
  panel.append(createElement('div', { className: 'cut-modal-header' }, [domText('h2', '', cut.titulo || 'Corte'), close]), video);
  modal.appendChild(panel);
  document.body.appendChild(modal);
  modal.addEventListener('click', event => { if (event.target === modal) modal.remove(); });
}
function activeCutOperationFor(cutId) {
  const localOperation = activeCutOperations.get(Number(cutId));
  if (localOperation) return localOperation;
  if (!isLiveJob(cutJob)) return null;
  const activeIds = cutJob.cut_ids || cutJob.cutIds || [];
  return activeIds.map(Number).includes(Number(cutId)) ? cutJob : null;
}
function renderCutProcessingCard(cut, operation, options = {}) {
  const cutId = Number(cut.cut_id || cut.id);
  const title = cut.titulo || 'Corte editorial';
  const card = createElement('article', { className: `cut-card cut-card-processing ${options.candidate ? 'candidate-row' : ''}`, 'data-cut-id': String(cutId) });
  card.append(
    createElement('div', { className: 'cut-card-header' }, [domText('span', 'cut-status', 'Processando')]),
    domText('h3', 'cut-title', title),
    createElement('div', { className: 'cut-processing-stage' }, [domIcon('loader-circle'), domText('span', '', operation.message || 'Processando corte')]),
    renderJobProgress(operation),
  );
  return card;
}
function refreshActiveCutCards() {
  const activeIds = new Set((cutJob?.cut_ids || cutJob?.cutIds || []).map(Number));
  activeCutOperations.forEach((operation, cutId) => activeIds.add(Number(cutId)));
  activeIds.forEach(cutId => {
    const cut = [...persistedCuts, ...cutSuggestions].find(item => Number(item.cut_id || item.id) === cutId);
    const currentCard = document.querySelector(`article[data-cut-id="${cutId}"]`);
    if (!cut || !currentCard) return;
    currentCard.replaceWith(renderCutCard(cut, { candidate: currentCard.classList.contains('candidate-row') }));
  });
  refreshIcons();
}
function publicationDescription(cut) {
  const savedDescription = String(cut.descricao_publicacao || '').trim();
  if (savedDescription) return savedDescription;
  return 'Descrição editorial ainda não gerada. Ela será revisada antes da publicação.';
}
function openCutEditor(cut) {
  closeCutEditor();
  const cutId = Number(cut.cut_id || cut.id);
  const modal = createElement('div', { className: 'cut-modal-backdrop' });
  const panel = createElement('section', { className: 'cut-modal cut-metadata-modal', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'cut-metadata-title' });
  const close = domButton('Fechar', 'x', 'secondary', 'close-cut-editor');
  panel.appendChild(createElement('div', { className: 'cut-modal-header' }, [domText('h2', '', 'Editar título e descrição'), close]));
  panel.appendChild(domText('p', 'schedule-modal-lead', 'Esses dados serão enviados ao YouTube junto com o Short.'));
  panel.appendChild(createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Título do Short'), createElement('input', { id: 'cut-edit-title', value: cut.titulo || '', maxlength: '100' }), domButton('Gerar título', 'sparkles', 'secondary', 'regenerate-cut-metadata', { 'data-cut-id': cutId, 'data-field': 'title' })]));
  panel.appendChild(createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Descrição para o YouTube'), createElement('textarea', { id: 'cut-edit-description', maxlength: '5000', rows: '7' }, cut.descricao_publicacao || ''), domButton('Gerar descrição', 'sparkles', 'secondary', 'regenerate-cut-metadata', { 'data-cut-id': cutId, 'data-field': 'description' })]));
  panel.appendChild(createElement('div', { className: 'schedule-modal-actions' }, [domButton('Cancelar', 'x', 'secondary', 'close-cut-editor'), domButton('Salvar alterações', 'save', 'lime', 'save-cut-metadata', { 'data-cut-id': cutId })]));
  modal.appendChild(panel);
  document.body.appendChild(modal);
  modal.addEventListener('click', event => { if (event.target === modal) closeCutEditor(); });
}
function closeCutEditor() { document.querySelector('.cut-modal-backdrop')?.remove(); }
async function deleteCutCycle(videoId, roundName) {
  if (!confirm('Excluir todos os cortes desta rodada?')) return;
  try {
    const response = await fetch('/api/cuts/delete-cycle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ video_id: videoId, nome_rodada: roundName }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível excluir a rodada.');
    await reloadSelectedCutData();
    renderCuts();
    showToast(`${payload.deleted} cortes excluídos.`);
  } catch (error) { showToast(error.message); }
}
async function replaceCycleMetadata(jobId, count) {
  const source = window.prompt('Qual palavra ou expressão deve ser substituída?', 'Varenga')?.trim() || '';
  if (!source) return;
  const replacement = window.prompt(`Por qual texto substituir “${source}”?`, 'Alvarenga')?.trim() || '';
  if (!replacement) return;
  if (!window.confirm(`Substituir “${source}” por “${replacement}” no título e na descrição dos ${count} cortes deste ciclo?`)) return;
  try {
    const response = await fetch('/api/cuts/replace-cycle-metadata', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_id: jobId, source, replacement }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível substituir os metadados do ciclo.');
    await reloadSelectedCutData();
    renderCuts();
    showToast(`${payload.occurrences} ocorrência(s) substituída(s) em ${payload.cuts} corte(s).`);
  } catch (error) { showToast(error.message); }
}
function reviewCutGroups(cuts) {
  const groups = new Map();
  cuts.forEach(cut => {
    const videoKey = cut.video_id || cut.video_titulo || 'video-sem-identificacao';
    if (!groups.has(videoKey)) groups.set(videoKey, { videoId: cut.video_id, title: cut.video_titulo || cut.video_id || 'Vídeo original', cycles: new Map() });
    const video = groups.get(videoKey);
    const cycleKey = cut.nome_rodada || `Ciclo ${Number(cut.numero_rodada || 1)}`;
    if (!video.cycles.has(cycleKey)) video.cycles.set(cycleKey, []);
    video.cycles.get(cycleKey).push(cut);
  });
  return [...groups.values()];
}
function renderReviewGroups(cuts, toggleAction = 'candidate-toggle') {
  const root = createElement('div', { className: 'cut-groups' });
  reviewCutGroups(cuts).forEach(video => {
    const videoGroup = createElement('details', { className: 'cut-video-group', 'data-video-id': video.videoId || '' });
    const totalCuts = [...video.cycles.values()].reduce((total, cycle) => total + cycle.length, 0);
    const source = cutSources.find(item => item.id === video.videoId) || { id: video.videoId, title: video.title, thumbnail_url: `https://i.ytimg.com/vi/${video.videoId}/hqdefault.jpg` };
    const videoSummary = createElement('summary', { className: 'cut-group-summary' }, [
      createVideoThumbnail(source, true),
      createElement('span', { className: 'cut-group-summary-copy' }, [
        domText('strong', '', video.title),
        domText('small', '', `${totalCuts} corte${totalCuts === 1 ? '' : 's'} gerado${totalCuts === 1 ? '' : 's'}`),
      ]),
    ]);
    videoGroup.appendChild(videoSummary);
    const cycles = createElement('div', { className: 'cut-cycles' });
    [...video.cycles.entries()].forEach(([cycleName, cycleCuts], cycleIndex) => {
      const cycleGroup = createElement('details', { className: 'cut-cycle-group', 'data-video-id': video.videoId || '', 'data-cycle-key': cycleName });
      const cycleIds = cycleCuts.map(cut => Number(cut.cut_id || cut.id)).filter(Boolean);
      const cycleHeader = createElement('summary', { className: 'cut-cycle-summary' }, [domText('strong', '', `Ciclo ${cycleIndex + 1}`), domText('span', '', `${cycleCuts.length} cortes`)]);
      const cycleSelected = cycleIds.length > 0 && cycleIds.every(cutId => selectedCandidateIds.has(cutId));
      const selectedCycleIds = cycleIds.filter(cutId => selectedCandidateIds.has(cutId));
      const cycleActions = createElement('div', { className: 'cut-cycle-actions' }, [domButton(cycleSelected ? 'Desselecionar todos' : 'Selecionar todos', 'check-check', 'secondary', 'select-cycle-cuts', { 'data-cut-ids': cycleIds.join(','), 'aria-pressed': String(cycleSelected), 'aria-label': cycleSelected ? 'Desselecionar todos deste ciclo' : 'Selecionar todos deste ciclo' }), domButton('Agendar ciclo', 'calendar-plus', 'secondary', 'schedule-cycle-cuts', { 'data-cut-ids': cycleIds.join(',') }), domButton('Gerar legendas', 'captions', 'secondary', 'caption-cycle-cuts', { 'data-cut-ids': selectedCycleIds.join(','), 'data-all-cut-ids': cycleIds.join(','), hidden: selectedCycleIds.length < 2 ? 'hidden' : null }), domButton('Substituir palavras', 'replace', 'secondary', 'replace-cycle-metadata', { 'data-job-id': cycleCuts[0]?.job_id || '', 'data-count': cycleIds.length }), domButton('Excluir ciclo', 'trash-2', 'danger', 'delete-cut-cycle', { 'data-video-id': cycleCuts[0]?.video_id || '', 'data-round-name': cycleName })]);
      cycleGroup.append(cycleHeader, cycleActions);
      const list = createElement('div', { className: 'suggestion-list' });
      [...cycleCuts].sort((left, right) => Number(right.score_vaca_roxa || 0) - Number(left.score_vaca_roxa || 0)).forEach((cut, index) => {
        const status = cut.status || 'candidato';
        const statusLabel = status === 'concluido' ? 'Renderizado' : status === 'selecionado' ? 'Selecionado' : 'Para revisar';
        list.appendChild(renderCutCard(cut, { candidate: true, toggleAction, statusLabel: status === 'candidato' ? `Candidato ${String(index + 1).padStart(2, '0')}` : statusLabel }));
      });
      cycleGroup.appendChild(list);
      cycles.appendChild(cycleGroup);
    });
    videoGroup.appendChild(cycles);
    root.appendChild(videoGroup);
  });
  return root;
}
function allReviewCuts() {
  const byId = new Map();
  [...persistedCuts, ...cutSuggestions].forEach(cut => {
    const key = cut.cut_id || cut.id || `${cut.video_id}-${cut.nome_rodada}-${cut.inicio}`;
    if (!byId.has(key)) byId.set(key, cut);
  });
  return [...byId.values()]
    .filter(cut => cut.status === 'concluido' && (cut.output_path || cut.caminho_saida))
    .map(cut => {
      if (!/^\s*\[(?:m[uú]sica|som(?: de [^\]]+)?|ru[ií]do|aplausos?|risos?)\]/i.test(String(cut.titulo || ''))) return cut;
      const replacement = [cut.gancho, cut.promessa, cut.conclusao].find(value => value && !/^\s*\[/i.test(String(value)));
      return replacement ? { ...cut, titulo: String(replacement).slice(0, 55).trim() } : cut;
    })
    .sort((left, right) => Number(right.score_vaca_roxa || 0) - Number(left.score_vaca_roxa || 0))
}
async function runTranscription() {
  if (!selectedCutSource) return showToast('Selecione um vídeo longo primeiro.');
  showToast('Transcrição iniciada. Acompanhe o progresso na Central.');
  try {
    const response = await fetch('/api/transcription/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ video_id: selectedCutSource.id }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'falha na transcrição');
    transcriptionJob = { id: payload.job_id, status: 'queued', progress: 0, message: 'Na fila', perfil_id: activeProfileId };
    rememberActiveJob('transcription', transcriptionJob);
    renderCuts();
    pollTranscriptionJob();
  } catch (error) {
    showToast(error.message);
  }
}
async function clearTranscriptionCache(videoId) {
  if (!videoId || !confirm('Limpar o cache da transcrição e permitir uma nova transcrição? O vídeo e os cortes serão preservados.')) return;
  try {
    const response = await fetch('/api/transcription/clear-cache', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ video_id: videoId }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível limpar o cache da transcrição.');
    if (selectedCutSource?.id === videoId) selectedCutSource.transcription = null;
    showToast('Cache da transcrição limpo. O vídeo e os cortes foram preservados.');
    await loadCutSources();
  } catch (error) {
    showToast(error.message);
  }
}
async function exportTranscription(videoId) {
  if (!videoId) return;
  try {
    const response = await fetch(`/api/transcription/export?video_id=${encodeURIComponent(videoId)}`);
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || 'Não foi possível exportar a transcrição.');
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    const filename = String(selectedCutSource?.title || 'transcricao').replace(/[<>:"/\\|?*\u0000-\u001f]/g, '').trim().slice(0, 100) || 'transcricao';
    link.download = `${filename}.srt`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    showToast('Transcrição exportada em SRT.');
  } catch (error) {
    showToast(error.message);
  }
}
async function openEditorialDossier(videoId) {
  if (!videoId) return;
  try {
    const response = await fetch(`/api/editorial/dossier?video_id=${encodeURIComponent(videoId)}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível carregar o Dossiê Editorial.');
    const dossier = payload.dossier || {};
    const chapters = Array.isArray(dossier.capitulos) ? dossier.capitulos : [];
    const melhoresMomentos = Array.isArray(dossier.melhores_momentos) ? dossier.melhores_momentos : [];
    const modal = createElement('div', { className: 'cut-modal-backdrop editorial-reader-backdrop' });
    const panel = createElement('section', { className: 'cut-modal editorial-reader-modal', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'editorial-reader-title' });
    const close = () => modal.remove();
    panel.appendChild(createElement('div', { className: 'cut-modal-header' }, [domText('h2', '', 'Dossiê Editorial'), domButton('Fechar', 'x', 'ghost', 'close-editorial-reader')]));
    panel.appendChild(domText('p', 'schedule-modal-lead', dossier.resumo_global || 'Resumo editorial não disponível.'));
    const chapterList = createElement('div', { className: 'editorial-chapter-list' });
    chapters.forEach((chapter, index) => {
      const start = Number(chapter.inicio ?? chapter.inicio_segundos);
      const end = Number(chapter.fim ?? chapter.fim_segundos);
      const chapterTitle = chapter.titulo || `Capítulo ${index + 1}`;
      const chapterLabel = Number.isFinite(start) ? `${formatElapsedSeconds(start)} - ${chapterTitle}` : chapterTitle;
      chapterList.appendChild(createElement('article', { className: 'editorial-chapter' }, [
        domText('span', 'editorial-chapter-index', chapterLabel),
        Number.isFinite(end) ? domText('p', '', `Até ${formatElapsedSeconds(end)}`) : null,
      ]));
    });
    if (chapters.length) panel.appendChild(chapterList);
    else panel.appendChild(domText('p', 'empty-state', 'A IA não encontrou capítulos editoriais neste vídeo.'));
    if (melhoresMomentos.length) {
      const momentsList = createElement('div', { className: 'editorial-moments-list' });
      melhoresMomentos.forEach(moment => {
        momentsList.appendChild(createElement('article', { className: 'editorial-moment' }, [
          domText('h3', '', moment.titulo || 'Momento editorial'),
          domText('p', '', moment.descricao_publicacao || ''),
        ]));
      });
      panel.appendChild(momentsList);
    }
    modal.appendChild(panel);
    document.body.appendChild(modal);
    modal.addEventListener('click', event => { if (event.target === modal) close(); });
    panel.querySelector('[data-action="close-editorial-reader"]')?.addEventListener('click', close);
    refreshIcons();
  } catch (error) {
    showToast(error.message);
  }
}
async function deleteEditorialDossier(videoId) {
  if (!videoId || !confirm('Apagar o Dossiê Editorial deste vídeo? A transcrição, o vídeo e os cortes serão preservados.')) return;
  try {
    const response = await fetch('/api/editorial/delete-dossier', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ video_id: videoId }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível apagar o Dossiê Editorial.');
    const source = cutSources.find(video => String(video.id) === String(videoId));
    if (source) source.has_editorial = false;
    showToast(payload.deleted ? 'Dossiê Editorial apagado. Gere novamente quando quiser.' : 'Este vídeo não possui Dossiê Editorial.');
    renderCuts();
  } catch (error) {
    showToast(error.message);
  }
}
async function cancelActiveJob() {
  const activeJob = cutJob || transcriptionJob;
  if (!activeJob?.id) return;
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(activeJob.id)}/cancel`, { method: 'POST', headers: { 'X-Profile-Id': String(activeJob.perfil_id || activeProfileId) } });
    const payload = await response.json();
    if (!response.ok) {
      if (payload.status && ['completed', 'failed', 'cancelled', 'interrupted', 'rejected', 'needs_review', 'needs_review_fallback'].includes(payload.status)) {
        forgetActiveJob(activeJob.id);
        if (cutJob?.id === activeJob.id) cutJob = null;
        if (transcriptionJob?.id === activeJob.id) transcriptionJob = null;
        renderCuts();
      }
      throw new Error(payload.error || 'Não foi possível cancelar o processo.');
    }
    if (cutJob?.id === activeJob.id) cutJob = { ...cutJob, ...payload };
    if (transcriptionJob?.id === activeJob.id) transcriptionJob = { ...transcriptionJob, ...payload };
    renderCuts();
    if (payload.status === 'cancelling') {
      rememberActiveJob(activeJob.kind || (cutJob?.id === activeJob.id ? 'cut' : 'transcription'), { ...activeJob, ...payload });
      if (cutJob?.id === activeJob.id) pollCutJob();
      else if (transcriptionJob?.id === activeJob.id) pollTranscriptionJob();
      showToast('Cancelamento em andamento. Aguarde a liberação antes de gerar novamente.');
    } else {
      forgetActiveJob(activeJob.id);
      showToast('Cancelamento concluído.');
    }
  } catch (error) {
    showToast(error.message);
  }
}
async function uploadLocalMedia() {
  if (uploadProgress) return showToast('O upload já está em andamento.');
  const input = document.querySelector('#local-media-file');
  if (!input?.files?.[0]) return showToast('Selecione um arquivo MP4 ou MKV.');
  const file = input.files[0];
  if (!/\.(mp4|mkv)$/i.test(file.name)) return showToast('Envie um vídeo MP4 ou MKV.');
  const maxUploadBytes = 8 * 1024 * 1024 * 1024;
  if (file.size > maxUploadBytes) return showToast('O arquivo excede o limite local de 8 GB.');
  const form = new FormData();
  form.append('file', file);
  try {
    uploadProgress = { status: 'uploading', progress: 0, message: `Enviando ${file.name}` };
    renderCuts();
    const result = await new Promise((resolve, reject) => {
      const request = new XMLHttpRequest();
      request.open('POST', '/api/uploads/local');
      request.setRequestHeader('X-Profile-Id', String(activeProfileId));
      request.setRequestHeader('X-Cut-Min-Seconds', String(cutDurationRange.min));
      request.setRequestHeader('X-Cut-Max-Seconds', String(cutDurationRange.max));
      request.upload.addEventListener('progress', event => {
        if (!event.lengthComputable) return;
        uploadProgress = { status: 'uploading', progress: Math.round((event.loaded / event.total) * 100), message: `Enviando ${file.name}` };
        renderCuts();
      });
      request.addEventListener('load', () => {
        let payload = {};
        try { payload = request.responseText ? JSON.parse(request.responseText) : {}; } catch (parseError) { payload = { error: request.responseText }; }
        resolve({ status: request.status, payload });
      });
      request.addEventListener('error', () => reject(new TypeError('Falha de rede durante o upload.')));
      request.addEventListener('abort', () => reject(new Error('Upload cancelado.')));
      request.send(form);
    });
    if (result.status < 200 || result.status >= 300) throw new Error(result.payload.error || 'Falha no upload.');
    uploadProgress = null;
    const payload = result.payload;
    cutJob = { id: payload.job_id, status: 'queued', progress: 0, message: 'Upload recebido', started_at: Date.now() };
    rememberActiveJob('cut', cutJob);
    renderCuts();
    pollCutJob();
  } catch (error) {
    uploadProgress = null;
    renderCuts();
    showToast(error.name === 'TypeError' ? 'Não foi possível enviar o arquivo. Verifique se o servidor está ativo e tente novamente.' : error.message);
  }
}
async function useLocalPathMedia() {
  if (uploadProgress) return showToast('O processamento local já está em andamento.');
  const input = document.querySelector('#local-media-path');
  const path = input?.value?.trim();
  if (!path) return showToast('Informe o caminho completo de um arquivo MP4 ou MKV.');
  try {
    uploadProgress = { status: 'uploading', progress: 0, message: 'Validando arquivo local' };
    renderCuts();
    const response = await fetch('/api/uploads/local-path', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Profile-Id': String(activeProfileId), 'X-Cut-Min-Seconds': String(cutDurationRange.min), 'X-Cut-Max-Seconds': String(cutDurationRange.max) },
      body: JSON.stringify({ path, duracao_minima: cutDurationRange.min, duracao_maxima: cutDurationRange.max }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível usar o arquivo local.');
    uploadProgress = null;
    cutJob = { id: payload.job_id, status: 'queued', progress: 0, message: 'Arquivo local selecionado', started_at: Date.now() };
    rememberActiveJob('cut', cutJob);
    renderCuts();
    pollCutJob();
  } catch (error) {
    uploadProgress = null;
    renderCuts();
    showToast(error.message);
  }
}
async function uploadSrtTranscription() {
  if (!selectedCutSource?.id) return showToast('Selecione um vídeo antes de enviar o SRT.');
  const input = document.querySelector('#srt-transcription-file');
  const file = input?.files?.[0];
  if (!file) return showToast('Escolha um arquivo SRT.');
  if (!/\.srt$/i.test(file.name)) return showToast('Envie um arquivo com extensão .srt.');
  const form = new FormData();
  form.append('file', file);
  try {
    const response = await fetch('/api/transcription/upload-srt', { method: 'POST', headers: { 'X-Profile-Id': String(activeProfileId), 'X-Video-Id': selectedCutSource.id }, body: form });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível usar o SRT.');
    selectedCutSource.transcription = payload.transcription;
    renderCuts();
    showToast(`${payload.segments.length} segmentos carregados do SRT.`);
  } catch (error) {
    showToast(error.message);
  }
}
async function forceDownloadMedia() {
  const input = document.querySelector('#force-download-url');
  const url = input?.value?.trim();
  if (!url) return showToast('Informe uma URL do YouTube.');
  try {
    const response = await fetch('/api/downloads/force', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url, duracao_minima: cutDurationRange.min, duracao_maxima: cutDurationRange.max }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Falha ao iniciar download.');
    cutJob = { id: payload.job_id, status: 'queued', progress: 0, message: 'Download forçado na fila', started_at: Date.now() };
    rememberActiveJob('cut', cutJob);
    renderCuts();
    pollCutJob();
  } catch (error) {
    showToast(error.message);
  }
}
async function pollTranscriptionJob() {
  if (!transcriptionJob) return;
  try {
    const response = await fetch(`/api/jobs/${transcriptionJob.id}`);
    const payload = await response.json();
    transcriptionJob = { ...transcriptionJob, ...payload };
    renderCuts();
    if (payload.status === 'completed') {
      forgetActiveJob(transcriptionJob.id);
      selectedCutSource.transcription = { segments: payload.segments || [] };
      transcriptionJob = null;
      renderCuts();
      showToast('Transcrição concluída e salva no SQLite.');
      return;
    }
    if (payload.status === 'failed' || payload.status === 'interrupted' || payload.status === 'cancelled') {
      forgetActiveJob(transcriptionJob.id);
      transcriptionJob = null;
      renderCuts();
      showToast(payload.message || 'A transcrição foi interrompida.');
      return;
    }
    if (payload.status === 'cancelling') {
      setTimeout(pollTranscriptionJob, 1200);
      return;
    }
    setTimeout(pollTranscriptionJob, 1200);
  } catch (error) {
    showToast('Não foi possível acompanhar a transcrição.');
  }
}

function domMetric(label, value, meta, neutral = false) {
  return createElement('div', { className: 'metric-card' }, [domText('span', 'metric-label', label), domText('strong', 'metric-value', value), domText('span', `metric-meta ${neutral ? 'neutral' : ''}`, meta)]);
}
function domPanelHeader(title, subtitle, action = null) {
  const header = createElement('div', { className: 'panel-header' }, [createElement('div', {}, [domText('h2', '', title), domText('p', '', subtitle)])]);
  if (action) header.appendChild(action);
  return header;
}
function renderOverview() {
  const metrics = dashboard.metrics;
  const projectionLabels = { '1_week': '7 dias', '15_days': '15 dias', '1_month': '1 mês', '6_months': '6 meses', '1_year': '1 ano' };
  const selectedProjection = metrics.projections?.[projectionPeriod] || {};
  const root = createElement('div', { className: 'view-card active' });
  root.appendChild(createElement('div', { className: 'page-header overview-header' }, [createElement('div', {}, [domText('span', 'eyebrow', 'Central / visão geral'), domText('h1', '', 'O que merece atenção hoje?'), domText('p', '', 'Um resumo limpo do canal, das projeções e das próximas ações.')]), createElement('div', { className: 'header-actions' }, [domButton('Sincronizar canal', 'refresh-cw', 'lime', 'sync'), domButton('Ver cortes', 'scissors', 'secondary', 'cuts')])]));
  root.appendChild(domText('span', 'overview-section-label', 'Resumo do canal'));
  root.appendChild(createElement('div', { className: 'metric-grid overview-metrics' }, [
    domMetric('Vídeos analisados', metrics.videos_analisados, 'dados do YouTube'),
    domMetric('Cortes em revisão', metrics.cortes_em_revisao ?? 0, 'cortes aguardando revisão'),
    domMetric('Views totais do canal', metrics.views_total_display || formatCount(metrics.views_total), 'dado oficial do YouTube'),
    domMetric('Inscritos', formatCount(metrics.subscribers), metrics.subscribers === null ? 'sincronize após conectar o Google' : 'dado oficial do YouTube', metrics.subscribers === null),
    domMetric('Taxa média de likes', formatRate(metrics.taxa_likes), metrics.taxa_likes === null ? 'sem dados de views' : 'média do canal', metrics.taxa_likes === null),
  ]));
  const projectionFilters = createElement('div', { className: 'projection-filters', role: 'group', 'aria-label': 'Período de projeção' });
  Object.entries(projectionLabels).forEach(([period, label]) => projectionFilters.appendChild(createElement('button', { className: `projection-filter ${projectionPeriod === period ? 'active' : ''}`, type: 'button', 'data-action': 'overview-projection-period', 'data-projection-period': period, textContent: label })));
  const projectionPanel = createElement('section', { className: 'panel channel-projection-panel' }, [domPanelHeader('Projeção de inscritos', 'Estimativa para o período selecionado.', projectionFilters)]);
  projectionPanel.appendChild(createElement('div', { className: 'projection-grid overview-projection-grid' }, [domMetric('Views projetadas', formatCount(selectedProjection.views), 'estimativa de alcance'), domMetric('Inscritos projetados', formatCount(selectedProjection.subscribers), metrics.subscribers === null ? 'aguarda histórico oficial' : 'estimativa', metrics.subscribers === null)]));
  const contentGrid = createElement('div', { className: 'content-grid' });
  const videoPanel = createElement('section', { className: 'panel' }, [domPanelHeader('Melhores sinais', 'Vídeos que mais ajudam a orientar os próximos conteúdos.', createElement('button', { className: 'text-link', 'data-action': 'ranking' }, ['VER RANKING ', domIcon('arrow-up-right')]))]);
  const videoList = createElement('div', { className: 'video-list' });
  videos.slice(0, 4).forEach((video, index) => {
    const info = createElement('div', { className: 'video-info' }, [createElement('strong', {}, [domText('span', 'video-title', video.title), domText('span', `type-pill ${video.type === 'Short' ? 'short' : ''}`, video.type)]), domText('span', '', `${video.date} · ${video.likes_display || video.likes} likes · taxa ${formatRate(video.score)}`)]);
    videoList.appendChild(createElement('div', { className: 'video-row' }, [domText('span', 'rank', `0${index + 1}`), info, createElement('div', { className: 'video-stats' }, [domText('strong', '', video.views_display || video.views), domText('span', '', 'visualizações')])]));
  });
  if (!videos.length) videoList.appendChild(createElement('div', { className: 'video-row' }, [createElement('div', { className: 'video-info' }, [domText('strong', {}, [domText('span', 'video-title', 'Nenhum vídeo sincronizado ainda.')])])]));
  videoPanel.appendChild(videoList);
  const rightStack = createElement('div', { className: 'right-stack' });
  const insight = createElement('section', { className: 'panel insight-panel' }, [domPanelHeader('Leitura do momento', 'O principal padrão identificado nos dados.', domIcon('scan-search')), createElement('div', { className: 'insight-body' }, [createElement('div', { className: 'lime-line' }), domText('p', 'insight-quote', buildInsights()[0].text), domText('p', 'insight-source', `${metrics.videos_analisados} vídeos analisados · taxa média de likes ${formatRate(metrics.taxa_likes)}`)])]);
  const queue = createElement('section', { className: 'panel' }, [domPanelHeader('Próximas ações', 'Tarefas que podem gerar avanço agora.')]);
  queue.appendChild(createElement('div', { className: 'queue-item' }, [createElement('div', { className: 'queue-icon' }, [domIcon('scissors')]), createElement('div', { className: 'queue-copy' }, [domText('strong', '', 'Revisar cortes'), domText('span', '', 'Pipeline de cortes')]), createElement('button', { className: 'dot-menu', 'data-action': 'cuts' }, [domIcon('arrow-up-right')])]));
  queue.appendChild(createElement('div', { className: 'queue-item' }, [createElement('div', { className: 'queue-icon' }, [domIcon('refresh-cw')]), createElement('div', { className: 'queue-copy' }, [domText('strong', '', 'Sincronizar canal'), domText('span', '', `Última atualização ${formatSyncTime(dashboard.last_sync_at)}`)]), createElement('button', { className: 'dot-menu', 'data-action': 'sync' }, [domIcon('arrow-up-right')])]));
  rightStack.append(projectionPanel, insight, queue);
  contentGrid.append(videoPanel, rightStack);
  root.appendChild(contentGrid);
  replaceView(root);
}
function renderRanking() {
  const root = createElement('div', { className: 'view-card active' });
  root.appendChild(createElement('div', { className: 'page-header' }, [createElement('div', {}, [domText('span', 'eyebrow', 'Central / ranking'), domText('h1', '', 'O que o canal já provou?'), domText('p', '', 'Compare desempenho sem misturar formatos. A ordenação começa por views, mas a leitura considera likes, data e contexto.')]), createElement('div', { className: 'header-actions' }, [domButton('Sincronizar dados', 'refresh-cw', 'lime', 'sync')])]));
  const tabs = createElement('div', { className: 'filter-tabs' });
  [{ id: 'video', label: 'Top 15 longos' }, { id: 'short', label: 'Top 15 Shorts' }, { id: '', label: 'Todos os vídeos' }].forEach(tab => tabs.appendChild(createElement('button', { className: `filter-tab ${state.rankingType === tab.id ? 'active' : ''}`, 'data-action': 'ranking-filter', 'data-ranking-type': tab.id, textContent: tab.label })));
  root.appendChild(tabs);
  const table = createElement('table', { className: 'rank-table' });
  table.appendChild(createElement('thead', {}, [createElement('tr', {}, ['#', 'Vídeo', 'Views', 'Likes', 'Taxa', 'Publicado'].map(label => domText('th', '', label)))]));
  const body = createElement('tbody');
  videos.forEach((video, index) => body.appendChild(createElement('tr', {}, [domText('td', '', String(index + 1).padStart(2, '0')), createElement('td', {}, [createElement('strong', {}, [domText('span', 'video-title', video.title), domText('span', `type-pill ${video.type === 'Short' ? 'short' : ''}`, video.type)])]), domText('td', '', video.views_display), domText('td', '', video.likes_display), domText('td', '', formatRate(video.score)), domText('td', '', video.date)])));
  if (!videos.length) body.appendChild(createElement('tr', {}, [domText('td', '', 'Nenhum vídeo sincronizado ainda.')]));
  table.appendChild(body);
  root.appendChild(table);
  replaceView(root);
}
function renderPublishing() {
  const root = createElement('div', { className: 'view-card active' });
  root.appendChild(createElement('div', { className: 'page-header' }, [createElement('div', {}, [domText('span', 'eyebrow', 'Central / publicação'), domText('h1', '', 'Publicar com intenção.'), domText('p', '', 'Vídeos programados ficam separados de vídeos publicados: antes da publicação não existem views ou likes reais para ranquear.')]), createElement('div', { className: 'header-actions' }, [domButton('Atualizar fila', 'refresh-cw', 'lime', 'scheduled')])]));
  const table = createElement('table', { className: 'rank-table' });
  table.appendChild(createElement('thead', {}, [createElement('tr', {}, ['#', 'Vídeo', 'Data', 'Horário', 'Ranking'].map(label => domText('th', '', label)))]));
  const body = createElement('tbody');
  scheduledVideos.forEach((video, index) => body.appendChild(createElement('tr', {}, [domText('td', '', String(index + 1).padStart(2, '0')), createElement('td', {}, [createElement('strong', {}, [domText('span', 'video-title', video.title), domText('span', 'type-pill short', video.type)])]), domText('td', '', video.scheduled_date), domText('td', '', video.scheduled_time), domText('td', '', video.score_note)])));
  if (!scheduledVideos.length) body.appendChild(createElement('tr', {}, [domText('td', '', 'Nenhum vídeo programado registrado.')]));
  table.appendChild(body);
  root.appendChild(table);
  replaceView(root);
}
function renderLibrary() {
  const root = createElement('div', { className: 'view-card active' });
  root.appendChild(createElement('div', { className: 'page-header' }, [createElement('div', {}, [domText('span', 'eyebrow', 'Central / biblioteca'), domText('h1', '', 'Biblioteca do canal'), domText('p', '', 'Filtre o catálogo e abra qualquer vídeo para ver uma leitura mais profunda de desempenho.')]), createElement('div', { className: 'header-actions' }, [domButton('Atualizar biblioteca', 'refresh-cw', 'lime', 'library-refresh')])]));
  const filters = createElement('div', { className: 'library-toolbar' });
  const formatFilters = createElement('div', { className: 'filter-tabs library-filters' });
  [['all', 'Todos os vídeos'], ['video', 'Vídeos longos'], ['short', 'Shorts']].forEach(([value, label]) => formatFilters.appendChild(createElement('button', { className: `filter-tab ${libraryFilter === value ? 'active' : ''}`, 'data-action': 'library-filter', 'data-library-filter': value, textContent: label })));
  filters.appendChild(formatFilters);
  filters.appendChild(createElement('label', { className: 'library-sort-control' }, [domText('span', '', 'Classificar por'), createElement('select', { 'data-action': 'library-sort', 'aria-label': 'Classificar biblioteca' }, [
    createElement('option', { value: 'recent', selected: librarySort === 'recent', textContent: 'Mais recentes' }),
    createElement('option', { value: 'views', selected: librarySort === 'views', textContent: 'Mais views' }),
    createElement('option', { value: 'likes', selected: librarySort === 'likes', textContent: 'Mais likes' }),
    createElement('option', { value: 'score', selected: librarySort === 'score', textContent: 'Maior taxa de likes' }),
  ])]));
  root.appendChild(filters);
  const sortedVideos = [...libraryVideos].sort((left, right) => {
    if (librarySort === 'views') return Number(right.views || 0) - Number(left.views || 0);
    if (librarySort === 'likes') return Number(right.likes || 0) - Number(left.likes || 0);
    if (librarySort === 'score') return Number(right.score ?? -1) - Number(left.score ?? -1);
    const rightDate = Date.parse(right.date || '') || 0;
    const leftDate = Date.parse(left.date || '') || 0;
    return rightDate - leftDate;
  });
  const list = createElement('div', { className: 'library-video-list' });
  sortedVideos.forEach(video => {
    const related = video.related_video_title ? `Relacionado: ${video.related_video_title}` : 'Nenhum vídeo relacionado definido';
    const relatedActions = createElement('div', { className: 'library-related-actions' }, [
      video.tipo === 'short' ? domButton('Definir relacionado', 'link', 'secondary', 'library-related-video', { 'data-short-video-id': video.video_id }) : domText('span', 'library-open-hint', 'Abrir análise'),
      video.tipo === 'short' && video.related_video_status === 'falhou' && video.related_video_id ? domButton('Tentar relação novamente', 'refresh-cw', 'secondary', 'library-retry-related', { 'data-short-video-id': video.video_id, 'data-related-video-id': video.related_video_id }) : null,
    ].filter(Boolean));
    const row = createElement('article', { className: 'library-video-row', 'data-action': 'library-video-detail', 'data-video-id': video.video_id }, [
      createVideoThumbnail(video),
      createElement('div', {}, [createElement('strong', { textContent: video.titulo }), createElement('small', { textContent: `${video.status || 'disponível'} · ${related}` })]),
      relatedActions,
    ]);
    list.appendChild(row);
  });
  if (!libraryVideos.length) list.appendChild(domText('p', 'empty-state', 'Nenhum vídeo encontrado para este filtro.'));
  root.appendChild(list);
  replaceView(root);
}
function renderLibraryDetail() {
  const video = libraryDetail;
  const projections = video.projections || {};
  const analysis = video.analysis || {};
  const root = createElement('div', { className: 'view-card active' });
  root.appendChild(createElement('div', { className: 'page-header' }, [createElement('div', {}, [domText('span', 'eyebrow', 'Central / biblioteca / análise'), domText('h1', '', video.titulo), domText('p', '', `${video.tipo === 'short' ? 'Short' : 'Vídeo longo'} · ${video.status || 'status desconhecido'} · ${video.age_days} dias observados`)]), createElement('div', { className: 'header-actions' }, [domButton('Voltar à biblioteca', 'arrow-left', 'secondary', 'library-back')])]));
  root.appendChild(createElement('div', { className: 'metric-grid' }, [domMetric('Views atuais', video.views_display, `${video.daily_views} views/dia observado`), domMetric('Likes', video.likes_display, `taxa ${formatRate(video.score)}`), domMetric('Projeção em 1 semana', formatCount(projections['1_week']?.views), 'estimativa por ritmo atual', true), domMetric('Projeção em 1 mês', formatCount(projections['1_month']?.views), 'estimativa por ritmo atual', true)]));
  root.appendChild(createElement('section', { className: 'panel projection-panel' }, [domPanelHeader('Projeção de alcance', 'A projeção é uma linha de base, não uma promessa de crescimento.'), createElement('div', { className: 'projection-grid' }, [domMetric('Em 1 semana', formatCount(projections['1_week']?.views), 'ritmo médio'), domMetric('Em 1 mês', formatCount(projections['1_month']?.views), 'ritmo médio'), domMetric('Em 1 ano', formatCount(projections['1_year']?.views), 'ritmo médio')])]));
  const analysisText = analysis.resumo || analysis.summary || analysis.diagnostico || 'A análise refinada ainda não foi executada para este vídeo. Sincronize e rode a análise de conteúdo para preencher este diagnóstico.';
  const isAnalyzing = ['queued', 'running'].includes(manualAnalysisTask.status);
  const analysisContent = createElement('div', { className: 'library-analysis-content' }, [domText('p', 'library-analysis-text', typeof analysisText === 'string' ? analysisText : JSON.stringify(analysisText)), domText('small', 'library-analysis-note', `Status da análise: ${video.analysis_status || 'pendente'}`)]);
  const actionItems = [domButton(isAnalyzing ? 'Analisando...' : 'Analisar este vídeo', 'sparkles', 'lime', 'library-analyze-video', { 'data-video-id': video.video_id, disabled: isAnalyzing })];
  if (isAnalyzing) {
    const eta = manualAnalysisTask.eta_seconds == null ? 'calculando ETA...' : `ETA: ${formatElapsedSeconds(manualAnalysisTask.eta_seconds)}`;
    actionItems.push(createElement('div', { className: 'library-analysis-progress' }, [createElement('div', { className: 'progress-head' }, [domText('span', '', manualAnalysisTask.message || 'Processando análise'), domText('strong', '', `${manualAnalysisTask.progress || 0}%`)]), createElement('div', { className: 'progress-track' }, [createElement('span', { style: `width:${manualAnalysisTask.progress || 0}%` })]), domText('p', 'task-meta', eta)]));
  }
  analysisContent.appendChild(createElement('div', { className: `library-analysis-actions ${isAnalyzing ? 'is-running' : ''}` }, actionItems));
  const analysisPanel = createElement('section', { className: 'panel library-analysis-panel' }, [domPanelHeader('Análise refinada', 'Leitura própria do Growth Engine, separada dos números brutos do YouTube.'), analysisContent]);
  root.appendChild(analysisPanel);
  replaceView(root);
}
function isLiveJob(job) {
  return Boolean(job && ['uploading', 'queued', 'pending', 'running', 'processing', 'analyzing', 'rendering', 'publishing', 'scheduling', 'cancelling'].includes(job.status));
}
function renderJobProgress(job) {
  const candidatesFound = Number(job.candidatos_gerados ?? job.candidatos);
  const elapsedSeconds = jobElapsedSeconds(job);
  const etaSeconds = jobEtaSeconds(job, elapsedSeconds);
  const etaLabel = job.kind === 'captions' || job.tipo === 'caption_render' ? 'ETA estimado' : 'ETA';
  const telemetry = [
    Number.isFinite(candidatesFound) ? `Candidatos encontrados: ${candidatesFound}` : '',
    Number.isFinite(Number(job.validos)) ? `Válidos: ${job.validos}` : '',
    job.stage ? `Etapa: ${job.stage}` : '',
    job.device ? `Dispositivo: ${job.device}${job.fallback_reason ? ` (${job.fallback_reason})` : ''}` : '',
    Number.isFinite(elapsedSeconds) ? `Tempo: ${formatElapsedSeconds(elapsedSeconds)}` : '',
    Number.isFinite(Number(job.speed_x)) ? `Velocidade: ${job.speed_x}x` : '',
    Number.isFinite(etaSeconds) ? `${etaLabel}: ${formatElapsedSeconds(etaSeconds)}` : elapsedSeconds !== null ? `${etaLabel}: calculando` : '',
    Number.isFinite(Number(job.processed_audio_seconds)) && Number.isFinite(Number(job.audio_seconds)) ? `Áudio: ${formatElapsedSeconds(job.processed_audio_seconds)} / ${formatElapsedSeconds(job.audio_seconds)}` : '',
    Number.isFinite(Number(job.segments_processed)) ? `Segmentos: ${job.segments_accepted || 0}/${job.segments_processed}` : '',
  ].filter(Boolean).join(' · ');
  const message = job.status === 'queued' && job.message === 'Upload recebido' ? 'Aguardando fila de processamento' : job.message;
  const box = createElement('div', { className: 'progress-box' }, [createElement('div', { className: 'progress-head' }, [domText('span', '', message), domText('strong', '', `${job.progress || 0}%`)]), createElement('div', { className: 'progress-track' }, [createElement('span', { style: `width:${job.progress || 0}%` })]), telemetry ? domText('p', 'progress-telemetry', telemetry) : null]);
  if (job.cancelable !== false) box.appendChild(createElement('div', { className: 'progress-actions' }, [domButton('Cancelar processo', 'x', 'danger', 'cancel-job')]));
  return box;
}
function renderCuts() {
  const previousScrollY = window.scrollY;
  const openDetails = [...appView.querySelectorAll('details[open]')].map(details => ({
    videoId: details.dataset.videoId || '',
    cycleKey: details.dataset.cycleKey || '',
    publicationCutId: details.dataset.publicationCutId || '',
  }));
  const root = createElement('div', { className: 'view-card active' });
  root.appendChild(createElement('div', { className: 'page-header' }, [createElement('div', {}, [domText('span', 'eyebrow', 'Central / produção'), domText('h1', '', 'Revisar antes de renderizar.'), domText('p', '', 'Escolha um vídeo real, confira a transcrição ancorada e só então gere sugestões de corte.')]) ]));
  const intake = createElement('section', { className: 'panel media-intake' }, [domPanelHeader('Entrada de mídia', 'Processe um MP4 local ou force o download de um vídeo do YouTube.')]);
  const uploadForm = createElement('div', { className: 'media-intake-row' }, [createElement('input', { id: 'local-media-file', type: 'file', accept: '.mp4,.mkv,video/mp4,video/x-matroska' }), domButton('Enviar arquivo', 'upload', 'lime', 'upload-local')]);
  const localPathForm = createElement('div', { className: 'media-intake-row' }, [createElement('input', { id: 'local-media-path', type: 'text', placeholder: 'C:\\Videos\\meu-video.mp4' }), domButton('Usar arquivo local', 'file-video', 'secondary', 'local-path')]);
  const downloadForm = createElement('div', { className: 'media-intake-row' }, [createElement('input', { id: 'force-download-url', type: 'url', placeholder: 'https://www.youtube.com/watch?v=...' }), domButton('Forçar Download/Recorte', 'download', 'secondary', 'force-download')]);
  intake.append(uploadForm, localPathForm, downloadForm);
  root.appendChild(intake);
  const activeJob = [uploadProgress, cutJob, transcriptionJob].find(isLiveJob);
  const activeJobTargetsCuts = Array.isArray(activeJob?.cut_ids || activeJob?.cutIds) && (activeJob.cut_ids || activeJob.cutIds).length > 0;
  if (activeJob) root.appendChild(renderJobProgress(activeJob));
  if (cutJob?.status === 'failed') {
    const publicationFailure = cutJob.kind === 'publish' || cutJob.kind === 'publish-now';
    root.appendChild(createElement('div', { className: 'progress-box task-error' }, [
      domText('strong', '', publicationFailure ? 'A publicação dos cortes falhou' : 'A geração de cortes falhou'),
      domText('p', '', cutJob.message || (publicationFailure ? 'Não foi possível confirmar a publicação dos cortes.' : 'Não foi possível gerar os cortes.')),
      domText('p', '', publicationFailure ? 'A geração dos cortes é separada da publicação. Confira as notificações e o canal antes de tentar novamente; um upload pode ter sido aceito mesmo que o registro local tenha falhado.' : 'Confira o diagnóstico da curadoria e tente gerar novamente após corrigir a entrada ou a disponibilidade da IA.'),
    ]));
  }
  if (!activeJob || activeJobTargetsCuts) {
  const picker = createElement('section', { className: 'panel cut-source-picker' }, [
    domPanelHeader('1. Escolha o vídeo', 'Escolha o vídeo longo que você quer transformar em cortes curtos.'),
  ]);
  const sourceLabel = createElement('label', { className: 'cut-source-label' }, [
    domText('span', '', 'Vídeo selecionado'),
  ]);
  const select = createElement('select', { 'data-action': 'cut-source', 'aria-label': 'Escolha o vídeo para criar cortes' });
  const transcription = selectedCutSource?.transcription;
  const segments = transcription?.segments || [];
  cutSources.forEach(video => select.appendChild(createElement('option', { value: video.id, selected: selectedCutSource?.id === video.id ? 'true' : null, textContent: `${video.title} · ${video.views_display} views` })));
  if (cutSources.length) {
    sourceLabel.appendChild(select);
    picker.appendChild(sourceLabel);
    const sourceStatus = createElement('div', { className: 'cut-source-status' });
    const srtControls = createElement('div', { className: 'srt-upload-controls' }, [
      createElement('label', { className: 'srt-upload-label' }, [domText('span', '', 'Ou use uma transcrição pronta'), createElement('input', { id: 'srt-transcription-file', type: 'file', accept: '.srt,text/plain' })]),
      domButton('Usar arquivo SRT', 'file-up', 'secondary', 'upload-srt'),
    ]);
    if (segments.length) {
      const duration = Math.max(...segments.map(segment => Number(segment.fim) || 0));
      const contentSummary = selectedCutSource?.contentSummary || {};
      const summaryText = typeof contentSummary.summary === 'string' ? contentSummary.summary.trim() : '';
      const hasUsableSummary = Boolean(summaryText)
        && !['loading', 'unavailable'].includes(contentSummary.status)
        && !['Gerando resumo do conteúdo...', 'Resumo indisponível até a transcrição ser concluída.', 'Resumo de conteúdo indisponível no momento.'].includes(summaryText);
      sourceStatus.appendChild(createElement('div', { className: 'transcription-summary' }, [
        domText('strong', '', 'Transcrição pronta'),
        domText('span', '', `${segments.length} segmentos · ${formatElapsedSeconds(duration)} de áudio · cortes de ${cutDurationRange.min}s a ${cutDurationRange.max}s`),
        hasUsableSummary ? domText('p', '', summaryText) : null,
      ]));
      const editorialStatus = createElement('span', { className: `editorial-status ${selectedCutSource.has_editorial ? 'available' : 'unavailable'}`, role: 'status' }, [
        domIcon(selectedCutSource.has_editorial ? 'check-circle' : 'circle-help'),
        domText('span', '', selectedCutSource.has_editorial ? 'Editorial disponível' : 'Sem editorial'),
      ]);
      const transcriptionActions = [domButton('Exportar transcrição', 'download', 'secondary', 'export-transcription', { 'data-video-id': selectedCutSource.id }), domButton('Limpar cache da transcrição', 'refresh-cw', 'secondary', 'clear-transcription-cache', { 'data-video-id': selectedCutSource.id })];
      if (selectedCutSource.has_editorial) {
        transcriptionActions.push(domButton('Ler editorial', 'book-open', 'secondary', 'read-editorial-dossier', { 'data-video-id': selectedCutSource.id }));
        transcriptionActions.push(domButton('Apagar editorial', 'trash-2', 'danger', 'delete-editorial-dossier', { 'data-video-id': selectedCutSource.id }));
      } else {
        transcriptionActions.push(domButton('Gerar editorial', 'sparkles', 'lime', 'generate-editorial'));
      }
      transcriptionActions.push(editorialStatus);
      if (!cutJob || cutJob.status === 'needs_review' || cutJob.status === 'needs_review_fallback') transcriptionActions.unshift(domButton('Gerar cortes deste vídeo', 'scissors', 'lime', 'preview'));
      sourceStatus.appendChild(createElement('div', { className: 'cut-source-actions' }, transcriptionActions));
    } else {
      sourceStatus.appendChild(createElement('div', { className: 'evidence-row' }, [domText('span', '', 'Próximo passo'), domText('p', '', 'Este vídeo ainda não possui segmentos salvos. Execute a transcrição pelo pipeline antes de gerar uma prévia.')]));
      if (selectedCutSource && !transcriptionJob) sourceStatus.appendChild(createElement('div', { className: 'cut-source-actions' }, [domButton('Transcrever este vídeo', 'audio-lines', 'lime', 'transcribe')]));
    }
    sourceStatus.appendChild(srtControls);
    picker.appendChild(sourceStatus);
    root.appendChild(picker);
  } else {
    root.appendChild(domText('p', 'empty-state', 'Este perfil ainda não possui vídeos longos para corte.'));
  }
  const durationPanel = createElement('section', { className: 'panel cut-settings' }, [
    domPanelHeader('2. Escolha o tamanho dos cortes', 'Defina quanto tempo cada corte pode ter.'),
    createElement('div', { className: 'media-intake-row' }, [
      createElement('label', {}, ['Duração mínima', createElement('select', { id: 'cut-duration-min', 'data-action': 'cut-duration' }, [
        createElement('option', { value: '15', textContent: '15 segundos', selected: cutDurationRange.min === 15 ? 'true' : null }),
        createElement('option', { value: '30', textContent: '30 segundos', selected: cutDurationRange.min === 30 ? 'true' : null }),
        createElement('option', { value: '45', textContent: '45 segundos', selected: cutDurationRange.min === 45 ? 'true' : null }),
        createElement('option', { value: '60', textContent: '60 segundos', selected: cutDurationRange.min === 60 ? 'true' : null }),
      ])]),
      createElement('label', {}, ['Duração máxima', createElement('select', { id: 'cut-duration-max', 'data-action': 'cut-duration' }, [
        createElement('option', { value: '30', textContent: '30 segundos', selected: cutDurationRange.max === 30 ? 'true' : null }),
        createElement('option', { value: '60', textContent: '60 segundos', selected: cutDurationRange.max === 60 ? 'true' : null }),
        createElement('option', { value: '90', textContent: '90 segundos', selected: cutDurationRange.max === 90 ? 'true' : null }),
        createElement('option', { value: '120', textContent: '120 segundos', selected: cutDurationRange.max === 120 ? 'true' : null }),
      ])]),
      domText('span', 'progress-telemetry', `Faixa atual: ${cutDurationRange.min}s a ${cutDurationRange.max}s`),
    ]),
  ]);
  root.appendChild(durationPanel);
  const availableCaptionStyles = captionGallery.length ? captionGallery : [
    { style_id: 'clean', name: 'Clean', style: 'clean', font: 'Arial', size: 54, position: 'bottom', stroke_color: 'black', stroke_size: 3 },
    { style_id: 'bold', name: 'Bold', style: 'bold', font: 'Arial', size: 60, position: 'bottom', stroke_color: 'black', stroke_size: 4 },
    { style_id: 'highlight', name: 'Highlight', style: 'highlight', font: 'Arial', size: 56, position: 'bottom', stroke_color: 'black', stroke_size: 3, animation: 'karaoke' },
  ];
  const optionalStyle = createElement('select', { 'data-action': 'caption-default', 'data-caption-key': 'style' }, availableCaptionStyles.map(item => createElement('option', { value: item.style_id, selected: captionDefaults.style === item.style_id ? 'true' : null }, captionStyleLabel(item))));
  const optionalFont = createElement('select', { 'data-action': 'caption-default', 'data-caption-key': 'font' }, captionFonts.map(value => createElement('option', { value, selected: captionDefaults.font === value ? 'true' : null }, value)));
  const optionalSize = createElement('input', { type: 'range', min: '32', max: '160', step: '1', value: String(captionDefaults.size), 'data-action': 'caption-default', 'data-caption-key': 'size', 'aria-label': 'Tamanho padrão da legenda' });
  const optionalSizeValue = domText('output', 'caption-size-value', `${captionDefaults.size}px`);
  const optionalSingleLine = createElement('input', { type: 'checkbox', checked: captionDefaults.singleLine ? 'true' : null, 'data-action': 'caption-default', 'data-caption-key': 'singleLine', 'aria-label': 'Usar uma linha' });
  const optionalPosition = createElement('select', { 'data-action': 'caption-default', 'data-caption-key': 'position' }, [
    ['bottom', 'Embaixo'], ['center', 'Centro'], ['top', 'Em cima'],
  ].map(([value, label]) => createElement('option', { value, selected: captionDefaults.position === value ? 'true' : null }, label)));
  const optionalStrokeColor = createElement('select', { 'data-action': 'caption-default', 'data-caption-key': 'strokeColor' }, [
    ['#000000', 'Preto'], ['#FFFFFF', 'Branco'], ['#FF4B5B', 'Coral'],
  ].map(([value, label]) => createElement('option', { value, selected: captionDefaults.strokeColor === value ? 'true' : null }, label)));
  const optionalStrokeSize = createElement('select', { 'data-action': 'caption-default', 'data-caption-key': 'strokeSize' }, [0, 1, 2, 3, 4, 6, 8].map(value => createElement('option', { value: String(value), selected: captionDefaults.strokeSize === value ? 'true' : null }, `${value}px`)));
  const optionalPrimaryColorControl = createCaptionColorControl({ type: 'color', value: captionDefaults.primaryColor, 'data-action': 'caption-default', 'data-caption-key': 'primaryColor' });
  const optionalHighlightColorControl = createCaptionColorControl({ type: 'color', value: captionDefaults.highlightColor, 'data-action': 'caption-default', 'data-caption-key': 'highlightColor' });
  const optionalBackgroundColorControl = createCaptionColorControl({ type: 'color', value: captionDefaults.backgroundColor, 'data-action': 'caption-default', 'data-caption-key': 'backgroundColor' });
  const optionalPrimaryColor = optionalPrimaryColorControl.input;
  const optionalHighlightColor = optionalHighlightColorControl.input;
  const optionalBackgroundColor = optionalBackgroundColorControl.input;
  const optionalBackgroundAlpha = createElement('input', { type: 'range', min: '0', max: '100', step: '5', value: String(captionDefaults.backgroundAlpha), 'data-action': 'caption-default', 'data-caption-key': 'backgroundAlpha' });
  const optionalPreviewStage = createElement('div', { className: 'caption-preview-stage', role: 'img', 'aria-label': 'Preview da legenda padrão' });
  const optionalPreviewText = domText('span', 'caption-preview-text', 'A cidade muda quando a gente participa.');
  optionalPreviewStage.appendChild(optionalPreviewText);
  const optionalPreviewCut = allReviewCuts().find(cut => cut.caminho_saida || cut.output_path) || null;
  const applyOptionalPreviewPosition = setupCaptionPreview(optionalPreviewStage, optionalPreviewText, optionalPreviewCut, optionalPosition);
  const optionalPreviewStyles = {
    clean: { color: '#ffffff', weight: '400', shadow: '0 2px 3px rgba(0, 0, 0, .95)' },
    bold: { color: '#ffffff', weight: '800', shadow: '0 3px 0 #101010, 2px 0 0 #101010, -2px 0 0 #101010, 0 -2px 0 #101010' },
    highlight: { color: '#ffe45c', weight: '800', shadow: '0 3px 0 #101010, 2px 0 0 #101010, -2px 0 0 #101010, 0 -2px 0 #101010' },
  };
  const optionalStrokeColors = { black: '#000000', white: '#ffffff', coral: '#ff4b5b' };
  const updateOptionalPreview = () => {
    const selected = availableCaptionStyles.find(item => item.style_id === optionalStyle.value);
    const preset = optionalPreviewStyles[selected?.style || optionalStyle.value] || optionalPreviewStyles.clean;
    optionalPreviewText.style.fontFamily = `'${optionalFont.value}', sans-serif`;
    const scale = captionPreviewScale(optionalPreviewStage);
    optionalPreviewText.style.fontSize = `${Number(optionalSize.value) * scale}px`;
    fitSingleLineCaption(optionalPreviewStage, optionalPreviewText, Number(optionalSize.value) * scale);
    optionalSizeValue.textContent = `${optionalSize.value}px`;
    optionalPreviewText.style.fontWeight = preset.weight;
    optionalPreviewText.style.whiteSpace = optionalSingleLine.checked ? 'nowrap' : 'normal';
    optionalPreviewText.style.maxWidth = optionalSingleLine.checked ? 'none' : '88%';
    optionalPreviewText.style.color = optionalPrimaryColor.value || preset.color;
    const stroke = Number(optionalStrokeSize.value);
    const strokeColor = captionColorValue(optionalStrokeColor.value) || optionalStrokeColors.black;
    const scaledStroke = stroke * scale;
    const scaledShadow = scaleCaptionShadow(preset.shadow, scale);
    optionalPreviewText.style.textShadow = stroke ? `0 ${scaledStroke}px 0 ${strokeColor}, ${scaledStroke}px 0 0 ${strokeColor}, -${scaledStroke}px 0 0 ${strokeColor}, 0 -${scaledStroke}px 0 ${strokeColor}, ${scaledShadow}` : scaledShadow;
    applyOptionalPreviewPosition(optionalPosition.value);
    optionalPreviewStage.style.justifyContent = 'center';
    optionalPreviewStage.style.alignItems = 'center';
  };
  [optionalStyle, optionalFont, optionalSize, optionalSingleLine, optionalPosition, optionalStrokeColor, optionalStrokeSize, optionalPrimaryColor, optionalHighlightColor, optionalBackgroundColor, optionalBackgroundAlpha].forEach(control => control.addEventListener('change', updateOptionalPreview));
  optionalSize.addEventListener('input', updateOptionalPreview);
  optionalPreviewStage.addEventListener('caption-preview-resize', updateOptionalPreview);
  optionalPosition.addEventListener('change', () => { delete optionalPreviewText.dataset.positionX; delete optionalPreviewText.dataset.positionY; updateOptionalPreview(); });
  updateOptionalPreview();
  const captionOptionsContent = createElement('div', { className: 'caption-options-content', hidden: 'hidden' }, [
    createElement('div', { className: 'caption-option-grid' }, [
      createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Estilo padrão'), optionalStyle]),
      createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Fonte padrão'), optionalFont]),
      createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Tamanho padrão'), optionalSize, optionalSizeValue]),
      createElement('label', { className: 'cut-metadata-field caption-checkbox-field' }, [optionalSingleLine, domText('span', '', 'Uma linha')]),
      createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Posição padrão'), optionalPosition]),
      createElement('div', { className: 'caption-position-actions' }, [domButton('Centralizar legenda', 'crosshair', 'secondary', 'caption-center-preview'), domButton('Centralizar horizontalmente', 'move-horizontal', 'secondary', 'caption-center-horizontal')]),
      createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Cor do stroke'), optionalStrokeColor]),
      createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Espessura do stroke'), optionalStrokeSize]),
      createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Cor base'), optionalPrimaryColorControl.control]),
      createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Cor destaque'), optionalHighlightColorControl.control]),
      createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Cor do fundo'), optionalBackgroundColorControl.control]),
      createElement('label', { className: 'cut-metadata-field' }, [domText('span', '', 'Opacidade do fundo'), optionalBackgroundAlpha]),
    ]),
    createElement('div', { className: 'caption-preview-block' }, [domText('strong', '', 'Preview'), optionalPreviewStage]),
    createElement('div', { className: 'caption-gallery-import' }, [
      createElement('label', { className: 'caption-file-label' }, [domText('span', '', 'Galeria de estilos'), createElement('input', { id: 'caption-style-file', type: 'file', accept: '.json,application/json' })]),
      domButton('Importar estilo JSON', 'upload', 'secondary', 'import-caption-style'),
      createElement('label', { className: 'caption-file-label' }, [domText('span', '', 'Fonte externa'), createElement('input', { id: 'caption-font-file', type: 'file', accept: '.ttf,.otf,.ttc,font/ttf,font/otf' })]),
      domButton('Instalar fonte', 'type', 'secondary', 'import-caption-font'),
    ]),
  ]);
  const optionalPanel = createElement('section', { className: 'panel cut-optionals' }, [
    domPanelHeader('3. Opcionais', 'Escolha recursos adicionais para aplicar depois à produção dos cortes.'),
    domButton('Legendas automáticas', 'captions', 'secondary', 'toggle-caption-options', { 'aria-expanded': 'false', 'aria-controls': 'caption-options-content' }),
    captionOptionsContent,
  ]);
  captionOptionsContent.id = 'caption-options-content';
  root.appendChild(optionalPanel);
  }
  const candidateToggleAction = 'candidate-toggle';
  const candidateTitle = cutSuggestions.find(cut => cut.titulo)?.titulo || '';
  const candidateHook = cutSuggestions.find(cut => cut.gancho)?.gancho || '';
  const reviewCuts = allReviewCuts();
  const persistedPanel = reviewCuts.length ? createElement('section', { className: 'panel cut-review' }, [domPanelHeader('Cortes gerados', candidateTitle ? `Último título sugerido: ${candidateTitle}` : candidateHook ? `Gancho: ${candidateHook}` : 'Estado persistido de cada renderização')]) : null;
  if (persistedPanel) {
    const selectedToolbar = createElement('div', { id: 'selected-cuts-toolbar', className: 'selected-cuts-toolbar', hidden: selectedCandidateIds.size === 0 ? 'hidden' : null }, [
      domText('strong', 'selected-cuts-count', `${selectedCandidateIds.size} selecionado${selectedCandidateIds.size === 1 ? '' : 's'}`),
      domButton('Renderizar selecionados', 'scissors', 'secondary', 'render-selected-cuts'),
      domButton('Postar selecionados', 'send', 'lime', 'post-selected-cuts'),
      domButton('Agendar selecionados', 'calendar-plus', 'secondary', 'schedule-selected-cuts'),
      domButton('Excluir selecionados', 'trash-2', 'danger', 'delete-selected-cuts'),
    ]);
    persistedPanel.appendChild(selectedToolbar);
    persistedPanel.appendChild(renderReviewGroups(reviewCuts, candidateToggleAction));
  }
  const reviewJob = [cutJob, transcriptionJob].find(job => job?.status === 'needs_review' || job?.status === 'needs_review_fallback');
  if (reviewJob) {
      const diagnostics = reviewJob.diagnostics || parseJobDiagnostics(reviewJob);
      const analysis = diagnostics?.analysis;
      const editorialDiagnostics = analysis?.diagnostico || [];
      const accepted = analysis?.cortes?.length || 0;
      const candidates = analysis?.candidatos?.length || 0;
      const renderedCandidates = cutSuggestions.filter(cut => cut.status === 'concluido' && (cut.output_path || cut.caminho_saida)).length;
      const providerUnavailable = editorialDiagnostics.some(item => ['timeout_or_network', 'http_error', 'provider_disabled', 'editorial_unavailable'].includes(item.status));
      const detail = editorialDiagnostics.map(item => {
        const status = item.status === 'timeout_or_network' ? 'IA indisponível (timeout)' : item.status === 'http_error' ? `IA respondeu HTTP ${item.http_status || ''}`.trim() : item.status;
        if (providerUnavailable && status) return `${status}; ${renderedCandidates} candidato(s) local(is) renderizado(s) para revisão`;
        if (Number.isFinite(Number(item.aceitos))) return `${item.aceitos} corte(s) aceito(s) de ${item.candidatos || 0} candidato(s)`;
        return `${item.candidatos || 0} candidato(s) encontrado(s) neste bloco`;
      }).join(' · ');
      root.appendChild(createElement('div', { className: 'panel task-review-details' }, [
        domText('strong', '', providerUnavailable ? renderedCandidates ? `IA indisponível; ${renderedCandidates} candidato(s) local(is) renderizado(s) para revisão humana.` : 'IA indisponível; nenhum candidato local foi renderizado nesta rodada.' : `${accepted} corte(s) aprovado(s) automaticamente pela IA.`),
        domText('p', '', detail || 'O diagnóstico desta execução não possui detalhes.'),
        domText('p', '', renderedCandidates ? 'Os candidatos renderizados aparecem abaixo para aprovação humana.' : 'Não há candidatos renderizados para aprovação humana.'),
      ]));
  }
  if (persistedPanel) root.appendChild(persistedPanel);
  replaceView(root);
  root.querySelectorAll('details').forEach(details => {
    const matches = openDetails.some(open => (
      (open.publicationCutId && open.publicationCutId === details.dataset.publicationCutId)
      || (open.cycleKey && open.cycleKey === details.dataset.cycleKey && open.videoId === details.dataset.videoId)
      || (open.videoId && open.videoId === details.dataset.videoId && !details.dataset.cycleKey && !details.dataset.publicationCutId)
    ));
    if (matches) details.open = true;
  });
  window.scrollTo(0, previousScrollY);
}
function renderAutopsyPipeline() {
  const status = contentAnalysisStatus.status || 'idle';
  if (!['running', 'completed', 'failed'].includes(status)) return null;
  const progress = Number(contentAnalysisStatus.progress || 0);
  const processed = Number(contentAnalysisStatus.processed || 0);
  const message = status === 'completed'
    ? `${processed} vídeo(s) processado(s). Os resultados estão nas seções abaixo.`
    : contentAnalysisStatus.message || 'Preparando análise';
  const currentStage = message.startsWith('2.') ? 2 : message.startsWith('3.') ? 3 : 1;
  const stages = ['A extrair métricas do YouTube', 'A analisar transcrições de áudio', 'A cruzar padrões de roteiro'];
  const tracker = createElement('section', { className: 'autopsy-pipeline panel' }, [
    createElement('div', { className: 'autopsy-pipeline-head' }, [domText('div', '', status === 'completed' ? 'Última análise' : 'Análise em andamento'), domText('strong', '', status === 'running' ? `${progress}%` : status === 'completed' ? 'Concluída' : 'Falhou')]),
    createElement('div', { className: 'autopsy-pipeline-track' }, [createElement('span', { style: `width:${status === 'completed' ? 100 : progress}%` })]),
    domText('p', 'autopsy-pipeline-message', message),
  ]);
  const list = createElement('div', { className: 'autopsy-stages' });
  stages.forEach((label, index) => {
    const number = index + 1;
    const stageState = status === 'completed' || number < currentStage ? 'done' : number === currentStage ? 'active' : '';
    list.appendChild(createElement('div', { className: `autopsy-stage ${stageState}` }, [domText('span', 'autopsy-stage-number', `0${number}`), domText('span', '', label)]));
  });
  tracker.appendChild(list);
  if (status === 'failed') tracker.appendChild(domText('p', 'autopsy-error', `Falha: ${message}`));
  return tracker;
}
function renderAutopsyVideoCard(video, variant) {
  const detail = variant === 'top' ? (video.observations[0] || video.evidence[0] || 'Análise concluída; evidência textual ainda não registrada.') : (video.hypotheses[0] || video.observations[0] || video.error || 'Evidência insuficiente para determinar a causa.');
  const isPending = video.analysis_status !== 'concluida';
  const isProcessing = video.analysis_status === 'processando' || (contentAnalysisStatus.processing_video_ids || []).includes(video.id) || (contentAnalysisStatus.cache?.processing_video_ids || []).includes(video.id);
  const action = isProcessing
    ? domButton('Processando...', 'loader-circle', 'secondary', 'autopsy-analyze-video', { 'data-video-id': video.id, disabled: true, 'aria-label': 'Análise deste vídeo em andamento' })
    : isPending
      ? domButton('Analisar', 'microscope', 'secondary', 'autopsy-analyze-video', { 'data-video-id': video.id })
      : domText('span', 'autopsy-analysis-state', 'Análise concluída');
  return createElement('article', { className: `autopsy-video-card ${variant}` }, [
    createElement('div', { className: 'autopsy-video-card-head' }, [domText('span', 'autopsy-video-status', variant === 'top' ? 'Anatomia do sucesso' : 'Causa mortis'), domText('strong', '', video.views_display)]),
    domText('h3', '', video.title),
    domText('p', 'autopsy-video-detail', detail),
    createElement('div', { className: 'autopsy-video-meta' }, [domText('span', '', `${video.likes_rate == null ? '—' : `${video.likes_rate}%`} likes/views`), action]),
  ]);
}
function autopsyFormatLabel(format) {
  return { all: 'Geral', live: 'Lives', short: 'Shorts', video: 'Vídeos longos' }[format] || 'Geral';
}
function getAutopsyColumnItems(side) {
  const source = getAutopsySourceItems(side);
  if (side === 'top') return [...source].sort((left, right) => right.views - left.views).slice(0, 10);
  return [...source].filter(video => video.views > 0).sort((left, right) => left.views - right.views).slice(0, 10);
}
function getAutopsySourceItems(side) {
  const format = autopsyFilters[side] || 'all';
  return (autopsyData.videos || (side === 'top' ? autopsyData.top_performers : autopsyData.flops) || []).filter(video => format === 'all' || video.format === format);
}
function renderAutopsyColumn(side) {
  const isTop = side === 'top';
  const items = getAutopsyColumnItems(side);
  const pendingItems = items.filter(video => video.analysis_status !== 'concluida' && video.analysis_status !== 'processando');
  const column = createElement('div', { className: `autopsy-column ${isTop ? 'success' : 'failure'}` }, [
    createElement('div', { className: 'autopsy-column-header' }, [
      createElement('div', {}, [domText('h3', '', isTop ? 'Top performers' : 'Flops'), domText('p', 'autopsy-column-note', isTop ? 'Anatomia do sucesso' : 'Causa mortis provável')]),
      createElement('select', { className: 'autopsy-format-filter', 'data-action': 'autopsy-filter', 'data-autopsy-side': side, 'aria-label': `Filtrar ${isTop ? 'Top performers' : 'Flops'}` }, [
        createElement('option', { value: 'all', selected: autopsyFilters[side] === 'all' ? 'true' : null, textContent: 'Geral' }),
        createElement('option', { value: 'live', selected: autopsyFilters[side] === 'live' ? 'true' : null, textContent: 'Lives' }),
        createElement('option', { value: 'short', selected: autopsyFilters[side] === 'short' ? 'true' : null, textContent: 'Shorts' }),
        createElement('option', { value: 'video', selected: autopsyFilters[side] === 'video' ? 'true' : null, textContent: 'Vídeos longos' }),
      ]),
    ]),
    pendingItems.length ? domButton(`Analisar todos os pendentes (${pendingItems.length})`, 'microscope', 'secondary autopsy-pending-button', 'autopsy-analyze-pending', { 'data-autopsy-side': side }) : null,
  ]);
  if (items.length) items.forEach(video => column.appendChild(renderAutopsyVideoCard(video, isTop ? 'top' : 'flop')));
  else column.appendChild(domText('p', 'autopsy-empty', `Nenhum vídeo encontrado em ${autopsyFormatLabel(autopsyFilters[side])}.`));
  return createElement('div', { className: 'autopsy-column-wrap' }, [domText('strong', 'autopsy-column-caption', isTop ? 'O que deu certo' : 'O que deu errado'), column]);
}
function renderAutopsy() {
  const root = createElement('div', { className: 'view-card active autopsy-view' });
  const metrics = autopsyData.metrics || {};
  const semantic = autopsyData.semantic || {};
  const isRunning = contentAnalysisStatus.status === 'running';
  const headerCopy = createElement('div', {}, [domText('span', 'eyebrow', 'Central / autópsia'), domText('h1', '', 'O canal por baixo da superfície.'), domText('p', '', 'A Autópsia compara o desempenho dos seus vídeos e lê as transcrições dos itens escolhidos. Ela organiza evidências observáveis, diferenças entre formatos e hipóteses testáveis para orientar os próximos conteúdos.'), createElement('div', { className: 'header-actions autopsy-header-actions' }, [domButton(isRunning ? 'Análise em curso...' : 'Escolher vídeos para analisar', isRunning ? 'loader-circle' : 'microscope', 'lime', 'autopsy')])]);
  root.appendChild(createElement('div', { className: 'page-header autopsy-header' }, [headerCopy]));
  const pipeline = renderAutopsyPipeline();
  if (pipeline) root.appendChild(pipeline);
  const metricGrid = createElement('div', { className: 'autopsy-metric-grid' });
  [['Vídeos na base', metrics.total || 0, 'histórico disponível'], ['Transcrições lidas', metrics.transcribed || 0, 'texto disponível'], ['Análises concluídas', metrics.analyzed || 0, 'evidência revisada'], ['Views no top 3', formatCount(metrics.top_views || 0), 'amostra dos melhores']].forEach(([label, value, note]) => metricGrid.appendChild(createElement('article', { className: 'autopsy-metric' }, [domText('span', '', label), domText('strong', '', String(value)), domText('small', '', note)])));
  root.appendChild(metricGrid);
  const anatomy = createElement('section', { className: 'autopsy-section' }, [createElement('div', { className: 'section-title' }, [domText('h2', '', 'Dissecação')])]);
  const split = createElement('div', { className: 'autopsy-split' }, [renderAutopsyColumn('top'), renderAutopsyColumn('flop')]);
  anatomy.appendChild(split);
  root.appendChild(anatomy);
  const semanticPanel = createElement('section', { className: 'autopsy-semantic panel' }, [domPanelHeader('O que a IA leu', 'Padrões extraídos das transcrições salvas, separados de causalidade.')]);
  const semanticGrid = createElement('div', { className: 'autopsy-semantic-grid' }, [createElement('div', {}, [domText('span', 'autopsy-label', 'Estrutura de guião recorrente'), domText('strong', '', semantic.structure || 'Aguardando dados')]), createElement('div', {}, [domText('span', 'autopsy-label', 'Evidências literais'), domText('p', '', semantic.evidence?.[0] || 'Nenhum trecho analisado ainda.')]), createElement('div', {}, [domText('span', 'autopsy-label', 'Hipóteses para testar'), domText('p', '', semantic.hypotheses?.[0] || 'A autópsia irá separar hipóteses de fatos observáveis.')])]);
  semanticPanel.appendChild(semanticGrid);
  root.appendChild(semanticPanel);
  const ideaButton = domButton(opportunityTask.status === 'running' ? 'Gerando ideias...' : 'Gerar ideias com estes padrões', opportunityTask.status === 'running' ? 'loader-circle' : 'sparkles', 'lime', 'generate-opportunities', { disabled: opportunityTask.status === 'running' });
  const ideaProgress = renderOpportunityProgress();
  const ideaPanel = createElement('section', { className: 'autopsy-action-panel panel' }, [createElement('div', {}, [domText('span', 'eyebrow', 'Depois da análise'), domText('h2', '', 'O que fazer com este resultado?'), domText('p', '', 'Leia os cards de sucesso e falha, confira as evidências literais e use as hipóteses para criar o próximo teste.')]), ideaButton]);
  if (ideaProgress) ideaPanel.appendChild(ideaProgress);
  root.appendChild(ideaPanel);
  replaceView(root);
}
function renderSuggestions() {
  const root = createElement('div', { className: 'view-card active' });
  root.appendChild(createElement('div', { className: 'page-header' }, [createElement('div', {}, [domText('span', 'eyebrow', 'Central / próximos vídeos'), domText('h1', '', 'Ideias que nascem dos seus dados.'), domText('p', '', 'Sugestões tratadas como hipóteses de produção.')]), createElement('div', { className: 'header-actions' }, [domButton('Gerar sugestões', 'sparkles', 'lime', 'generate-opportunities')])]));
  root.appendChild(domText('div', 'panel empty-state', 'Gere sugestões dos Top 15 para carregar pautas ancoradas na Autópsia.'));
  replaceView(root);
}
function renderSettings() {
  const root = createElement('div', { className: 'view-card active' });
  root.appendChild(createElement('div', { className: 'page-header' }, [createElement('div', {}, [domText('span', 'eyebrow', 'Central / configurações'), domText('h1', '', 'Controle seu contexto.'), domText('p', '', 'Use a localização para encontrar eventos e notícias relevantes sem inferir seu endereço.')]), createElement('div', { className: 'header-actions' }, [domButton('Conectar Google', 'link', 'lime', 'connect-google')])]));
  const form = createElement('section', { className: 'panel location-panel' }, [domPanelHeader('Radar local', 'Você pode alterar esses dados quando quiser.')]);
  const fields = createElement('div', { className: 'location-form' });
  [['bairro', 'Bairro', 'Ex.: Centro'], ['cidade', 'Cidade', 'Ex.: São Paulo'], ['estado', 'Estado', 'Ex.: SP']].forEach(([id, label, placeholder]) => {
    const input = createElement('input', { id: `location-${id}`, value: locationSettings[id] || '', placeholder });
    if (id === 'estado') input.maxLength = 2;
    fields.appendChild(createElement('label', {}, [label, input]));
  });
  fields.appendChild(domButton('Salvar localização', 'map-pin', 'lime', 'save-location'));
  form.appendChild(fields);
  root.appendChild(form);
  replaceView(root);
}
function renderAdmin() {
  if (!isAdmin) return render('overview');
  const root = createElement('div', { className: 'view-card active' });
  root.appendChild(createElement('div', { className: 'page-header' }, [createElement('div', {}, [domText('span', 'eyebrow', 'Sistema / manutenção'), domText('h1', '', 'Painel Admin'), domText('p', '', 'Operações de manutenção do banco, da fila e dos artefatos temporários.')])]));
  const actions = createElement('div', { className: 'admin-actions panel' });
  [['clear-cache', 'Limpar cache', 'trash-2', 'Remove temporários e caches de transcrição órfãos.'], ['reset-jobs', 'Resetar fila', 'rotate-ccw', 'Cancela jobs presos e libera estados pendentes.'], ['clear-finished-jobs', 'Limpar jobs finalizados', 'broom', 'Remove jobs concluídos, falhos ou cancelados; jobs ativos são preservados.'], ['vacuum-db', 'Otimizar banco', 'database', 'Executa VACUUM no SQLite.'], ['restart-server', 'Reiniciar servidor', 'refresh-cw', 'Reinicia o processo web e recupera estados antigos como interrompidos.']].forEach(([action, label, iconName, description]) => {
    actions.appendChild(createElement('article', { className: 'admin-action' }, [domButton(label, iconName, 'lime', `admin-${action}`), domText('p', '', description)]));
  });
  root.appendChild(actions);
  replaceView(root);
}
async function runAdminAction(action, message) {
  if (!isAdmin || !window.confirm(`Confirmar: ${message}?`)) return;
  try {
    const response = await fetch(`/api/admin/${action}`, { method: 'POST' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Operação não autorizada.');
    const detail = action === 'clear-cache' ? `${payload.removidos || 0} arquivo(s) removido(s).` : action === 'reset-jobs' ? `${payload.cancelados || 0} job(s) cancelado(s).` : action === 'clear-finished-jobs' ? `${payload.removidos || 0} job(s) removido(s).` : action === 'restart-server' ? 'A página será recarregada quando o servidor voltar.' : 'Banco otimizado com sucesso.';
    showToast(`${message} concluído. ${detail}`);
    if (action === 'restart-server') window.setTimeout(() => window.location.reload(), 1800);
  } catch (error) {
    showToast(`Falha: ${error.message}`);
  }
}
function renderSimple(title, eyebrow, text) {
  const root = createElement('div', { className: 'view-card active' });
  root.appendChild(createElement('div', { className: 'page-header' }, [createElement('div', {}, [domText('span', 'eyebrow', `Central / ${eyebrow}`), domText('h1', '', title), domText('p', '', text)])]));
  root.appendChild(domText('div', 'panel empty-state', 'Módulo em preparação.'));
  replaceView(root);
}

function render(view = state.view) { state.view = view; breadcrumb.textContent = labels[view] || view; ({ overview: renderOverview, ranking: renderRanking, autopsy: renderAutopsy, suggestions: renderSuggestions, radar: renderRadar, opportunities: renderOpportunities, cuts: renderCuts, library: renderLibrary, publishing: renderPublishing, settings: renderSettings, admin: renderAdmin }[view] || renderOverview)(); refreshIcons(); if (view === 'autopsy') { loadAutopsy(); loadOpportunityTask(); fetch('/api/content-analysis/status').then(response => response.json()).then(payload => { contentAnalysisStatus = payload; renderAutopsy(); refreshIcons(); if (payload.status === 'running') pollContentAnalysis(); }); } }

document.addEventListener('change', (event) => { const duration = event.target.closest('[data-action="cut-duration"]'); if (duration) { const minimum = Number(document.querySelector('#cut-duration-min')?.value || cutDurationRange.min); const maximum = Number(document.querySelector('#cut-duration-max')?.value || cutDurationRange.max); if (minimum > maximum) { showToast('A duração mínima não pode ser maior que a máxima.'); renderCuts(); return; } cutDurationRange = { min: minimum, max: maximum }; renderCuts(); } const select = event.target.closest('[data-action="cut-source"]'); if (select) selectCutSource(select.value); const librarySelect = event.target.closest('[data-action="library-sort"]'); if (librarySelect) { librarySort = librarySelect.value; renderLibrary(); return; } const candidate = event.target.closest('[data-action="candidate-toggle"]'); if (candidate) { const cutId = Number(candidate.dataset.cutId); if (candidate.checked) selectedCandidateIds.add(cutId); else selectedCandidateIds.delete(cutId); renderCuts(); } });
document.addEventListener('change', (event) => { const captionDefault = event.target.closest('[data-action="caption-default"]'); if (!captionDefault) return; const key = captionDefault.dataset.captionKey; captionDefaults[key] = ['size', 'strokeSize', 'backgroundAlpha'].includes(key) ? Number(captionDefault.value) : key === 'singleLine' ? captionDefault.checked : captionDefault.value; });
document.addEventListener('input', (event) => { const captionDefault = event.target.closest('[data-action="caption-default"]'); if (!captionDefault) return; if (captionDefault.dataset.captionKey === 'size') captionDefaults.size = Number(captionDefault.value); });
document.addEventListener('click', (event) => {
  const swatch = event.target.closest('[data-caption-color]');
  if (!swatch) return;
  const input = swatch.closest('.caption-color-control')?.querySelector('input[type="color"]');
  if (!input) return;
  input.value = swatch.dataset.captionColor;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
});
document.addEventListener('click', (event) => {
  const centerCaption = event.target.closest('[data-action="caption-center-preview"]');
  if (!centerCaption) return;
  const scope = centerCaption.closest('.caption-modal-backdrop, .caption-options-content, .view-card') || document;
  const previewText = scope.querySelector('.caption-preview-text');
  const position = scope.querySelector('#caption-position-select, [data-caption-key="position"]');
  if (previewText && position) {
    previewText.dataset.positionX = '50';
    previewText.dataset.positionY = '50';
    position.value = 'center';
    position.dispatchEvent(new Event('change', { bubbles: true }));
  }
});
document.addEventListener('click', (event) => {
  const centerCaptionHorizontal = event.target.closest('[data-action="caption-center-horizontal"]');
  if (!centerCaptionHorizontal) return;
  const scope = centerCaptionHorizontal.closest('.caption-modal-backdrop, .caption-options-content, .view-card') || document;
  const previewText = scope.querySelector('.caption-preview-text');
  if (previewText) {
    previewText.dataset.positionX = '50';
    previewText.style.left = '50%';
  }
});
document.addEventListener('change', (event) => { const filter = event.target.closest('[data-action="autopsy-filter"]'); if (!filter) return; autopsyFilters[filter.dataset.autopsySide] = filter.value; renderAutopsy(); refreshIcons(); });
document.addEventListener('click', (event) => { const nav = event.target.closest('[data-view]'); if (nav) { document.querySelectorAll('.nav-item').forEach(item => item.classList.toggle('active', item === nav)); render(nav.dataset.view); renderDynamicInsights(); if (nav.dataset.view === 'ranking') loadRanking(); if (nav.dataset.view === 'radar') loadRadar(); if (nav.dataset.view === 'opportunities') loadOpportunities(); if (nav.dataset.view === 'cuts') loadCutSources(); if (nav.dataset.view === 'publishing') loadScheduled(); if (nav.dataset.view === 'settings') loadProfiles(); return; } const actionElement = event.target.closest('[data-action]'); const action = actionElement?.dataset.action; if (!action) return; if (action === 'toggle-theme') { const nextTheme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'; document.documentElement.dataset.theme = nextTheme; localStorage.setItem('growth-engine-theme', nextTheme); clearElement(actionElement); actionElement.appendChild(domIcon(nextTheme === 'dark' ? 'sun' : 'moon')); refreshIcons(); } else if (action === 'save-location') saveLocationSettings(); else if (action === 'settings') { render('settings'); loadProfiles(); } else if (action === 'opportunities') loadOpportunities(); else if (action === 'profile-rebuild') startProfileRebuild(); else if (action === 'briefing') { fetch(`/api/opportunities/${actionElement.dataset.opportunityId}/briefing`).then(response => response.json()).then(briefing => showToast(`Briefing: ${briefing.titulo_provisorio || 'carregado'}`)); } else if (action === 'cuts') { render('cuts'); loadCutSources(); } else if (action === 'ranking') { render('ranking'); loadRanking(); } else if (action === 'ranking-filter') loadRanking(actionElement.dataset.rankingType); else if (action === 'scheduled') loadScheduled(); else if (action === 'connect-google') window.location.href = '/oauth/google/start'; else if (action === 'sync') startSync(); else if (action === 'preview') generateCutPreview(); else if (action === 'transcribe') runTranscription(); else if (action === 'approve') showToast('Corte aprovado e enviado para a fila de renderização.'); else if (action === 'reject') showToast('Corte rejeitado. A decisão será registrada.'); else if (action === 'autopsy') startContentAnalysis(); else if (action === 'suggest') showToast('Geração de sugestões enfileirada.'); });

document.addEventListener('click', (event) => { const notificationAction = event.target.closest('[data-action="notifications"]'); if (notificationAction) toggleNotifications(); const readAction = event.target.closest('[data-action="read-notification"]'); if (readAction) readNotification(readAction.dataset.notificationId); const searchAction = event.target.closest('[data-action="search-open"]'); if (searchAction) openSearch(); const resultAction = event.target.closest('[data-action="search-result"]'); if (resultAction) { document.querySelector('#search-panel')?.remove(); render(resultAction.dataset.resultAction); if (resultAction.dataset.resultAction === 'ranking') loadRanking(); if (resultAction.dataset.resultAction === 'opportunities') loadOpportunities(); } });

document.addEventListener('click', (event) => { if (event.target.closest('[data-action="generate-opportunities"]')) generateOpportunities(); });
document.addEventListener('click', (event) => { const action = event.target.closest('[data-action="library-analyze-video"]'); if (action) analyzeLibraryVideo(action.dataset.videoId); });
document.addEventListener('click', (event) => {
  const action = event.target.closest('[data-action="autopsy-analyze-video"], [data-action="autopsy-analyze-pending"]');
  if (!action) return;
  if (action.dataset.action === 'autopsy-analyze-video') {
    analyzeAutopsySelection([action.dataset.videoId]);
    return;
  }
  const items = getAutopsyColumnItems(action.dataset.autopsySide).filter(video => !['concluida', 'processando'].includes(video.analysis_status));
  if (items.length) analyzeAutopsySelection(items.map(video => video.id));
});
document.addEventListener('click', (event) => { if (event.target.closest('[data-action="clear-read"]')) clearReadNotifications(); });
document.addEventListener('click', (event) => { if (event.target.closest('[data-action="read-all-notifications"]')) readAllNotifications(); });
document.addEventListener('click', (event) => { if (event.target.closest('[data-action="radar-refresh"]')) loadRadar(); });
document.addEventListener('click', (event) => { if (event.target.closest('[data-action="close-briefing"]')) document.querySelector('#briefing-panel')?.remove(); });
document.addEventListener('click', (event) => { const briefingAction = event.target.closest('[data-action="briefing"]'); if (briefingAction) showBriefingPanel(briefingAction.dataset.opportunityId); });
document.addEventListener('click', (event) => { if (event.target.closest('[data-action="upload-local"]')) uploadLocalMedia(); if (event.target.closest('[data-action="local-path"]')) useLocalPathMedia(); if (event.target.closest('[data-action="force-download"]')) forceDownloadMedia(); if (event.target.closest('[data-action="upload-srt"]')) uploadSrtTranscription(); });
document.addEventListener('click', (event) => {
  const projectionFilter = event.target.closest('[data-action="overview-projection-period"]');
  if (projectionFilter) {
    projectionPeriod = projectionFilter.dataset.projectionPeriod || '1_month';
    renderOverview();
    refreshIcons();
    return;
  }
  const filter = event.target.closest('[data-action="library-filter"]');
  if (filter) {
    libraryFilter = filter.dataset.libraryFilter || 'all';
    loadLibrary();
    return;
  }
  const detail = event.target.closest('[data-action="library-video-detail"]');
  if (detail && !event.target.closest('[data-action="library-related-video"]') && !event.target.closest('[data-action="library-retry-related"]')) {
    loadLibraryDetail(detail.dataset.videoId);
    return;
  }
  if (event.target.closest('[data-action="library-back"]')) {
    libraryDetail = null;
    renderLibrary();
    return;
  }
  const libraryNav = event.target.closest('[data-view="library"]');
  if (libraryNav) loadLibrary();
  const retryRelated = event.target.closest('[data-action="library-retry-related"]');
  if (retryRelated) {
    fetch('/api/library/related-video', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ short_video_id: retryRelated.dataset.shortVideoId, related_video_id: retryRelated.dataset.relatedVideoId }),
    }).then(response => response.json().then(payload => ({ response, payload }))).then(({ response, payload }) => {
      if (!response.ok) throw new Error(payload.error || 'Não foi possível reenviar a relação.');
      showToast('Retry do vídeo relacionado enviado ao YouTube Studio.');
      loadNotifications();
      loadLibrary();
    }).catch(error => showToast(error.message));
    return;
  }
  const relatedAction = event.target.closest('[data-action="library-related-video"]');
  if (!relatedAction) return;
  openRelatedVideoPicker().then(video => {
    if (!video) return null;
    return fetch('/api/library/related-video', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ short_video_id: relatedAction.dataset.shortVideoId, ...(video.no_related_video ? { no_related_video: true } : { related_video_id: video.video_id }) }) });
  }).then(response => {
    if (response && !response.ok) throw new Error('Não foi possível salvar a relação.');
    if (response) {
      showToast('Vídeo relacionado enviado para aplicação no YouTube Studio.');
      loadNotifications();
      loadLibrary();
    }
  }).catch(error => showToast(error.message));
});
document.addEventListener('click', (event) => {
  if (event.target.closest('[data-action="render-selected-cuts"]')) renderSelectedCuts();
  if (event.target.closest('[data-action="post-selected-cuts"]')) postSelectedCuts();
  if (event.target.closest('[data-action="delete-selected-cuts"]')) deleteSelectedCuts();
  const scheduleSelected = event.target.closest('[data-action="schedule-selected-cuts"]');
  if (scheduleSelected) scheduleCuts([...selectedCandidateIds], 'cortes selecionados');
  const selectCycle = event.target.closest('[data-action="select-cycle-cuts"]');
  if (selectCycle) toggleCycleCuts(selectCycle.dataset.cutIds.split(',').map(Number).map(id => allReviewCuts().find(cut => Number(cut.cut_id || cut.id) === id)).filter(Boolean));
  const scheduleCycle = event.target.closest('[data-action="schedule-cycle-cuts"]');
  if (scheduleCycle) scheduleCuts(scheduleCycle.dataset.cutIds.split(',').map(Number), 'cortes do ciclo');
  const captionCycle = event.target.closest('[data-action="caption-cycle-cuts"]');
  if (captionCycle) {
    const cuts = captionCycle.dataset.cutIds.split(',').map(Number).map(id => allReviewCuts().find(cut => Number(cut.cut_id || cut.id) === id)).filter(Boolean);
    if (cuts.length >= 2) openCaptionDialog(cuts[0], cuts);
  }
});
document.addEventListener('click', (event) => {
  const selectionButton = event.target.closest('[data-action="candidate-toggle-button"]');
  if (selectionButton) {
    const cutId = Number(selectionButton.dataset.cutId);
    const selected = !selectedCandidateIds.has(cutId);
    if (selected) selectedCandidateIds.add(cutId);
    else selectedCandidateIds.delete(cutId);
    selectionButton.classList.toggle('selected', selected);
    selectionButton.classList.toggle('secondary', !selected);
    selectionButton.setAttribute('aria-pressed', String(selected));
    selectionButton.setAttribute('aria-label', selected ? 'Remover da seleção para postagem' : 'Selecionar para postagem');
    selectionButton.title = selected ? 'Remover da seleção para postagem' : 'Selecionar para postagem';
    clearElement(selectionButton);
    selectionButton.append(domIcon(selected ? 'circle-check' : 'circle'), selected ? 'Selecionado' : 'Selecionar');
    refreshIcons();
    syncSelectionButtons();
    return;
  }
  const editButton = event.target.closest('[data-action="edit-cut"]');
  if (editButton) { const cut = allReviewCuts().find(item => Number(item.cut_id || item.id) === Number(editButton.dataset.cutId)); if (cut) openCutEditor(cut); return; }
  const saveMetadataButton = event.target.closest('[data-action="save-cut-metadata"]');
  if (saveMetadataButton) { saveCutMetadata(Number(saveMetadataButton.dataset.cutId)); return; }
  const regenerateMetadataButton = event.target.closest('[data-action="regenerate-cut-metadata"]');
  if (regenerateMetadataButton) { regenerateCutMetadata(Number(regenerateMetadataButton.dataset.cutId), regenerateMetadataButton.dataset.field, regenerateMetadataButton); return; }
  if (event.target.closest('[data-action="close-cut-editor"]')) { closeCutEditor(); return; }
  const cycleButton = event.target.closest('[data-action="delete-cut-cycle"]');
  if (cycleButton) { deleteCutCycle(cycleButton.dataset.videoId, cycleButton.dataset.roundName); return; }
  const replaceCycleButton = event.target.closest('[data-action="replace-cycle-metadata"]');
  if (replaceCycleButton) { replaceCycleMetadata(replaceCycleButton.dataset.jobId, Number(replaceCycleButton.dataset.count || 0)); return; }
  const renderButton = event.target.closest('[data-action="render-cut"]');
  if (renderButton) { renderSingleCut(Number(renderButton.dataset.cutId)); return; }
  const captionButton = event.target.closest('[data-action="caption-cut"]');
  if (captionButton) { const cut = allReviewCuts().find(item => Number(item.cut_id || item.id) === Number(captionButton.dataset.cutId)); if (cut) openCaptionDialog(cut); return; }
  const transcriptButton = event.target.closest('[data-action="read-cut-transcript"]');
  if (transcriptButton) { const cut = allReviewCuts().find(item => Number(item.cut_id || item.id) === Number(transcriptButton.dataset.cutId)); if (cut) openCutTranscriptReader(cut); return; }
  const previewButton = event.target.closest('[data-action="open-cut-preview"]');
  if (previewButton) { const cut = allReviewCuts().find(item => Number(item.cut_id || item.id) === Number(previewButton.dataset.cutId)); if (cut) openCutPreview(cut); return; }
  const fullscreenButton = event.target.closest('[data-action="fullscreen-cut-preview"]');
  if (fullscreenButton) {
    const preview = fullscreenButton.closest('.cut-preview');
    const cut = allReviewCuts().find(item => Number(item.cut_id || item.id) === Number(fullscreenButton.dataset.cutId));
    if (preview?.requestFullscreen) preview.requestFullscreen().catch(() => {
      if (cut) openCutPreview(cut);
    });
    else if (cut) openCutPreview(cut);
    return;
  }
  const generateCaptionsButton = event.target.closest('[data-action="generate-captions"]');
  if (generateCaptionsButton) {
    const options = {
      style_id: document.querySelector('#caption-style-select')?.value || 'clean',
      style: (captionGallery.find(item => item.style_id === (document.querySelector('#caption-style-select')?.value || 'clean')) || {}).style || document.querySelector('#caption-style-select')?.value || 'clean',
      font: document.querySelector('#caption-font-select')?.value || 'Arial',
      size: Number(document.querySelector('#caption-size-select')?.value || 54),
      position: document.querySelector('#caption-position-select')?.value || 'bottom',
      stroke_color: document.querySelector('#caption-stroke-color-select')?.value || 'black',
      stroke_size: Number(document.querySelector('#caption-stroke-size-select')?.value || 3),
      primary_color: document.querySelector('#caption-primary-color-select')?.value || '#FFFFFF',
      highlight_color: document.querySelector('#caption-highlight-color-select')?.value || '#FFE45C',
      background_color: document.querySelector('#caption-background-color-select')?.value || '#000000',
      background_alpha: Number(document.querySelector('#caption-background-alpha-select')?.value || 50),
      uma_linha: Boolean(document.querySelector('#caption-single-line-select')?.checked),
      position_y: Number(document.querySelector('#caption-position-select')?.closest('.caption-modal-backdrop')?.querySelector('.caption-preview-text')?.dataset.positionY || NaN),
      position_x: Number(document.querySelector('#caption-position-select')?.closest('.caption-modal-backdrop')?.querySelector('.caption-preview-text')?.dataset.positionX || NaN),
    };
    const cutIds = generateCaptionsButton.dataset.cutIds.split(',').map(Number).filter(Boolean);
    generateCaptionsForCuts(cutIds, options, generateCaptionsButton.closest('.caption-modal-backdrop'));
    return;
  }
  const captionOptionalToggle = event.target.closest('[data-action="caption-optional-toggle"]');
  if (captionOptionalToggle) { cutOptionalSettings.captions = captionOptionalToggle.checked; return; }
  const captionOptionsToggle = event.target.closest('[data-action="toggle-caption-options"]');
  if (captionOptionsToggle) {
    const content = document.getElementById(captionOptionsToggle.getAttribute('aria-controls'));
    const expanded = captionOptionsToggle.getAttribute('aria-expanded') === 'true';
    captionOptionsToggle.setAttribute('aria-expanded', expanded ? 'false' : 'true');
    if (content) content.hidden = expanded;
    return;
  }
  if (event.target.closest('[data-action="import-caption-style"]')) { importCaptionStyle(); return; }
  if (event.target.closest('[data-action="import-caption-font"]')) { importCaptionFont(); return; }
  if (event.target.closest('[data-action="close-caption-dialog"]')) { document.querySelector('.caption-modal-backdrop')?.remove(); return; }
  if (event.target.closest('[data-action="close-cut-preview"]')) { document.querySelector('.cut-preview-backdrop')?.remove(); return; }
  const deleteButton = event.target.closest('[data-action="delete-cut"]');
  if (deleteButton) { deleteCut(Number(deleteButton.dataset.cutId)); return; }
  const scheduleButton = event.target.closest('[data-action="schedule-cut"]');
  if (scheduleButton) scheduleCut(Number(scheduleButton.dataset.cutId));
});
document.addEventListener('click', (event) => { if (event.target.closest('[data-action="cancel-job"]')) cancelActiveJob(); });
document.addEventListener('click', (event) => {
  const clearTranscriptionButton = event.target.closest('[data-action="clear-transcription-cache"]');
  if (clearTranscriptionButton) clearTranscriptionCache(clearTranscriptionButton.dataset.videoId);
  const exportTranscriptionButton = event.target.closest('[data-action="export-transcription"]');
  if (exportTranscriptionButton) exportTranscription(exportTranscriptionButton.dataset.videoId);
  const readEditorialButton = event.target.closest('[data-action="read-editorial-dossier"]');
  if (readEditorialButton) openEditorialDossier(readEditorialButton.dataset.videoId);
  const deleteEditorialButton = event.target.closest('[data-action="delete-editorial-dossier"]');
  if (deleteEditorialButton) deleteEditorialDossier(deleteEditorialButton.dataset.videoId);
});
document.addEventListener('click', (event) => {
  if (event.target.closest('[data-action="generate-editorial"]')) generateEditorial();
});
document.addEventListener('click', (event) => {
  const option = event.target.closest('[data-action="profile-option"]');
  if (!option) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  selectProfile(option.dataset.profileId);
}, true);
document.addEventListener('click', (event) => {
  const action = event.target.closest('[data-action="profile-add"], [data-action="profile-reauthorize"], [data-action="profile-disconnect"], [data-action="profile-remove"]');
  if (!action) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  if (action.dataset.action === 'profile-add') addProfile();
  else if (action.dataset.action === 'profile-reauthorize') reauthorizeActiveProfile();
  else if (action.dataset.action === 'profile-disconnect') disconnectActiveProfile();
  else removeActiveProfile();
}, true);
document.addEventListener('click', (event) => {
  const menu = document.querySelector('#profile-menu');
  if (menu && !event.target.closest('.user-chip') && !event.target.closest('#profile-menu')) menu.hidden = true;
});
document.addEventListener('click', (event) => {
  const action = event.target.closest('[data-action^="admin-"]')?.dataset.action;
  if (!action) return;
  const actions = { 'admin-clear-cache': ['clear-cache', 'Limpar cache'], 'admin-reset-jobs': ['reset-jobs', 'Resetar fila'], 'admin-clear-finished-jobs': ['clear-finished-jobs', 'Limpar jobs finalizados'], 'admin-vacuum-db': ['vacuum-db', 'Otimizar banco'], 'admin-restart-server': ['restart-server', 'Reiniciar servidor'] };
  if (actions[action]) runAdminAction(...actions[action]);
});
render();
renderDynamicInsights();
loadProfileCatalog().then(() => loadDashboard()).catch(() => loadDashboard());
loadGoogleIdentity();
loadLocationSettings();
loadNotifications();
