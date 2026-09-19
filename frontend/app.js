let videos = [];
let dashboard = { metrics: { videos_analisados: 0, views_top_15_display: '0', taxa_likes: null }, videos: [], last_sync_at: null };
let cutSources = [];
let selectedCutSource = null;
let cutDurationRange = { min: 30, max: 60 };
let cutSuggestions = [];
let persistedCuts = [];
const selectedCandidateIds = new Set();
let transcriptionJob = null;
let cutJob = null;
let uploadProgress = null;
let scheduledVideos = [];
let connectedProfiles = [];
let locationSettings = { bairro: '', cidade: '', estado: '' };
let radarData = null;
let opportunities = [];
let profileTask = { status: 'idle', progress: 0, processed: 0, total: 0, message: 'Nenhum perfil gerado', eta_seconds: null };
let notifications = { notificacoes: [], nao_lidas: 0 };
let searchResults = [];
let contentAnalysisStatus = { status: 'idle', processed: 0, total: 0, cache: { pendentes: 0 } };
let activeProfileId = Number(localStorage.getItem('growth-engine-profile-id') || 1);
let profileCatalog = [];
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
  if (url.startsWith('/api/') && url !== '/api/profiles' && url !== '/api/profiles/active') headers.set('X-Profile-Id', String(activeProfileId));
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
const labels = { overview: 'Visão geral', ranking: 'Ranking', autopsy: 'Autópsia', suggestions: 'Próximos vídeos', radar: 'Radar local', opportunities: 'Oportunidades', cuts: 'Central de cortes', library: 'Biblioteca', publishing: 'Publicação', settings: 'Configurações' };
const savedTheme = localStorage.getItem('growth-engine-theme') || 'light';
document.documentElement.dataset.theme = savedTheme;

function icon(name) { return `<i data-lucide="${name}"></i>`; }
function refreshIcons() { if (window.lucide) lucide.createIcons(); }
async function loadNotifications() {
  try {
    const response = await fetch('/api/notifications');
    if (response.ok) notifications = await response.json();
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
    const option = createElement('button', { className: 'profile-option', 'data-action': 'profile-option', 'data-profile-id': profile.id }, [
      createElement('span', { textContent: profile.nome || `Perfil ${profile.id}` }),
      createElement('small', { textContent: profile.canal_nome || profile.canal_url || '' }),
    ]);
    menu.appendChild(option);
  });
  menu.appendChild(createElement('div', { className: 'profile-menu-divider' }));
  menu.appendChild(createElement('button', { className: 'profile-option profile-menu-action', 'data-action': 'profile-add', textContent: 'Adicionar perfil' }));
  if (activeProfileId !== 1) menu.appendChild(createElement('button', { className: 'profile-option profile-menu-action danger', 'data-action': 'profile-remove', textContent: 'Remover perfil atual' }));
  document.body.appendChild(menu);
  chip.onclick = () => {
    const rect = chip.getBoundingClientRect();
    menu.style.top = `${rect.bottom + 8}px`;
    menu.style.right = `${Math.max(12, window.innerWidth - rect.right)}px`;
    menu.hidden = !menu.hidden;
  };
}
async function selectProfile(profileId) {
  const response = await nativeFetch('/api/profiles/active', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ perfil_id: Number(profileId) }) });
  if (!response.ok) return showToast('Não foi possível alternar o perfil.');
  activeProfileId = Number(profileId);
  localStorage.setItem('growth-engine-profile-id', String(activeProfileId));
  document.querySelector('#profile-menu')?.remove();
  clearElement(appView);
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
  await loadCutSources();
  await loadScheduled();
  await loadNotifications();
}
async function addProfile() {
  window.location.href = '/oauth/google/start';
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
function toggleNotifications() {
  let panel = document.querySelector('#notifications-panel');
  if (panel) { panel.remove(); return; }
  panel = document.createElement('div');
  panel.id = 'notifications-panel';
  const header = createElement('div', { className: 'notifications-header' }, [
    createElement('strong', { textContent: 'Notificações' }),
    createElement('span', {}, [
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
  toggleNotifications();
  toggleNotifications();
}
async function clearReadNotifications() {
  const response = await fetch('/api/notifications/clear-read', { method: 'POST' });
  if (!response.ok) return showToast('Não foi possível limpar as notificações lidas.');
  notifications = await response.json();
  const panel = document.querySelector('#notifications-panel');
  if (panel) panel.remove();
  toggleNotifications();
  showToast('Notificações lidas removidas.');
}
function showToast(message) { const toast = document.querySelector('#toast'); toast.textContent = message; toast.classList.add('show'); setTimeout(() => toast.classList.remove('show'), 2600); }
function metric(label, value, meta, neutral = false) { return `<div class="metric-card"><span class="metric-label">${label}</span><strong class="metric-value">${value}</strong><span class="metric-meta ${neutral ? 'neutral' : ''}">${meta}</span></div>`; }
function button(label, iconName, cls = 'secondary', action = '') { return `<button class="button ${cls}" data-action="${action}">${icon(iconName)}${label}</button>`; }
function formatRate(value) { return value === null || value === undefined ? 'sem dados' : `${String(value).replace('.', ',')}%`; }
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
  if (!job?.resultado_json) return null;
  try { return typeof job.resultado_json === 'string' ? JSON.parse(job.resultado_json) : job.resultado_json; } catch (error) { return null; }
}
function formatElapsedSeconds(seconds) {
  if (!Number.isFinite(Number(seconds))) return 'n/d';
  const total = Math.max(0, Math.round(Number(seconds)));
  return `${Math.floor(total / 60)}m ${String(total % 60).padStart(2, '0')}s`;
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
  const displayName = profile.google_account_email || profile.canal_nome || profile.nome || 'Conta Google';
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
async function loadOpportunities() {
  try {
    const response = await fetch('/api/opportunities');
    opportunities = response.ok ? (await response.json()).oportunidades || [] : [];
  } catch (error) {
    opportunities = [];
  }
  renderOpportunities();
  loadProfileTask();
}
async function generateOpportunities() {
  const response = await fetch('/api/opportunities/generate', { method: 'POST' });
  if (!response.ok) return showToast('Não foi possível iniciar as sugestões dos Top 15.');
  showToast('Análise dos Top 15 iniciada.');
  const poll = async () => {
    const status = await (await fetch('/api/opportunities/status')).json();
    if (status.status === 'running') return setTimeout(poll, 1800);
    await loadOpportunities();
    showToast(status.message);
  };
  poll();
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
function renderOpportunities() {
  const root = createElement('div', { className: 'view-card active' });
  root.appendChild(createElement('div', { className: 'page-header' }, [createElement('div', {}, [domText('span', 'eyebrow', 'Central / oportunidades'), domText('h1', '', 'Transforme sinais em pautas.'), domText('p', '', 'Estas sugestões vêm exclusivamente da Autópsia dos Top 15, não do Radar.')]), createElement('div', { className: 'header-actions' }, [domButton('Gerar sugestões dos Top 15', 'sparkles', 'lime', 'generate-opportunities')])]));
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
  if (source) source.textContent = `${dashboard.metrics.videos_analisados} vídeos observados · taxa média ${formatRate(dashboard.metrics.taxa_likes)}`;
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
    const response = await fetch('/api/cut-sources');
    if (!response.ok) throw new Error('fontes indisponíveis');
    const payload = await response.json();
    cutSources = payload.videos || [];
    selectedCutSource = cutSources[0] || null;
    if (cutSources.length) {
      const cutsResponse = await fetch('/api/cuts');
      const cuts = cutsResponse.ok ? (await cutsResponse.json()).cortes || [] : [];
      const sourceIds = new Set(cutSources.map(video => video.id));
      persistedCuts = cuts.filter(cut => sourceIds.has(cut.video_id) && cut.status !== 'excluido');
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
async function restoreActiveCutJobs() {
  try {
    const response = await fetch('/api/jobs/active');
    let jobs = response.ok ? (await response.json()).jobs || [] : [];
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(activeJobStorageKey()) || 'null'); } catch (error) { localStorage.removeItem(activeJobStorageKey()); }
    if (!jobs.length && saved?.job?.id) {
      const savedResponse = await fetch(`/api/jobs/${encodeURIComponent(saved.job.id)}`);
      const savedJob = savedResponse.ok ? await savedResponse.json() : null;
      if (isLiveJob(savedJob)) jobs = [{ ...savedJob, tipo: saved.kind === 'transcription' ? 'transcription' : 'cut' }];
    }
    const transcription = jobs.find(job => job.tipo === 'transcription');
    const processing = jobs.find(job => job.tipo !== 'transcription');
    if (transcription && !transcriptionJob) {
      transcriptionJob = { id: transcription.job_id || transcription.id, status: transcription.status, progress: transcription.progresso ?? transcription.progress ?? 0, message: transcription.mensagem || transcription.message || 'Transcrição em andamento', video_id: transcription.video_id };
      pollTranscriptionJob();
    }
    if (processing && !cutJob) {
      cutJob = { id: processing.job_id || processing.id, status: processing.status, progress: processing.progresso ?? processing.progress ?? 0, message: processing.mensagem || processing.message || 'Processamento em andamento', video_id: processing.video_id };
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
async function startContentAnalysis() {
  try {
    const response = await fetch('/api/content-analysis/start', { method: 'POST' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível iniciar a análise.');
    showToast('Análise dos vídeos longos iniciada.');
    pollContentStatus();
    pollContentAnalysis();
  } catch (error) {
    showToast(error.message);
  }
}
async function pollContentAnalysis() {
  const response = await fetch('/api/content-analysis/status');
  const payload = await response.json();
  if (payload.status === 'running') {
    showToast(`${payload.message}: ${payload.processed}/${payload.total || '?'} vídeos`);
    setTimeout(pollContentAnalysis, 1800);
  } else if (payload.status === 'completed') {
    showToast('Análise de conteúdo concluída e salva no cache.');
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
  renderCuts();
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
    cutJob = { id: payload.job_id, status: 'queued', progress: 0, message: 'Na fila' };
    rememberActiveJob('cut', cutJob);
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
    renderCuts();
    if (payload.status === 'completed') {
      forgetActiveJob(cutJob.id);
      cutSuggestions = payload.suggestions || [];
      await loadCutSources();
      cutJob = null;
      renderCuts();
      showToast(`${cutSuggestions.length} corte(s) validado(s) pela IA.`);
      return;
    }
    if (payload.status === 'needs_review') {
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
      showToast(payload.message || 'A análise precisa de revisão.');
      return;
    }
    if (payload.status === 'failed' || payload.status === 'interrupted' || payload.status === 'cancelled') {
      forgetActiveJob(cutJob.id);
      cutJob = null;
      renderCuts();
      showToast(payload.message || 'O processamento dos cortes foi interrompido.');
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
async function renderSelectedCuts() {
  const cutIds = [...selectedCandidateIds];
  if (!cutIds.length) return showToast('Selecione pelo menos um candidato para renderizar.');
  try {
    const selectResponse = await fetch('/api/cuts/select', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cut_ids: cutIds }) });
    if (!selectResponse.ok) throw new Error((await selectResponse.json()).error || 'Não foi possível salvar a seleção.');
    const response = await fetch('/api/cuts/render-selected', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cut_ids: cutIds }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível iniciar a renderização.');
    cutJob = { id: payload.job_id, status: 'queued', progress: 0, message: 'Renderização aprovada na fila' };
    rememberActiveJob('cut', cutJob);
    renderCuts();
    pollCutJob();
  } catch (error) {
    showToast(error.message);
  }
}
async function runTranscription() {
  if (!selectedCutSource) return showToast('Selecione um vídeo longo primeiro.');
  showToast('Transcrição iniciada. Acompanhe o progresso na Central.');
  try {
    const response = await fetch('/api/transcription/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ video_id: selectedCutSource.id }) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'falha na transcrição');
    transcriptionJob = { id: payload.job_id, status: 'queued', progress: 0, message: 'Na fila' };
    rememberActiveJob('transcription', transcriptionJob);
    renderCuts();
    pollTranscriptionJob();
  } catch (error) {
    showToast(error.message);
  }
}
async function cancelActiveJob() {
  const activeJob = cutJob || transcriptionJob;
  if (!activeJob?.id) return;
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(activeJob.id)}/cancel`, { method: 'POST' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Não foi possível cancelar o processo.');
    if (cutJob?.id === activeJob.id) cutJob = { ...cutJob, ...payload };
    if (transcriptionJob?.id === activeJob.id) transcriptionJob = { ...transcriptionJob, ...payload };
    forgetActiveJob(activeJob.id);
    renderCuts();
    showToast('Cancelamento solicitado.');
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
    cutJob = { id: payload.job_id, status: 'queued', progress: 0, message: 'Upload recebido' };
    rememberActiveJob('cut', cutJob);
    renderCuts();
    pollCutJob();
  } catch (error) {
    uploadProgress = null;
    renderCuts();
    showToast(error.name === 'TypeError' ? 'Não foi possível enviar o arquivo. Verifique se o servidor está ativo e tente novamente.' : error.message);
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
    cutJob = { id: payload.job_id, status: 'queued', progress: 0, message: 'Download forçado na fila' };
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
  const root = createElement('div', { className: 'view-card active' });
  root.appendChild(createElement('div', { className: 'page-header' }, [createElement('div', {}, [domText('span', 'eyebrow', 'Central / visão geral'), domText('h1', '', 'O que merece atenção hoje?'), domText('p', '', 'Uma leitura rápida do seu sistema de conteúdo: o que performou, o que está pronto para virar Short e onde existe uma próxima boa ideia.')]), createElement('div', { className: 'header-actions' }, [domButton('Sincronizar canal', 'refresh-cw', 'lime', 'sync'), domButton('Ver cortes', 'scissors', 'secondary', 'cuts')])]));
  root.appendChild(createElement('div', { className: 'metric-grid' }, [
    domMetric('Vídeos analisados', metrics.videos_analisados, 'dados do SQLite'),
    domMetric('Cortes em revisão', '—', 'pipeline de cortes'),
    domMetric('Views top 15', metrics.views_top_15_display, 'ranking atual'),
    domMetric('Taxa média de likes', formatRate(metrics.taxa_likes), metrics.taxa_likes === null ? 'base sem views' : 'views totais', metrics.taxa_likes === null),
  ]));
  const contentGrid = createElement('div', { className: 'content-grid' });
  const videoPanel = createElement('section', { className: 'panel' }, [domPanelHeader('Melhores sinais', 'Os vídeos que estão ensinando algo ao sistema', createElement('button', { className: 'text-link', 'data-action': 'ranking' }, ['VER RANKING ', domIcon('arrow-up-right')]))]);
  const videoList = createElement('div', { className: 'video-list' });
  videos.slice(0, 4).forEach((video, index) => {
    const info = createElement('div', { className: 'video-info' }, [createElement('strong', {}, [domText('span', 'video-title', video.title), domText('span', `type-pill ${video.type === 'Short' ? 'short' : ''}`, video.type)]), domText('span', '', `${video.date} · ${video.likes_display || video.likes} likes · taxa ${formatRate(video.score)}`)]);
    videoList.appendChild(createElement('div', { className: 'video-row' }, [domText('span', 'rank', `0${index + 1}`), info, createElement('div', { className: 'video-stats' }, [domText('strong', '', video.views_display || video.views), domText('span', '', 'visualizações')])]));
  });
  if (!videos.length) videoList.appendChild(createElement('div', { className: 'video-row' }, [createElement('div', { className: 'video-info' }, [domText('strong', {}, [domText('span', 'video-title', 'Nenhum vídeo sincronizado ainda.')])])]));
  videoPanel.appendChild(videoList);
  const rightStack = createElement('div', { className: 'right-stack' });
  const insight = createElement('section', { className: 'panel insight-panel' }, [domPanelHeader('Leitura do momento', 'Hipótese baseada nos últimos dados', domIcon('scan-search')), createElement('div', { className: 'insight-body' }, [createElement('div', { className: 'lime-line' }), domText('p', 'insight-quote', buildInsights()[0].text), domText('p', 'insight-source', `${metrics.videos_analisados} vídeos observados · taxa média ${formatRate(metrics.taxa_likes)}`)])]);
  const queue = createElement('section', { className: 'panel' }, [domPanelHeader('Fila de trabalho', 'Próximas ações sugeridas')]);
  queue.appendChild(createElement('div', { className: 'queue-item' }, [createElement('div', { className: 'queue-icon' }, [domIcon('scissors')]), createElement('div', { className: 'queue-copy' }, [domText('strong', '', 'Revisar cortes'), domText('span', '', 'Pipeline de cortes')]), createElement('button', { className: 'dot-menu', 'data-action': 'cuts' }, [domIcon('arrow-up-right')])]));
  queue.appendChild(createElement('div', { className: 'queue-item' }, [createElement('div', { className: 'queue-icon' }, [domIcon('refresh-cw')]), createElement('div', { className: 'queue-copy' }, [domText('strong', '', 'Sincronizar canal'), domText('span', '', `Última atualização ${formatSyncTime(dashboard.last_sync_at)}`)]), createElement('button', { className: 'dot-menu', 'data-action': 'sync' }, [domIcon('arrow-up-right')])]));
  rightStack.append(insight, queue);
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
function isLiveJob(job) {
  return Boolean(job && ['uploading', 'queued', 'running', 'analyzing', 'rendering'].includes(job.status));
}
function renderJobProgress(job) {
  const telemetry = [
    job.stage ? `Etapa: ${job.stage}` : '',
    job.device ? `Dispositivo: ${job.device}${job.fallback_reason ? ` (${job.fallback_reason})` : ''}` : '',
    Number.isFinite(Number(job.elapsed_seconds)) ? `Tempo: ${formatElapsedSeconds(job.elapsed_seconds)}` : '',
    Number.isFinite(Number(job.speed_x)) ? `Velocidade: ${job.speed_x}x` : '',
    Number.isFinite(Number(job.eta_seconds)) ? `ETA: ${formatElapsedSeconds(job.eta_seconds)}` : '',
    Number.isFinite(Number(job.processed_audio_seconds)) && Number.isFinite(Number(job.audio_seconds)) ? `Áudio: ${formatElapsedSeconds(job.processed_audio_seconds)} / ${formatElapsedSeconds(job.audio_seconds)}` : '',
    Number.isFinite(Number(job.segments_processed)) ? `Segmentos: ${job.segments_accepted || 0}/${job.segments_processed}` : '',
  ].filter(Boolean).join(' · ');
  const message = job.status === 'queued' && job.message === 'Upload recebido' ? 'Aguardando fila de processamento' : job.message;
  const box = createElement('div', { className: 'progress-box' }, [createElement('div', { className: 'progress-head' }, [domText('span', '', message), domText('strong', '', `${job.progress || 0}%`)]), createElement('div', { className: 'progress-track' }, [createElement('span', { style: `width:${job.progress || 0}%` })]), telemetry ? domText('p', 'progress-telemetry', telemetry) : null]);
  box.appendChild(domButton('Cancelar processo', 'x', 'danger', 'cancel-job'));
  return box;
}
function renderCuts() {
  const root = createElement('div', { className: 'view-card active' });
  root.appendChild(createElement('div', { className: 'page-header' }, [createElement('div', {}, [domText('span', 'eyebrow', 'Central / produção'), domText('h1', '', 'Revisar antes de renderizar.'), domText('p', '', 'Escolha um vídeo real, confira a transcrição ancorada e só então gere sugestões de corte.')]) ]));
  const intake = createElement('section', { className: 'panel media-intake' }, [domPanelHeader('Entrada de mídia', 'Processe um MP4 local ou force o download de um vídeo do YouTube.')]);
  const uploadForm = createElement('div', { className: 'media-intake-row' }, [createElement('input', { id: 'local-media-file', type: 'file', accept: '.mp4,.mkv,video/mp4,video/x-matroska' }), domButton('Enviar', 'upload', 'lime', 'upload-local')]);
  const downloadForm = createElement('div', { className: 'media-intake-row' }, [createElement('input', { id: 'force-download-url', type: 'url', placeholder: 'https://www.youtube.com/watch?v=...' }), domButton('Forçar Download/Recorte', 'download', 'secondary', 'force-download')]);
  intake.append(uploadForm, downloadForm);
  root.appendChild(intake);
  const activeJob = [uploadProgress, cutJob, transcriptionJob].find(isLiveJob);
  if (activeJob) root.appendChild(renderJobProgress(activeJob));
  const picker = createElement('div', { className: 'cut-source-picker' });
  const select = createElement('select', { 'data-action': 'cut-source' });
  cutSources.forEach(video => select.appendChild(createElement('option', { value: video.id, selected: selectedCutSource?.id === video.id ? 'true' : null, textContent: `${video.title} · ${video.views_display} views` })));
  if (cutSources.length) {
    picker.appendChild(select);
    root.appendChild(picker);
  } else {
    root.appendChild(domText('p', 'empty-state', 'Este perfil ainda não possui vídeos longos para corte.'));
  }
  const durationPanel = createElement('section', { className: 'panel cut-settings' }, [
    domPanelHeader('Regra de duração', 'A IA só poderá sugerir trechos dentro desta faixa.'),
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
  const persistedPanel = createElement('section', { className: 'panel cut-review' }, [domPanelHeader('Cortes gerados', 'Estado persistido de cada renderização')]);
  const persistedList = createElement('div', { className: 'suggestion-list' });
  const statusLabel = { pendente: 'Pendente', candidato: 'Para revisar', renderizando: 'Renderizando', concluido: 'Renderizado', falhou: 'Falhou', excluido: 'Excluído' };
  persistedCuts.forEach(cut => {
    const status = cut.status || 'pendente';
    const canSelect = ['candidato', 'concluido', 'selecionado'].includes(status);
    const checkbox = canSelect ? createElement('input', { type: 'checkbox', checked: selectedCandidateIds.has(cut.id) ? 'true' : null, 'data-action': 'candidate-toggle', 'data-cut-id': cut.id, 'aria-label': `Selecionar ${cut.titulo || 'corte'}` }) : null;
    const row = createElement('div', { className: 'evidence-row' }, [
      checkbox,
      createElement('span', { className: `cut-status cut-status-${status}`, textContent: statusLabel[status] || status }),
      createElement('p', {}, [
        domText('strong', '', cut.titulo || 'Corte sem título'),
        document.createElement('br'),
        domText('span', '', `Score ${cut.score_vaca_roxa || 0}/100 · ${cut.inicio_segundos}s — ${cut.fim_segundos}s`),
        document.createElement('br'),
        domText('span', '', `Gancho: ${cut.gancho || 'não informado'} · Promessa: ${cut.promessa || 'não informada'}`),
      ]),
    ]);
    if (status === 'concluido') {
      const link = setSafeLink(createElement('a'), `/api/cuts/file?id=${encodeURIComponent(cut.id)}`);
      link.append('Abrir MP4 ', domIcon('arrow-up-right'));
      row.appendChild(link);
    }
    if (canSelect) row.appendChild(domButton('Excluir', 'trash-2', 'danger', 'delete-cut', { 'data-cut-id': cut.id }));
    persistedList.appendChild(row);
  });
  if (!persistedCuts.length) persistedList.appendChild(domText('p', 'empty-state', 'Nenhum corte persistido ainda.'));
  persistedPanel.appendChild(persistedList);
  root.appendChild(persistedPanel);
  const reviewJob = [cutJob, transcriptionJob].find(job => job?.status === 'needs_review');
  if (reviewJob) {
      const diagnostics = reviewJob.diagnostics || parseJobDiagnostics(reviewJob);
      const analysis = diagnostics?.analysis;
      const rounds = analysis?.diagnostico || [];
      const accepted = analysis?.cortes?.length || 0;
      const detail = rounds.map(round => `Rodada ${round.tentativa}: ${round.aceitos || 0} aceitos de ${round.candidatos || 0}`).join(' · ');
      root.appendChild(createElement('div', { className: 'panel task-review-details' }, [
        domText('strong', '', `Foram encontrados ${accepted} de 9 cortes válidos.`),
        domText('p', '', detail || 'O diagnóstico desta execução não possui detalhes de rodada.'),
        domText('p', '', 'O vídeo e a transcrição permanecem disponíveis para uma nova revisão.'),
      ]));
  }
  const review = createElement('section', { className: 'panel cut-review' }, [domPanelHeader('Preparação da análise', 'Confirme a fonte e a faixa antes de pedir sugestões à IA')]);
  const body = createElement('div', { className: 'cut-review-body' });
  const transcription = selectedCutSource?.transcription;
  const segments = transcription?.segments || [];
  if (segments.length) {
    const duration = Math.max(...segments.map(segment => Number(segment.fim) || 0));
    const sample = segments.slice(0, 2).map(segment => segment.texto).join(' ');
    body.appendChild(createElement('div', { className: 'transcription-summary' }, [
      domText('strong', '', selectedCutSource.title || selectedCutSource.titulo || 'Vídeo selecionado'),
      domText('span', '', `${segments.length} segmentos · ${formatElapsedSeconds(duration)} de áudio · faixa de corte ${cutDurationRange.min}s–${cutDurationRange.max}s`),
      domText('p', '', sample ? `${sample.slice(0, 220)}${sample.length > 220 ? '...' : ''}` : 'Transcrição pronta para análise.'),
    ]));
  } else body.appendChild(createElement('div', { className: 'evidence-row' }, [domText('span', '', 'Transcrição temporal'), domText('p', '', 'Este vídeo ainda não possui segmentos salvos. Execute a transcrição pelo pipeline antes de gerar uma prévia.')]));
  const actions = createElement('div', { className: 'header-actions' });
  if (!segments.length && selectedCutSource && !transcriptionJob) actions.appendChild(domButton('Transcrever vídeo', 'audio-lines', 'lime', 'transcribe'));
  if (segments.length && (!cutJob || cutJob.status === 'needs_review')) actions.appendChild(domButton('Gerar cortes', 'scissors', 'lime', 'preview'));
  body.appendChild(actions);
  if (cutSuggestions.length) {
    const suggestions = createElement('div', { className: 'suggestion-list' });
    cutSuggestions.forEach((cut, index) => {
      const isCandidate = Boolean(cut.nome_rodada) || cut.status === 'candidato' || cut.status === 'selecionado';
      const checkbox = isCandidate ? createElement('input', { type: 'checkbox', checked: selectedCandidateIds.has(cut.cut_id) ? 'true' : null, 'data-action': 'candidate-toggle', 'data-cut-id': cut.cut_id, 'aria-label': `Selecionar ${cut.titulo}` }) : null;
      const rangeLabel = isCandidate ? (cut.nome_rodada || 'Candidato') : `Corte ${String(index + 1).padStart(2, '0')}`;
      const evidence = createElement('p', {}, [domText('span', 'score-meter', `Score ${cut.score_vaca_roxa}/100`), document.createElement('br'), domText('strong', '', cut.titulo), document.createElement('br'), domText('span', '', cut.gancho)]);
      const row = createElement('div', { className: `evidence-row ${isCandidate ? 'candidate-row' : ''}` }, [checkbox, domText('span', '', `${rangeLabel} · ${Number(cut.inicio).toFixed(1)}s — ${Number(cut.fim).toFixed(1)}s`), evidence]);
      if (cut.output_path || cut.caminho_saida) {
        const link = setSafeLink(createElement('a'), `/api/cuts/file?id=${encodeURIComponent(cut.cut_id || cut.id)}`);
        link.append('Abrir MP4 ', domIcon('arrow-up-right'));
        row.appendChild(link);
      }
      suggestions.appendChild(row);
    });
    body.appendChild(suggestions);
    if (cutSuggestions.some(cut => cut.status === 'candidato' || cut.status === 'concluido' || cut.status === 'selecionado')) body.appendChild(domButton('Selecionar para postagem e renderizar', 'scissors', 'lime', 'render-selected-cuts'));
  }
  review.appendChild(body);
  root.appendChild(review);
  replaceView(root);
}
function renderAutopsy() {
  const root = createElement('div', { className: 'view-card active' });
  root.appendChild(createElement('div', { className: 'page-header' }, [createElement('div', {}, [domText('span', 'eyebrow', 'Central / autópsia'), domText('h1', '', 'Transformar números em hipóteses.'), domText('p', '', 'A IA lê os melhores vídeos e separa observações de hipóteses.')]), createElement('div', { className: 'header-actions' }, [domButton('Rodar autópsia', 'microscope', 'lime', 'autopsy')])]));
  const list = createElement('div', { className: 'insight-list' });
  ['Contraste é um sinal observável', 'Descrição ajuda a classificar', 'Próximo teste recomendado'].forEach((title, index) => list.appendChild(createElement('div', { className: 'insight-row' }, [domText('span', 'insight-index', `0${index + 1}`), createElement('div', {}, [domText('strong', '', title), domText('p', '', 'Use os dados reais do canal e trate esta leitura como hipótese testável.')] )])));
  root.appendChild(list);
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
function renderSimple(title, eyebrow, text) {
  const root = createElement('div', { className: 'view-card active' });
  root.appendChild(createElement('div', { className: 'page-header' }, [createElement('div', {}, [domText('span', 'eyebrow', `Central / ${eyebrow}`), domText('h1', '', title), domText('p', '', text)])]));
  root.appendChild(domText('div', 'panel empty-state', 'Módulo em preparação.'));
  replaceView(root);
}

function render(view = state.view) { state.view = view; breadcrumb.textContent = labels[view] || view; ({ overview: renderOverview, ranking: renderRanking, autopsy: renderAutopsy, suggestions: renderSuggestions, radar: renderRadar, opportunities: renderOpportunities, cuts: renderCuts, library: () => renderSimple('Tudo que o canal já produziu.', 'biblioteca', 'Vídeos sincronizados, transcrições e arquivos prontos para o próximo movimento.'), publishing: renderPublishing, settings: renderSettings }[view] || renderOverview)(); refreshIcons(); }

document.addEventListener('change', (event) => { const duration = event.target.closest('[data-action="cut-duration"]'); if (duration) { const minimum = Number(document.querySelector('#cut-duration-min')?.value || cutDurationRange.min); const maximum = Number(document.querySelector('#cut-duration-max')?.value || cutDurationRange.max); if (minimum > maximum) { showToast('A duração mínima não pode ser maior que a máxima.'); renderCuts(); return; } cutDurationRange = { min: minimum, max: maximum }; renderCuts(); } const select = event.target.closest('[data-action="cut-source"]'); if (select) selectCutSource(select.value); const candidate = event.target.closest('[data-action="candidate-toggle"]'); if (candidate) { const cutId = Number(candidate.dataset.cutId); if (candidate.checked) selectedCandidateIds.add(cutId); else selectedCandidateIds.delete(cutId); renderCuts(); } });
document.addEventListener('click', (event) => { const nav = event.target.closest('[data-view]'); if (nav) { document.querySelectorAll('.nav-item').forEach(item => item.classList.toggle('active', item === nav)); render(nav.dataset.view); renderDynamicInsights(); if (nav.dataset.view === 'ranking') loadRanking(); if (nav.dataset.view === 'radar') loadRadar(); if (nav.dataset.view === 'opportunities') loadOpportunities(); if (nav.dataset.view === 'cuts') loadCutSources(); if (nav.dataset.view === 'publishing') loadScheduled(); if (nav.dataset.view === 'settings') loadProfiles(); return; } const actionElement = event.target.closest('[data-action]'); const action = actionElement?.dataset.action; if (!action) return; if (action === 'toggle-theme') { const nextTheme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'; document.documentElement.dataset.theme = nextTheme; localStorage.setItem('growth-engine-theme', nextTheme); clearElement(actionElement); actionElement.appendChild(domIcon(nextTheme === 'dark' ? 'sun' : 'moon')); refreshIcons(); } else if (action === 'save-location') saveLocationSettings(); else if (action === 'settings') { render('settings'); loadProfiles(); } else if (action === 'opportunities') loadOpportunities(); else if (action === 'profile-rebuild') startProfileRebuild(); else if (action === 'briefing') { fetch(`/api/opportunities/${actionElement.dataset.opportunityId}/briefing`).then(response => response.json()).then(briefing => showToast(`Briefing: ${briefing.titulo_provisorio || 'carregado'}`)); } else if (action === 'cuts') { render('cuts'); loadCutSources(); } else if (action === 'ranking') { render('ranking'); loadRanking(); } else if (action === 'ranking-filter') loadRanking(actionElement.dataset.rankingType); else if (action === 'scheduled') loadScheduled(); else if (action === 'connect-google') window.location.href = '/oauth/google/start'; else if (action === 'sync') startSync(); else if (action === 'preview') generateCutPreview(); else if (action === 'transcribe') runTranscription(); else if (action === 'approve') showToast('Corte aprovado e enviado para a fila de renderização.'); else if (action === 'reject') showToast('Corte rejeitado. A decisão será registrada.'); else if (action === 'autopsy') startContentAnalysis(); else if (action === 'suggest') showToast('Geração de sugestões enfileirada.'); });

document.addEventListener('click', (event) => { const notificationAction = event.target.closest('[data-action="notifications"]'); if (notificationAction) toggleNotifications(); const readAction = event.target.closest('[data-action="read-notification"]'); if (readAction) readNotification(readAction.dataset.notificationId); const searchAction = event.target.closest('[data-action="search-open"]'); if (searchAction) openSearch(); const resultAction = event.target.closest('[data-action="search-result"]'); if (resultAction) { document.querySelector('#search-panel')?.remove(); render(resultAction.dataset.resultAction); if (resultAction.dataset.resultAction === 'ranking') loadRanking(); if (resultAction.dataset.resultAction === 'opportunities') loadOpportunities(); } });

document.addEventListener('click', (event) => { if (event.target.closest('[data-action="generate-opportunities"]')) generateOpportunities(); });
document.addEventListener('click', (event) => { if (event.target.closest('[data-action="clear-read"]')) clearReadNotifications(); });
document.addEventListener('click', (event) => { if (event.target.closest('[data-action="radar-refresh"]')) loadRadar(); });
document.addEventListener('click', (event) => { if (event.target.closest('[data-action="close-briefing"]')) document.querySelector('#briefing-panel')?.remove(); });
document.addEventListener('click', (event) => { const briefingAction = event.target.closest('[data-action="briefing"]'); if (briefingAction) showBriefingPanel(briefingAction.dataset.opportunityId); });
document.addEventListener('click', (event) => { if (event.target.closest('[data-action="upload-local"]')) uploadLocalMedia(); if (event.target.closest('[data-action="force-download"]')) forceDownloadMedia(); });
document.addEventListener('click', (event) => { if (event.target.closest('[data-action="render-selected-cuts"]')) renderSelectedCuts(); });
document.addEventListener('click', (event) => { if (event.target.closest('[data-action="cancel-job"]')) cancelActiveJob(); });
document.addEventListener('click', (event) => { const option = event.target.closest('[data-action="profile-option"]'); if (option) selectProfile(option.dataset.profileId); });
document.addEventListener('click', (event) => { if (event.target.closest('[data-action="profile-add"]')) addProfile(); if (event.target.closest('[data-action="profile-remove"]')) removeActiveProfile(); });
document.addEventListener('click', (event) => {
  const menu = document.querySelector('#profile-menu');
  if (menu && !event.target.closest('.user-chip') && !event.target.closest('#profile-menu')) menu.hidden = true;
});
render();
renderDynamicInsights();
loadProfileCatalog().then(() => loadDashboard()).catch(() => loadDashboard());
loadGoogleIdentity();
loadLocationSettings();
loadNotifications();
