import { createInitialState } from './data.js';

const STORAGE_KEY = 'plant-crm-state-v1';
const root = document.getElementById('app');

let state = loadState();
let renderQueued = false;

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return createInitialState();
    const parsed = JSON.parse(raw);
    return {
      ...createInitialState(),
      ...parsed,
      ui: { ...createInitialState().ui, ...(parsed.ui || {}) },
      security: { ...createInitialState().security, ...(parsed.security || {}) },
      auth: { ...createInitialState().auth, ...(parsed.auth || {}) },
    };
  } catch {
    return createInitialState();
  }
}

function persistState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function scheduleRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => {
    renderQueued = false;
    render();
  });
}

function nowIso() {
  return new Date().toISOString();
}

function currentUser() {
  return state.users.find((user) => user.id === state.auth.userId) || null;
}

function currentRole() {
  return currentUser()?.role || null;
}

function canAccess(view) {
  const role = currentRole();
  if (!role) return false;
  return state.roles[role]?.includes(view) || false;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatMoney(value) {
  return new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 }).format(value);
}

function formatDateTime(value) {
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
}

function formatTime(value) {
  return new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' }).format(new Date(value));
}

function minutesAgo(value) {
  return Math.max(1, Math.round((Date.now() - new Date(value).getTime()) / 60000));
}

function roleLabel(role) {
  const map = {
    admin: 'Админ',
    front: 'Фронт',
    back: 'Бек',
    hybrid: 'Гибрид',
    content: 'Контент',
    locomotive: 'Локомотив',
  };
  return map[role] || role;
}

function clientStatus(client) {
  if (client.purchases?.length || client.bankPurchases?.some((item) => item.matched || item.amount > 0)) return 'Покупатель';
  if (client.phone || client.email) return 'Лид';
  return 'Нераспознанный';
}

function statusChip(status) {
  const normalized = (status || '').toLowerCase();
  if (normalized.includes('покуп')) return 'good';
  if (normalized.includes('лид')) return 'warn';
  if (normalized.includes('нерасп')) return 'info';
  if (normalized.includes('done')) return 'good';
  if (normalized.includes('waiting')) return 'warn';
  if (normalized.includes('overdue')) return 'danger';
  return 'info';
}

function taskPriorityLabel(priority) {
  return {
    1: 'P1',
    2: 'P2',
    3: 'P3',
    4: 'P4',
  }[priority] || `P${priority}`;
}

function toast(title, text, type = 'info') {
  const id = crypto.randomUUID();
  state.notifications.push({ id, title, text, type, at: nowIso() });
  persistState();
  scheduleRender();
  setTimeout(() => {
    dismissNotification(id);
  }, 4200);
}

function dismissNotification(id) {
  state.notifications = state.notifications.filter((item) => item.id !== id);
  persistState();
  scheduleRender();
}

function logAction(action, before, after) {
  const actor = currentUser()?.name || 'Система';
  state.audit.unshift({
    id: crypto.randomUUID(),
    actor,
    ip: state.security.sessionIp,
    action,
    before: typeof before === 'string' ? before : JSON.stringify(before),
    after: typeof after === 'string' ? after : JSON.stringify(after),
    at: nowIso(),
  });
}

function mutate(action, description, fn) {
  const before = deepClone(state);
  fn();
  logAction(action, before, description || 'state mutated');
  state.security.lastActivityAt = nowIso();
  persistState();
  scheduleRender();
}

function logout(reason = 'Выход из системы') {
  mutate('Logout', reason, () => {
    state.auth.userId = null;
    state.ui.quickTest = null;
    state.security.blocked = false;
    state.security.blockReason = '';
  });
}

function normalizePhone(phone) {
  return String(phone || '')
    .replace(/[^\d+]/g, '')
    .replace(/^8(?=\d{10}$)/, '+7');
}

function findClientByPhone(phone) {
  const normalized = normalizePhone(phone);
  return state.clients.find((client) => normalizePhone(client.phone) === normalized && normalized);
}

function findClientByEmail(email) {
  const normalized = String(email || '').trim().toLowerCase();
  return state.clients.find((client) => String(client.email || '').trim().toLowerCase() === normalized && normalized);
}

function mergeClients(targetId, sourceId) {
  const target = state.clients.find((item) => item.id === targetId);
  const source = state.clients.find((item) => item.id === sourceId);
  if (!target || !source || target.id === source.id) return;
  mutate('Merge clients', `${source.name} -> ${target.name}`, () => {
    target.tags = Array.from(new Set([...(target.tags || []), ...(source.tags || [])]));
    target.interests = Array.from(new Set([...(target.interests || []), ...(source.interests || [])]));
    target.discountCards = Array.from(new Set([...(target.discountCards || []), ...(source.discountCards || [])]));
    target.wishList = Array.from(new Set([...(target.wishList || []), ...(source.wishList || [])]));
    target.waitList = Array.from(new Set([...(target.waitList || []), ...(source.waitList || [])]));
    target.history = [...(source.history || []), ...(target.history || [])];
    target.purchases = [...(source.purchases || []), ...(target.purchases || [])];
    target.bankPurchases = [...(source.bankPurchases || []), ...(target.bankPurchases || [])];
    target.channelHistory = Array.from(new Set([...(target.channelHistory || []), ...(source.channelHistory || [])]));
    target.notesInternal = [target.notesInternal, source.notesInternal].filter(Boolean).join('\n');
    target.updatedAt = nowIso();

    state.messages.forEach((message) => {
      if (message.clientId === source.id) message.clientId = target.id;
    });
    state.tasks.forEach((task) => {
      if (task.clientId === source.id) task.clientId = target.id;
    });
    state.clients = state.clients.filter((client) => client.id !== source.id);
    if (state.ui.selectedClientId === source.id) {
      state.ui.selectedClientId = target.id;
    }
  });
}

function openClientCard(clientId) {
  const user = currentUser();
  if (!user) return;
  const key = user.id;
  const events = state.security.openEvents[key] || [];
  const timestamp = Date.now();
  const recent = events.filter((item) => timestamp - item < 10 * 60 * 1000);
  recent.push(timestamp);
  state.security.openEvents[key] = recent;
  if (user.role !== 'admin' && recent.length > 30) {
    state.security.blocked = true;
    state.security.blockReason = `Подозрительная активность: ${recent.length} карточек за 10 минут`;
    toast('Права сотрудника ограничены', 'Сработал антифрод на аномальный просмотр карточек.', 'danger');
    state.notifications.unshift({
      id: crypto.randomUUID(),
      title: 'Антифрод',
      text: `${user.name} превысил лимит просмотра карточек клиентов.`,
      type: 'danger',
      at: nowIso(),
    });
  }
  state.ui.selectedClientId = clientId;
  persistState();
  scheduleRender();
}

function openQuickTest() {
  const tests = [
    { question: 'Сколько стоит детка гардении?', answer: '420' },
    { question: 'Что отвечаем, если товара нет в наличии?', answer: 'под заказ' },
    { question: 'Какой код нужен сотруднику для входа?', answer: '246810' },
  ];
  const picked = tests[Math.floor(Math.random() * tests.length)];
  state.ui.quickTest = picked;
  persistState();
  scheduleRender();
}

function answerQuickTest(formData) {
  const answer = String(formData.get('quickAnswer') || '').trim().toLowerCase();
  const expected = String(state.ui.quickTest?.answer || '').trim().toLowerCase();
  if (!state.ui.quickTest) return;
  if (answer === expected || expected === 'под заказ' && answer.includes('под заказ')) {
    toast('Быстрый тест пройден', 'Рабочий экран разблокирован.', 'good');
    state.ui.quickTest = null;
  } else {
    toast('Неверный ответ', 'Попробуйте еще раз.', 'danger');
  }
  persistState();
  scheduleRender();
}

function sendCode() {
  state.auth.pendingCode = '246810';
  state.auth.codeIssuedAt = nowIso();
  persistState();
  toast('Код отправлен', 'Для демо доступен код 246810.', 'info');
}

function attemptLogin(formData) {
  const login = String(formData.get('login') || '').trim();
  const password = String(formData.get('password') || '').trim();
  const code = String(formData.get('code') || '').trim();
  const user = state.users.find((item) => item.login === login && item.password === password && item.active);
  if (!user) {
    toast('Ошибка входа', 'Проверьте логин и пароль.', 'danger');
    return;
  }
  if (user.role !== 'admin' && code !== state.auth.pendingCode) {
    toast('Неверный код', 'Нужен код из рабочей почты.', 'danger');
    return;
  }
  state.auth.userId = user.id;
  state.auth.lastLoginAt = nowIso();
  state.security.lastActivityAt = nowIso();
  state.ui.view = canAccess(state.ui.view) ? state.ui.view : 'dashboard';
  state.ui.quickTest = null;
  if (user.role === 'admin') {
    toast('Добро пожаловать', 'Вход администратора выполнен.', 'good');
  } else {
    toast('Авторизация успешна', `Вход выполнен как ${user.name}.`, 'good');
  }
  persistState();
  scheduleRender();
}

function currentClient() {
  return state.clients.find((client) => client.id === state.ui.selectedClientId) || state.clients[0];
}

function getFilteredClients() {
  const query = state.ui.filters.clientQuery.trim().toLowerCase();
  const statusFilter = state.ui.filters.clientStatus;
  const channelFilter = state.ui.filters.clientChannel;
  return state.clients.filter((client) => {
    const matchesQuery = !query || [client.name, client.phone, client.email, client.source, ...(client.tags || []), ...(client.interests || [])]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query));
    const matchesStatus = statusFilter === 'all' || clientStatus(client) === statusFilter;
    const matchesChannel = channelFilter === 'all' || client.preferredChannel === channelFilter || client.source === channelFilter;
    return matchesQuery && matchesStatus && matchesChannel;
  });
}

function getFilteredMessages() {
  const channelFilter = state.ui.filters.inboxChannel;
  const query = state.ui.filters.messageQuery.trim().toLowerCase();
  return state.messages.filter((message) => {
    const matchesChannel = channelFilter === 'all' || message.channel === channelFilter;
    const matchesQuery = !query || [message.author, message.text, message.contact, message.channel].some((value) => String(value).toLowerCase().includes(query));
    return matchesChannel && matchesQuery;
  });
}

function getFilteredTasks() {
  const filter = state.ui.filters.taskFilter;
  const query = state.ui.filters.taskQuery.trim().toLowerCase();
  return state.tasks.filter((task) => {
    const matchesQuery = !query || [task.title, task.origin, task.status, state.clients.find((client) => client.id === task.clientId)?.name].some((value) => String(value || '').toLowerCase().includes(query));
    if (!matchesQuery) return false;
    if (filter === 'all') return true;
    if (filter === 'overdue') return new Date(task.dueAt) < new Date() && task.status !== 'done';
    return task.status === filter;
  });
}

function getFilteredProducts() {
  const q = state.ui.filters.productQuery.trim().toLowerCase();
  return state.products.filter((item) => !q || [item.name, item.parent, item.sku, item.type].some((value) => String(value).toLowerCase().includes(q)));
}

function saveClient(formData) {
  const name = String(formData.get('name') || '').trim();
  const phone = normalizePhone(formData.get('phone'));
  const email = String(formData.get('email') || '').trim();
  const oneCId = String(formData.get('oneCId') || '').trim();
  const source = String(formData.get('source') || '').trim() || 'Сайт';
  const preferredChannel = String(formData.get('preferredChannel') || '').trim() || source;
  const tags = String(formData.get('tags') || '').split(',').map((item) => item.trim()).filter(Boolean);
  const interests = String(formData.get('interests') || '').split(',').map((item) => item.trim()).filter(Boolean);
  const wishList = String(formData.get('wishList') || '').split(',').map((item) => item.trim()).filter(Boolean);
  const notesInternal = String(formData.get('notesInternal') || '').trim();
  const quality = String(formData.get('quality') || 'B');
  const greenList = formData.get('greenList') === 'on';
  const blacklist = formData.get('blacklist') === 'on';

  if (!name) {
    toast('Заполните имя', 'Карточка клиента не может быть пустой.', 'danger');
    return;
  }

  const duplicateByPhone = phone ? findClientByPhone(phone) : null;
  const duplicateByEmail = email ? findClientByEmail(email) : null;
  const currentId = state.ui.selectedClientId;
  const editing = state.clients.find((client) => client.id === currentId);
  const duplicate = duplicateByPhone && duplicateByPhone.id !== currentId
    ? duplicateByPhone
    : duplicateByEmail && duplicateByEmail.id !== currentId
      ? duplicateByEmail
      : null;

  if (duplicate && editing) {
    mergeClients(duplicate.id, editing.id);
    return;
  }

  mutate(editing ? 'Update client' : 'Create client', name, () => {
    if (editing) {
      Object.assign(editing, {
        name,
        phone,
        email,
        oneCId,
        source,
        preferredChannel,
        tags,
        interests,
        wishList,
        notesInternal,
        quality,
        greenList,
        blacklist,
        updatedAt: nowIso(),
      });
      if (!editing.history) editing.history = [];
      editing.history.unshift({ type: 'update', text: 'Карточка обновлена вручную', at: nowIso() });
    } else {
      const created = {
        id: crypto.randomUUID(),
        name,
        phone,
        email,
        oneCId,
        source,
        preferredChannel,
        statusHint: 'Лид',
        tags,
        interests,
        discountCards: [],
        wishList,
        waitList: [...wishList],
        notesInternal,
        quality,
        blacklist,
        greenList,
        history: [{ type: 'message', text: 'Карточка создана в CRM', at: nowIso() }],
        purchases: [],
        bankPurchases: [],
        channelHistory: [source].filter(Boolean),
        createdAt: nowIso(),
        updatedAt: nowIso(),
      };
      state.clients.unshift(created);
      state.ui.selectedClientId = created.id;
    }
  });
}

function createTask(formData) {
  const title = String(formData.get('title') || '').trim();
  if (!title) return;
  const dueAt = String(formData.get('dueAt') || nowIso());
  const task = {
    id: crypto.randomUUID(),
    title,
    priority: Number(formData.get('priority') || 3),
    urgency: String(formData.get('urgency') || 'normal'),
    dueAt,
    status: String(formData.get('status') || 'new'),
    origin: String(formData.get('origin') || 'Внутренние'),
    assignedTo: String(formData.get('assignedTo') || currentUser()?.id || 'u-front'),
    clientId: String(formData.get('clientId') || '') || null,
    comments: [],
    createdAt: nowIso(),
  };
  mutate('Create task', title, () => {
    state.tasks.unshift(task);
    state.ui.selectedTaskId = task.id;
  });
}

function updateTask(taskId, updates) {
  const task = state.tasks.find((item) => item.id === taskId);
  if (!task) return;
  mutate('Update task', task.title, () => {
    Object.assign(task, updates, { updatedAt: nowIso() });
  });
}

function createMessage(formData) {
  const clientId = String(formData.get('clientId') || state.ui.selectedClientId || '').trim();
  const channel = String(formData.get('channel') || state.ui.composer.channel || 'Telegram');
  const text = String(formData.get('text') || '').trim();
  if (!text) return;
  const client = state.clients.find((item) => item.id === clientId);
  const message = {
    id: crypto.randomUUID(),
    channel,
    direction: 'out',
    contact: client?.phone || client?.email || 'direct',
    clientId: client?.id || null,
    author: currentUser()?.name || 'Менеджер',
    text,
    createdAt: nowIso(),
    unread: false,
    assignedTo: currentUser()?.id || null,
  };
  mutate('Send message', text, () => {
    state.messages.unshift(message);
    if (client) {
      client.channelHistory = Array.from(new Set([...(client.channelHistory || []), channel]));
      client.history.unshift({ type: 'message', text: `Отправлено сообщение через ${channel}`, at: nowIso() });
      client.updatedAt = nowIso();
    }
    const matchedTask = state.tasks.find((task) => task.clientId === client?.id && task.status !== 'done');
    if (matchedTask) matchedTask.comments.push({ author: currentUser()?.name || 'Менеджер', text, at: nowIso() });
  });
}

function applyCsvImport(text) {
  const lines = String(text || '').trim().split(/\r?\n/).filter(Boolean);
  if (!lines.length) return;
  const [headerLine, ...rows] = lines;
  const headers = headerLine.split(',').map((value) => value.trim());
  mutate('Import CSV', `${rows.length} rows`, () => {
    const imported = [];
    rows.forEach((line) => {
      const values = line.split(',');
      const row = Object.fromEntries(headers.map((header, index) => [header, (values[index] || '').trim()]));
      const existing = state.users.find((user) => user.login === row.login);
      if (existing) {
        Object.assign(existing, {
          name: row.name || existing.name,
          role: row.role || existing.role,
          email: row.email || existing.email,
          active: String(row.active || existing.active) === 'true',
        });
        imported.push(`updated:${existing.login}`);
        return;
      }
      state.users.push({
        id: crypto.randomUUID(),
        login: row.login,
        password: row.password || 'temp123',
        name: row.name || row.login,
        role: row.role || 'front',
        email: row.email || '',
        active: String(row.active || 'true') === 'true',
        schedule: row.schedule || '09:00-18:00',
      });
      imported.push(`created:${row.login}`);
    });
    state.audit.unshift({
      id: crypto.randomUUID(),
      actor: currentUser()?.name || 'Система',
      ip: state.security.sessionIp,
      action: 'CSV import summary',
      before: `rows:${rows.length}`,
      after: `imported:${rows.length}`,
      at: nowIso(),
    });
  });
  toast('CSV импорт выполнен', `${rows.length} строк обработано без дублей.`, 'good');
}

function exportData() {
  const payload = JSON.stringify({
    clients: state.clients,
    tasks: state.tasks,
    messages: state.messages,
    products: state.products,
    users: state.users,
    audit: state.audit,
  }, null, 2);
  const blob = new Blob([payload], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `plant-crm-export-${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  URL.revokeObjectURL(url);
  toast('Экспорт готов', 'Скачан JSON со всей базой.', 'good');
}

function import1C() {
  mutate('Sync 1C', 'Inventory refreshed', () => {
    state.products = state.products.map((product) => {
      const drift = Math.round((Math.random() - 0.5) * 3);
      const nextStock = Math.max(0, product.stock + drift);
      const stock = nextStock;
      const status = stock <= 2 ? 'critical' : stock <= 6 ? 'low' : 'ok';
      return {
        ...product,
        stock,
        status,
        updatedAt: nowIso(),
      };
    });
    const lowStock = state.products.filter((item) => item.status !== 'ok');
    if (lowStock.length) {
      state.tasks.unshift({
        id: crypto.randomUUID(),
        title: `Автозадача: проверить остатки ${lowStock[0].name}`,
        priority: 4,
        urgency: 'system',
        dueAt: nowIso(),
        status: 'new',
        origin: 'Системные',
        assignedTo: 'u-back',
        clientId: null,
        comments: [{ author: 'CRM', text: 'Создано после синхронизации с 1С.', at: nowIso() }],
        createdAt: nowIso(),
      });
    }
  });
  toast('1С синхронизирована', 'Остатки и статусы обновлены.', 'good');
}

function bankImport() {
  mutate('Bank CSV import', 'Unconfirmed purchases marked', () => {
    const target = state.clients.find((client) => client.bankPurchases?.some((purchase) => !purchase.matched));
    if (target) {
      target.bankPurchases = target.bankPurchases.map((purchase) => ({ ...purchase, matched: true }));
      target.history.unshift({ type: 'purchase', text: 'Оплата подтверждена по банковской выписке', at: nowIso() });
      target.updatedAt = nowIso();
    }
  });
  toast('Выписка обработана', 'Неподтвержденные покупки сопоставлены.', 'good');
}

function triggerFollowUp() {
  const client = state.clients.find((item) => item.wishList?.some((wish) => state.products.some((product) => product.name === wish && product.stock > 0)));
  if (!client) {
    toast('Триггер не найден', 'Нет совпадений по wishlist и остаткам.', 'warn');
    return;
  }
  mutate('Auto follow-up', client.name, () => {
    state.tasks.unshift({
      id: crypto.randomUUID(),
      title: `Follow-up: продать товар из wishlist для ${client.name}`,
      priority: 2,
      urgency: 'system',
      dueAt: nowIso(),
      status: 'new',
      origin: 'Системные',
      assignedTo: 'u-front',
      clientId: client.id,
      comments: [{ author: 'CRM', text: 'Сработал триггер по появлению товара в наличии.', at: nowIso() }],
      createdAt: nowIso(),
    });
  });
  toast('Автотриггер создан', `Сотруднику назначена продажа для ${client.name}.`, 'good');
}

function triggerScript(messageText) {
  const text = String(messageText || '').toLowerCase();
  const script = state.scripts.find((item) => text.includes(item.trigger));
  if (!script) return 'Подобранный скрипт отсутствует';
  const product = state.products.find((item) => item.stock > 0);
  const stock = product?.stock ?? 1;
  return script.answerTemplate.replace('{stock}', String(stock));
}

function selectView(view) {
  if (!canAccess(view)) return;
  state.ui.view = view;
  persistState();
  scheduleRender();
}

function setFilter(name, value) {
  state.ui.filters[name] = value;
  persistState();
  scheduleRender();
}

function selectTask(taskId) {
  state.ui.selectedTaskId = taskId;
  persistState();
  scheduleRender();
}

function selectProduct(productId) {
  state.ui.selectedProductId = productId;
  persistState();
  scheduleRender();
}

function renderLogin() {
  const demoUsers = state.users.map((user) => `<li><strong>${escapeHtml(user.login)}</strong> / ${escapeHtml(user.password)} / ${escapeHtml(user.role === 'admin' ? 'без кода' : state.ui.loginCodeHint)}</li>`).join('');
  root.innerHTML = `
    <div class="auth-shell fade-in">
      <section class="auth-hero">
        <div class="auth-hero-card">
          <div class="kicker">CRM для магазина растений</div>
          <h1 class="brand-title">Plant<span>Flow</span> CRM</h1>
          <p class="hero-copy">
            Единое окно для входящих сообщений, клиентов, склада, скриптов, обучения и аналитики.
            Каркас уже включает авторизацию, роли, антифрод, аудит действий и сценарии автоматизации из ТЗ.
          </p>
          <div class="feature-grid">
            <div class="feature">
              <strong>Авторизация</strong>
              Логин, пароль и код для сотрудников. Админ входит по логину и паролю.
            </div>
            <div class="feature">
              <strong>Омниканал</strong>
              Telegram, VK, WhatsApp, Email, сайт, Flowwow и Авито.
            </div>
            <div class="feature">
              <strong>Автоматизация</strong>
              Скрипты, follow-up, триггеры по остаткам и быстрый тест знаний.
            </div>
            <div class="feature">
              <strong>Контроль</strong>
              Логирование, тайм-трекинг, блокировка аномалий и роли доступа.
            </div>
          </div>
        </div>
      </section>
      <section class="auth-panel">
        <form class="login-card card" data-form="login">
          <h2>Вход в систему</h2>
          <p class="section-desc">Для демо используйте любой аккаунт из подсказки ниже.</p>
          <div class="field">
            <label for="login">Логин</label>
            <input id="login" name="login" autocomplete="username" placeholder="admin / front / hybrid" required />
          </div>
          <div class="field">
            <label for="password">Пароль</label>
            <input id="password" name="password" type="password" autocomplete="current-password" placeholder="admin123" required />
          </div>
          <div class="field">
            <label for="code">Код из почты сотрудника</label>
            <input id="code" name="code" inputmode="numeric" placeholder="246810" />
          </div>
          <div class="row">
            <button class="btn primary" type="submit">Войти</button>
            <button class="btn" type="button" data-action="send-code">Отправить код</button>
          </div>
          <div class="divider"></div>
          <div class="ghost-box">
            <strong>Демо-доступы</strong>
            <ul style="margin: 10px 0 0; padding-left: 18px; color: var(--muted); line-height: 1.7;">
              ${demoUsers}
            </ul>
          </div>
        </form>
      </section>
    </div>
  `;
}

function renderShell(viewHtml) {
  const user = currentUser();
  const role = currentRole();
  const navItems = [
    ['dashboard', 'Дашборд'],
    ['inbox', 'Единое окно'],
    ['clients', 'Клиенты'],
    ['tasks', 'Тикеты'],
    ['products', 'Склад и 1С'],
    ['knowledge', 'Обучение'],
    ['analytics', 'Аналитика'],
    ['admin', 'Админка'],
  ];
  const nav = navItems.map(([key, label]) => {
    const disabled = !canAccess(key);
    return `<button class="${state.ui.view === key ? 'active' : ''}" data-action="nav" data-view="${key}" ${disabled ? 'disabled' : ''}><span>${label}</span><span>${disabled ? '—' : '›'}</span></button>`;
  }).join('');
  root.innerHTML = `
    <div class="app-shell fade-in">
      <aside class="sidebar">
        <div class="brand">
          <p class="name">PlantFlow CRM</p>
          <p class="meta">${escapeHtml(user?.name || 'Гость')} · ${escapeHtml(roleLabel(role))}</p>
        </div>
        <nav class="nav">${nav}</nav>
        <div class="sidebar-footer">
          <div class="pill-row">
            <span class="chip good">${escapeHtml(user?.active ? 'Online' : 'Offline')}</span>
            <span class="chip info">${escapeHtml(state.security.sessionIp)}</span>
          </div>
          <div style="margin-top: 10px; color: var(--muted); font-size: 13px; line-height: 1.6;">
            Последняя активность: ${escapeHtml(formatDateTime(state.security.lastActivityAt))}
          </div>
        </div>
      </aside>
      <main class="content">
        <header class="topbar">
          <div>
            <h1>${escapeHtml(pageTitle(state.ui.view))}</h1>
            <p class="sub">${escapeHtml(pageSubtitle(state.ui.view))}</p>
          </div>
          <div class="topbar-actions">
            <button class="btn" data-action="quick-test">Быстрый тест</button>
            <button class="btn" data-action="seed-task">Новая задача</button>
            <button class="btn danger" data-action="logout">Выйти</button>
          </div>
        </header>
        <section class="layout">
          ${state.security.blocked ? blockedBanner() : ''}
          ${viewHtml}
        </section>
      </main>
    </div>
    <div class="toast-stack">
      ${state.notifications.slice(0, 3).map(renderToast).join('')}
    </div>
    ${state.ui.quickTest ? renderQuickTestModal() : ''}
  `;
}

function pageTitle(view) {
  return {
    dashboard: 'Дашборд',
    inbox: 'Единое окно',
    clients: 'База клиентов',
    tasks: 'Тикеты и приоритеты',
    products: 'Склад, товары и 1С',
    knowledge: 'Обучение и база знаний',
    analytics: 'Панель аналитики',
    admin: 'Панель администратора',
  }[view] || 'CRM';
}

function pageSubtitle(view) {
  return {
    dashboard: 'Приоритеты, статусы, события и быстрые действия.',
    inbox: 'Telegram, VK, WhatsApp, Email, сайт, Flowwow и Авито в одном окне.',
    clients: 'Поиск по контактам, хотелкам, статусам, тегам и истории покупок.',
    tasks: 'Ручные, внутренние и системные тикеты с дедлайнами и комментариями.',
    products: 'Остатки, динамика, лист ушедшего в производство и приемка из 1С.',
    knowledge: 'Регламенты, скрипты, новости и быстрый тест знаний.',
    analytics: 'Показатели выручки, каналов, сотрудников и товарных остатков.',
    admin: 'Пользователи, словари, импорт/экспорт, логирование и контроль.',
  }[view] || '';
}

function blockedBanner() {
  return `
    <div class="hero-banner">
      <div>
        <p class="title">Права сотрудника временно ограничены</p>
        <p>${escapeHtml(state.security.blockReason || 'Срабатывание антифрода')}</p>
      </div>
      <button class="btn primary" data-action="admin-unblock">Снять блок</button>
    </div>
  `;
}

function renderToast(item) {
  return `<div class="toast">
    <strong>${escapeHtml(item.title)}</strong>
    <p>${escapeHtml(item.text)}</p>
  </div>`;
}

function renderQuickTestModal() {
  return `
    <div class="modal-backdrop">
      <div class="modal">
        <h3>Быстрый тест</h3>
        <p class="section-desc">Рабочий экран продолжится после правильного ответа.</p>
        <div class="ghost-box">${escapeHtml(state.ui.quickTest.question)}</div>
        <form class="form-grid" data-form="quick-test" style="margin-top: 14px;">
          <div class="field">
            <label for="quickAnswer">Ответ</label>
            <input id="quickAnswer" name="quickAnswer" autofocus required />
          </div>
          <div class="row">
            <button class="btn primary" type="submit">Проверить</button>
            <button class="btn" type="button" data-action="close-quick-test">Отложить</button>
          </div>
        </form>
      </div>
    </div>
  `;
}

function renderDashboard() {
  const user = currentUser();
  const overdue = state.tasks.filter((task) => task.status !== 'done' && new Date(task.dueAt) < new Date());
  const replies = state.messages.filter((message) => message.direction === 'in' && message.unread).length;
  const revenueToday = state.clients.flatMap((client) => client.purchases || []).reduce((sum, purchase) => sum + purchase.amount, 0);
  const activeChats = state.messages.filter((message) => message.unread).length;
  const queue = [...state.tasks].sort((a, b) => a.priority - b.priority || new Date(a.dueAt) - new Date(b.dueAt));
  const messages = [...state.messages].sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
  return `
    <div class="hero-banner">
      <div>
        <p class="title">Добро пожаловать, ${escapeHtml(user?.name || 'менеджер')}</p>
        <p>Очередь тикетов выстроена по приоритетам. Просроченные задачи мигают в списке, а скрипты помогают отвечать быстрее.</p>
      </div>
      <div class="pill-row">
        <span class="chip good">Физ. вход: ${escapeHtml(formatTime(state.auth.lastLoginAt || nowIso()))}</span>
        <span class="chip info">IP ${escapeHtml(state.security.sessionIp)}</span>
      </div>
    </div>

    <div class="grid-cards">
      <div class="metric">
        <div class="label">Новые лиды</div>
        <div class="value">${state.clients.filter((client) => clientStatus(client) === 'Лид').length}</div>
        <div class="delta">+4 за 7 дней</div>
      </div>
      <div class="metric">
        <div class="label">Активные чаты</div>
        <div class="value">${activeChats}</div>
        <div class="delta">${replies} новых входящих</div>
      </div>
      <div class="metric">
        <div class="label">Просрочено</div>
        <div class="value">${overdue.length}</div>
        <div class="delta">${queue.length} тикетов всего</div>
      </div>
      <div class="metric">
        <div class="label">Выручка</div>
        <div class="value">${formatMoney(revenueToday)}</div>
        <div class="delta">По покупкам из базы</div>
      </div>
    </div>

    <div class="dashboard-grid">
      <section class="panel">
        <h3>Приоритетная очередь</h3>
        <div class="mini-list">
          ${queue.slice(0, 6).map((task) => `
            <div class="mini-item">
              <div class="head">
                <strong class="title">${escapeHtml(task.title)}</strong>
                <span class="chip ${statusChip(task.status)}">${escapeHtml(taskPriorityLabel(task.priority))}</span>
              </div>
              <div class="meta">
                ${escapeHtml(task.origin)} · ${escapeHtml(task.assignedTo ? roleLabel(state.users.find((u) => u.id === task.assignedTo)?.role) : 'Без назначенца')} · дедлайн ${escapeHtml(formatDateTime(task.dueAt))}
              </div>
              <div class="row">
                <button class="btn" data-action="open-task" data-task-id="${escapeHtml(task.id)}">Открыть</button>
                <button class="btn" data-action="task-done" data-task-id="${escapeHtml(task.id)}">Готово</button>
              </div>
            </div>
          `).join('')}
        </div>
      </section>

      <section class="panel">
        <h3>Входящие</h3>
        <div class="mini-list">
          ${messages.slice(0, 5).map((message) => `
            <div class="mini-item">
              <div class="head">
                <strong class="title">${escapeHtml(message.author)} · ${escapeHtml(message.channel)}</strong>
                <span class="chip ${message.direction === 'in' ? 'warn' : 'good'}">${escapeHtml(message.direction === 'in' ? 'Входящее' : 'Исходящее')}</span>
              </div>
              <div class="meta">${escapeHtml(message.text)}</div>
              <div class="row">
                <button class="btn" data-action="open-message-client" data-client-id="${escapeHtml(message.clientId || '')}">Карточка</button>
                <button class="btn" data-action="reply-template" data-channel="${escapeHtml(message.channel)}" data-client-id="${escapeHtml(message.clientId || '')}" data-text="${escapeHtml(triggerScript(message.text))}">Ответ по скрипту</button>
              </div>
            </div>
          `).join('')}
        </div>
      </section>

      <section class="panel">
        <h3>Скрипты и новости</h3>
        <div class="stack">
          <div class="ghost-box">
            <strong>Триггер:</strong> ${escapeHtml(triggerScript('есть ли наличие'))}
          </div>
          ${state.news.slice(0, 3).map((news) => `
            <div class="mini-item">
              <div class="head">
                <strong class="title">${escapeHtml(news.title)}</strong>
                <span class="chip info">${escapeHtml(formatDateTime(news.at))}</span>
              </div>
              <div class="meta">${escapeHtml(news.body)}</div>
            </div>
          `).join('')}
        </div>
      </section>
    </div>
  `;
}

function renderInbox() {
  const filtered = getFilteredMessages();
  const selected = filtered[0] || state.messages[0];
  const client = state.clients.find((item) => item.id === selected?.clientId) || currentClient();
  const channelOptions = ['all', ...state.channels];
  return `
    <div class="panel">
      <div class="row" style="justify-content: space-between;">
        <div>
          <h3 class="section-title">Единое окно</h3>
          <p class="section-desc">Работаем с Telegram, VK, WhatsApp, Email, сайтом, Flowwow и Авито.</p>
        </div>
        <div class="row">
          <button class="btn" data-action="simulate-incoming">Смоделировать входящее</button>
        </div>
      </div>
      <div class="searchbar">
        <input placeholder="Фильтр по тексту, клиенту, каналу..." value="${escapeHtml(state.ui.filters.messageQuery)}" data-input="inbox-search" />
        <select data-input="inbox-channel">
          ${channelOptions.map((channel) => `<option value="${escapeHtml(channel)}" ${state.ui.filters.inboxChannel === channel ? 'selected' : ''}>${escapeHtml(channel === 'all' ? 'Все каналы' : channel)}</option>`).join('')}
        </select>
        <button class="btn primary" data-action="create-message-from-selection">Отправить ответ</button>
      </div>
    </div>

    <div class="split-grid">
      <section class="panel">
        <h3>Лента сообщений</h3>
        <div class="mini-list">
          ${filtered.map((message) => `
            <div class="mini-item" style="${message.id === selected?.id ? 'border-color: rgba(114, 211, 154, 0.5);' : ''}">
              <div class="head">
                <strong class="title">${escapeHtml(message.author)} · ${escapeHtml(message.channel)}</strong>
                <span class="chip ${message.direction === 'in' ? 'warn' : 'good'}">${escapeHtml(message.direction === 'in' ? 'Входящее' : 'Исходящее')}</span>
              </div>
              <div class="meta">${escapeHtml(message.text)}</div>
              <div class="row">
                <span class="chip info">${escapeHtml(formatDateTime(message.createdAt))}</span>
                <button class="btn" data-action="select-client" data-client-id="${escapeHtml(message.clientId || '')}">Открыть клиента</button>
              </div>
            </div>
          `).join('')}
        </div>
      </section>

      <aside class="drawer">
        <section class="panel sidebar-card">
          <h3>Карточка клиента</h3>
          ${client ? `
            <div class="mini-item">
              <div class="head">
                <strong class="title">${escapeHtml(client.name)}</strong>
                <span class="chip ${statusChip(clientStatus(client))}">${escapeHtml(clientStatus(client))}</span>
              </div>
              <div class="meta">${escapeHtml(client.phone || 'без телефона')} · ${escapeHtml(client.email || 'без email')}</div>
              <div class="pill-row">
                ${(client.tags || []).map((tag) => `<span class="chip info">${escapeHtml(tag)}</span>`).join('')}
              </div>
              <div class="row">
                <button class="btn primary" data-action="open-write" data-client-id="${escapeHtml(client.id)}" data-channel="${escapeHtml(client.preferredChannel || 'Telegram')}">Написать</button>
                <button class="btn" data-action="open-client" data-client-id="${escapeHtml(client.id)}">Открыть</button>
              </div>
            </div>
          ` : '<div class="empty-state">Сообщение пока не привязано к клиенту.</div>'}
        </section>
        <section class="panel sidebar-card">
          <h3>Комментировать ответ</h3>
          <form class="form-grid" data-form="reply">
            <input type="hidden" name="clientId" value="${escapeHtml(client?.id || '')}" />
            <div class="field">
              <label>Канал</label>
              <select name="channel">
                ${state.channels.map((channel) => `<option value="${escapeHtml(channel)}" ${state.ui.composer.channel === channel ? 'selected' : ''}>${escapeHtml(channel)}</option>`).join('')}
              </select>
            </div>
            <div class="field">
              <label>Текст</label>
              <textarea name="text" placeholder="Введите ответ..." required>${escapeHtml(state.ui.composer.text || triggerScript(selected?.text || ''))}</textarea>
            </div>
            <button class="btn primary" type="submit">Отправить</button>
          </form>
        </section>
      </aside>
    </div>
  `;
}

function renderClients() {
  const clients = getFilteredClients();
  const selected = currentClient();
  return `
    <div class="panel">
      <div class="row" style="justify-content: space-between; align-items: end;">
        <div>
          <h3 class="section-title">База клиентов</h3>
          <p class="section-desc">Уникальность по телефону, склейка дублей, история переписки и лист ожидания.</p>
        </div>
        <div class="row">
          <button class="btn" data-action="add-sample-client">Быстрый лид</button>
          <button class="btn primary" data-action="sync-from-bank">Сверка банка</button>
        </div>
      </div>
      <div class="searchbar">
        <input placeholder="Поиск по ФИО, контакту, тегам..." value="${escapeHtml(state.ui.filters.clientQuery)}" data-input="client-query" />
        <select data-input="client-status">
          <option value="all" ${state.ui.filters.clientStatus === 'all' ? 'selected' : ''}>Все статусы</option>
          <option value="Покупатель" ${state.ui.filters.clientStatus === 'Покупатель' ? 'selected' : ''}>Покупатель</option>
          <option value="Лид" ${state.ui.filters.clientStatus === 'Лид' ? 'selected' : ''}>Лид</option>
          <option value="Нераспознанный" ${state.ui.filters.clientStatus === 'Нераспознанный' ? 'selected' : ''}>Нераспознанный</option>
        </select>
        <select data-input="client-channel">
          <option value="all" ${state.ui.filters.clientChannel === 'all' ? 'selected' : ''}>Все каналы</option>
          ${state.channels.map((channel) => `<option value="${escapeHtml(channel)}" ${state.ui.filters.clientChannel === channel ? 'selected' : ''}>${escapeHtml(channel)}</option>`).join('')}
        </select>
      </div>
    </div>

    <div class="split-grid">
      <section class="panel">
        <h3>Карточки</h3>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Клиент</th>
                <th>Контакты</th>
                <th>Статус</th>
                <th>Источник</th>
                <th>Теги</th>
              </tr>
            </thead>
            <tbody>
              ${clients.map((client) => `
                <tr style="${selected?.id === client.id ? 'background: rgba(114, 211, 154, 0.08);' : ''}" data-action="select-client-row" data-client-id="${escapeHtml(client.id)}">
                  <td>
                    <div><strong>${escapeHtml(client.name)}</strong></div>
                    <div class="meta">${escapeHtml(client.oneCId || 'Без 1С ID')}</div>
                  </td>
                  <td>${escapeHtml(client.phone || '—')}<br>${escapeHtml(client.email || '—')}</td>
                  <td><span class="chip ${statusChip(clientStatus(client))}">${escapeHtml(clientStatus(client))}</span></td>
                  <td>${escapeHtml(client.source || '—')}</td>
                  <td>${(client.tags || []).slice(0, 3).map((tag) => `<span class="chip info" style="margin: 0 6px 6px 0;">${escapeHtml(tag)}</span>`).join('')}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </section>

      <aside class="drawer">
        <section class="panel sidebar-card">
          <h3>Карточка клиента</h3>
          ${selected ? renderClientDetail(selected) : '<div class="empty-state">Выберите карточку.</div>'}
        </section>
        <section class="panel sidebar-card">
          <h3>Новая карточка</h3>
          ${renderClientForm(selected)}
        </section>
      </aside>
    </div>
  `;
}

function renderClientDetail(client) {
  const duplicate = state.clients.find((item) => item.id !== client.id && (normalizePhone(item.phone) === normalizePhone(client.phone) && client.phone || item.email === client.email && client.email));
  return `
    <div class="mini-item">
      <div class="head">
        <strong class="title">${escapeHtml(client.name)}</strong>
        <span class="chip ${statusChip(clientStatus(client))}">${escapeHtml(clientStatus(client))}</span>
      </div>
      <div class="meta">${escapeHtml(client.phone || '—')} · ${escapeHtml(client.email || '—')}</div>
      <div class="pill-row">
        ${(client.interests || []).map((item) => `<span class="chip good">${escapeHtml(item)}</span>`).join('')}
      </div>
      <div class="pill-row">
        ${(client.waitList || []).map((item) => `<span class="chip warn">Want: ${escapeHtml(item)}</span>`).join('')}
      </div>
      <div class="ghost-box">Скрытое поле: ${escapeHtml(client.quality)} · ${client.greenList ? 'Зеленый список' : 'Не отмечен'}${client.blacklist ? ' · Черный список' : ''}</div>
      <div class="row">
        <button class="btn primary" data-action="open-write" data-client-id="${escapeHtml(client.id)}" data-channel="${escapeHtml(client.preferredChannel || 'Telegram')}">Написать</button>
        <button class="btn" data-action="open-client" data-client-id="${escapeHtml(client.id)}">Открыть</button>
        ${duplicate ? `<button class="btn danger" data-action="merge-with-duplicate" data-target-id="${escapeHtml(client.id)}" data-source-id="${escapeHtml(duplicate.id)}">Склеить дубликат</button>` : ''}
      </div>
      <div class="divider"></div>
      <div class="stack">
        ${client.history.slice(0, 5).map((item) => `
          <div class="mini-item">
            <div class="head">
              <strong class="title">${escapeHtml(item.type)}</strong>
              <span class="chip info">${escapeHtml(formatDateTime(item.at))}</span>
            </div>
            <div class="meta">${escapeHtml(item.text)}</div>
          </div>
        `).join('')}
      </div>
    </div>
  `;
}

function renderClientForm(client) {
  return `
    <form class="form-grid" data-form="client">
      <input type="hidden" name="clientId" value="${escapeHtml(client?.id || '')}" />
      <div class="field">
        <label>ФИО</label>
        <input name="name" value="${escapeHtml(client?.name || '')}" placeholder="Имя клиента" required />
      </div>
      <div class="grid-2">
        <div class="field">
          <label>Телефон</label>
          <input name="phone" value="${escapeHtml(client?.phone || '')}" placeholder="+79990000000" />
        </div>
        <div class="field">
          <label>Email</label>
          <input name="email" type="email" value="${escapeHtml(client?.email || '')}" placeholder="client@example.com" />
        </div>
      </div>
      <div class="grid-2">
        <div class="field">
          <label>ID 1С</label>
          <input name="oneCId" value="${escapeHtml(client?.oneCId || '')}" placeholder="1C-1001" />
        </div>
        <div class="field">
          <label>Источник</label>
          <input name="source" value="${escapeHtml(client?.source || '')}" placeholder="Telegram" />
        </div>
      </div>
      <div class="field">
        <label>Предпочтительный канал</label>
        <select name="preferredChannel">
          ${state.channels.map((channel) => `<option value="${escapeHtml(channel)}" ${(client?.preferredChannel || client?.source) === channel ? 'selected' : ''}>${escapeHtml(channel)}</option>`).join('')}
        </select>
      </div>
      <div class="field">
        <label>Теги</label>
        <input name="tags" value="${escapeHtml((client?.tags || []).join(', '))}" placeholder="доставка, орхидеи" />
      </div>
      <div class="field">
        <label>Интересы</label>
        <input name="interests" value="${escapeHtml((client?.interests || []).join(', '))}" placeholder="Комнатные растения, Суккуленты" />
      </div>
      <div class="field">
        <label>Лист ожидания / хотелки</label>
        <input name="wishList" value="${escapeHtml((client?.wishList || []).join(', '))}" placeholder="Фикус Лирата, Монстера" />
      </div>
      <div class="field">
        <label>Внутреннее примечание</label>
        <textarea name="notesInternal" placeholder="Зеленый список / Черный список / Качество лида">${escapeHtml(client?.notesInternal || '')}</textarea>
      </div>
      <div class="grid-2">
        <div class="field">
          <label>Качество</label>
          <select name="quality">
            <option value="A" ${client?.quality === 'A' ? 'selected' : ''}>A</option>
            <option value="B" ${client?.quality === 'B' ? 'selected' : ''}>B</option>
            <option value="C" ${client?.quality === 'C' ? 'selected' : ''}>C</option>
          </select>
        </div>
        <div class="field">
          <label>&nbsp;</label>
          <div class="row">
            <label class="chip"><input type="checkbox" name="greenList" ${client?.greenList ? 'checked' : ''} /> Зеленый список</label>
            <label class="chip"><input type="checkbox" name="blacklist" ${client?.blacklist ? 'checked' : ''} /> Черный список</label>
          </div>
        </div>
      </div>
      <div class="row">
        <button class="btn primary" type="submit">Сохранить</button>
        <button class="btn" type="button" data-action="open-write" data-client-id="${escapeHtml(client?.id || '')}" data-channel="${escapeHtml(client?.preferredChannel || 'Telegram')}">Написать</button>
      </div>
    </form>
  `;
}

function renderTasks() {
  const tasks = getFilteredTasks();
  const selected = state.tasks.find((task) => task.id === state.ui.selectedTaskId) || tasks[0];
  return `
    <div class="panel">
      <div class="row" style="justify-content: space-between;">
        <div>
          <h3 class="section-title">Тикеты и приоритеты</h3>
          <p class="section-desc">Руководство, внутренние задачи, клиенты и системные автозадачи.</p>
        </div>
        <div class="row">
          <button class="btn primary" data-action="create-task-template">Новый тикет</button>
        </div>
      </div>
      <div class="searchbar">
        <input placeholder="Поиск по задаче..." value="${escapeHtml(state.ui.filters.taskQuery)}" data-input="task-query" />
        <select data-input="task-filter">
          <option value="all" ${state.ui.filters.taskFilter === 'all' ? 'selected' : ''}>Все</option>
          <option value="new" ${state.ui.filters.taskFilter === 'new' ? 'selected' : ''}>Новые</option>
          <option value="in_progress" ${state.ui.filters.taskFilter === 'in_progress' ? 'selected' : ''}>В работе</option>
          <option value="waiting" ${state.ui.filters.taskFilter === 'waiting' ? 'selected' : ''}>Ожидают</option>
          <option value="done" ${state.ui.filters.taskFilter === 'done' ? 'selected' : ''}>Готово</option>
          <option value="overdue" ${state.ui.filters.taskFilter === 'overdue' ? 'selected' : ''}>Просроченные</option>
        </select>
        <div class="ghost-box">Автологика: ${escapeHtml(state.tasks.filter((task) => task.origin === 'Системные').length)} системных задач</div>
      </div>
    </div>

    <div class="split-grid">
      <section class="panel">
        <h3>Очередь</h3>
        <div class="mini-list">
          ${tasks.map((task) => `
            <div class="mini-item" style="${selected?.id === task.id ? 'border-color: rgba(114, 211, 154, 0.5);' : ''}">
              <div class="head">
                <strong class="title">${escapeHtml(task.title)}</strong>
                <span class="chip ${task.status === 'done' ? 'good' : task.status === 'waiting' ? 'warn' : 'info'}">${escapeHtml(taskPriorityLabel(task.priority))}</span>
              </div>
              <div class="meta">${escapeHtml(task.origin)} · ${escapeHtml(task.clientId ? state.clients.find((client) => client.id === task.clientId)?.name || 'Клиент' : 'Без клиента')} · дедлайн ${escapeHtml(formatDateTime(task.dueAt))}</div>
              <div class="row">
                <button class="btn" data-action="select-task" data-task-id="${escapeHtml(task.id)}">Открыть</button>
                <button class="btn" data-action="task-progress" data-task-id="${escapeHtml(task.id)}">В работу</button>
                <button class="btn" data-action="task-done" data-task-id="${escapeHtml(task.id)}">Готово</button>
              </div>
            </div>
          `).join('')}
        </div>
      </section>

      <aside class="drawer">
        <section class="panel sidebar-card">
          <h3>Детали</h3>
          ${selected ? `
            <div class="mini-item">
              <div class="head">
                <strong class="title">${escapeHtml(selected.title)}</strong>
                <span class="chip ${selected.status === 'done' ? 'good' : selected.status === 'waiting' ? 'warn' : 'info'}">${escapeHtml(selected.status)}</span>
              </div>
              <div class="meta">${escapeHtml(selected.origin)} · ${escapeHtml(formatDateTime(selected.createdAt))}</div>
              <div class="divider"></div>
              <div class="stack">
                ${(selected.comments || []).map((comment) => `
                  <div class="ghost-box">
                    <strong>${escapeHtml(comment.author)}</strong>
                    <div style="color: var(--muted);">${escapeHtml(comment.text)}</div>
                    <div class="meta">${escapeHtml(formatDateTime(comment.at))}</div>
                  </div>
                `).join('')}
              </div>
            </div>
          ` : '<div class="empty-state">Нет выбранной задачи.</div>'}
        </section>
        <section class="panel sidebar-card">
          <h3>Создать тикет</h3>
          <form class="form-grid" data-form="task">
            <div class="field"><label>Название</label><input name="title" placeholder="Например, срочный ответ..." required /></div>
            <div class="grid-2">
              <div class="field"><label>Приоритет</label><select name="priority"><option value="1">1</option><option value="2">2</option><option value="3" selected>3</option><option value="4">4</option></select></div>
              <div class="field"><label>Статус</label><select name="status"><option value="new">new</option><option value="in_progress">in_progress</option><option value="waiting">waiting</option></select></div>
            </div>
            <div class="grid-2">
              <div class="field"><label>Источник</label><input name="origin" value="Внутренние" /></div>
              <div class="field"><label>Назначить</label><select name="assignedTo">${state.users.map((user) => `<option value="${escapeHtml(user.id)}">${escapeHtml(user.name)}</option>`).join('')}</select></div>
            </div>
            <div class="field"><label>Дедлайн</label><input name="dueAt" type="datetime-local" /></div>
            <button class="btn primary" type="submit">Создать</button>
          </form>
        </section>
      </aside>
    </div>
  `;
}

function renderProducts() {
  const products = getFilteredProducts();
  const selected = state.products.find((item) => item.id === state.ui.selectedProductId) || products[0];
  const goingToProduction = state.products.filter((item) => item.inProduction > 0);
  const totalStock = state.products.reduce((sum, item) => sum + item.stock, 0);
  const totalValue = state.products.reduce((sum, item) => sum + item.stock * item.price, 0);
  return `
    <div class="panel">
      <div class="row" style="justify-content: space-between;">
        <div>
          <h3 class="section-title">Склад и 1С</h3>
          <p class="section-desc">Регулярная синхронизация остатков, продажи, списания и лист ушедшего в производство.</p>
        </div>
        <div class="row">
          <button class="btn primary" data-action="sync-1c">Импорт из 1С</button>
          <button class="btn" data-action="bank-import">CSV банка</button>
        </div>
      </div>
      <div class="searchbar">
        <input placeholder="Поиск по товару..." value="${escapeHtml(state.ui.filters.productQuery)}" data-input="product-query" />
        <div class="ghost-box">В наличии: ${totalStock} шт.</div>
        <div class="ghost-box">На сумму: ${formatMoney(totalValue)}</div>
      </div>
    </div>

    <div class="split-grid">
      <section class="panel">
        <h3>Каталог</h3>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Товар</th>
                <th>Тип</th>
                <th>Остаток</th>
                <th>Резерв</th>
                <th>Цена</th>
              </tr>
            </thead>
            <tbody>
              ${products.map((product) => `
                <tr style="${selected?.id === product.id ? 'background: rgba(114, 211, 154, 0.08);' : ''}">
                  <td>
                    <strong>${escapeHtml(product.name)}</strong>
                    <div class="meta">${escapeHtml(product.parent)} · ${escapeHtml(product.sku)}</div>
                  </td>
                  <td><span class="chip info">${escapeHtml(product.type === 'plant' ? 'Комнатное растение' : 'Прочее')}</span></td>
                  <td><span class="chip ${product.status === 'critical' ? 'danger' : product.status === 'low' ? 'warn' : 'good'}">${escapeHtml(String(product.stock))}</span></td>
                  <td>${escapeHtml(String(product.reserve))}</td>
                  <td>${formatMoney(product.price)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </section>

      <aside class="drawer">
        <section class="panel sidebar-card">
          <h3>Детали товара</h3>
          ${selected ? `
            <div class="mini-item">
              <div class="head">
                <strong class="title">${escapeHtml(selected.name)}</strong>
                <span class="chip ${selected.status === 'critical' ? 'danger' : selected.status === 'low' ? 'warn' : 'good'}">${escapeHtml(selected.status)}</span>
              </div>
              <div class="meta">${escapeHtml(selected.parent)} · ${escapeHtml(selected.sku)}</div>
              <div class="ghost-box">Лист ушедшего в производство: ${escapeHtml(String(selected.inProduction))} шт.</div>
            </div>
          ` : '<div class="empty-state">Выберите товар.</div>'}
        </section>
        <section class="panel sidebar-card">
          <h3>На производство</h3>
          <div class="mini-list">
            ${goingToProduction.map((product) => `
              <div class="mini-item">
                <div class="head">
                  <strong class="title">${escapeHtml(product.name)}</strong>
                  <span class="chip warn">${escapeHtml(String(product.inProduction))} шт</span>
                </div>
                <div class="meta">Остаток ${escapeHtml(String(product.stock))} · Резерв ${escapeHtml(String(product.reserve))}</div>
              </div>
            `).join('')}
          </div>
        </section>
      </aside>
    </div>
  `;
}

function renderKnowledge() {
  const roleFilter = state.ui.filters.knowledgeRole;
  const items = state.knowledge.filter((item) => roleFilter === 'all' || item.role === roleFilter);
  return `
    <div class="panel">
      <div class="row" style="justify-content: space-between;">
        <div>
          <h3 class="section-title">Обучение и база знаний</h3>
          <p class="section-desc">Инструкции, новости, скрипты и быстрый тест, который может заблокировать экран.</p>
        </div>
        <div class="row">
          <button class="btn primary" data-action="open-quick-test">Запустить тест</button>
        </div>
      </div>
      <div class="searchbar">
        <select data-input="knowledge-role">
          <option value="all" ${roleFilter === 'all' ? 'selected' : ''}>Все роли</option>
          <option value="front" ${roleFilter === 'front' ? 'selected' : ''}>Фронт</option>
          <option value="back" ${roleFilter === 'back' ? 'selected' : ''}>Бек</option>
          <option value="hybrid" ${roleFilter === 'hybrid' ? 'selected' : ''}>Гибрид</option>
          <option value="content" ${roleFilter === 'content' ? 'selected' : ''}>Контент</option>
          <option value="locomotive" ${roleFilter === 'locomotive' ? 'selected' : ''}>Локомотив</option>
          <option value="admin" ${roleFilter === 'admin' ? 'selected' : ''}>Админ</option>
        </select>
        <div class="ghost-box">Скриптов: ${state.scripts.length}</div>
        <div class="ghost-box">Новостей: ${state.news.length}</div>
      </div>
    </div>

    <div class="dashboard-grid">
      <section class="panel">
        <h3>Регламенты</h3>
        <div class="mini-list">
          ${items.map((item) => `
            <div class="mini-item">
              <div class="head">
                <strong class="title">${escapeHtml(item.title)}</strong>
                <span class="chip info">${escapeHtml(roleLabel(item.role))}</span>
              </div>
              <div class="meta">${escapeHtml(item.body)}</div>
            </div>
          `).join('')}
        </div>
      </section>
      <section class="panel">
        <h3>Новости</h3>
        <div class="mini-list">
          ${state.news.map((item) => `
            <div class="mini-item">
              <div class="head">
                <strong class="title">${escapeHtml(item.title)}</strong>
                <span class="chip warn">${escapeHtml(formatDateTime(item.at))}</span>
              </div>
              <div class="meta">${escapeHtml(item.body)}</div>
            </div>
          `).join('')}
        </div>
      </section>
      <section class="panel">
        <h3>Скрипты</h3>
        <div class="mini-list">
          ${state.scripts.map((item) => `
            <div class="mini-item">
              <div class="head">
                <strong class="title">${escapeHtml(item.title)}</strong>
                <span class="chip good">${escapeHtml(item.trigger)}</span>
              </div>
              <div class="meta">${escapeHtml(item.answerTemplate)}</div>
            </div>
          `).join('')}
        </div>
      </section>
    </div>
  `;
}

function renderAnalytics() {
  const revenueMax = Math.max(...state.analytics.revenueByDay.map((item) => item.value));
  const channelMax = Math.max(...state.analytics.channelStats.map((item) => item.value));
  const kpiMax = Math.max(...state.analytics.employeeKpi.map((item) => item.replies));
  const productMax = Math.max(...state.analytics.productTrend.map((item) => item.value));
  return `
    <div class="panel">
      <div class="row" style="justify-content: space-between;">
        <div>
          <h3 class="section-title">Панель аналитики</h3>
          <p class="section-desc">Динамика выручки, каналов, сотрудников и товарных остатков.</p>
        </div>
      </div>
    </div>
    <div class="dashboard-grid">
      <section class="panel">
        <h3>Выручка по дням</h3>
        <div class="bar-chart">
          ${state.analytics.revenueByDay.map((item) => `
            <div class="bar-row">
              <div>${escapeHtml(item.day)}</div>
              <div class="bar-track"><div class="bar-fill" style="width:${Math.round(item.value / revenueMax * 100)}%"></div></div>
              <div>${Math.round(item.value / 1000)}k</div>
            </div>
          `).join('')}
        </div>
      </section>
      <section class="panel">
        <h3>Каналы общения</h3>
        <div class="bar-chart">
          ${state.analytics.channelStats.map((item) => `
            <div class="bar-row">
              <div>${escapeHtml(item.label)}</div>
              <div class="bar-track"><div class="bar-fill" style="width:${Math.round(item.value / channelMax * 100)}%"></div></div>
              <div>${item.value}%</div>
            </div>
          `).join('')}
        </div>
      </section>
      <section class="panel">
        <h3>KPI сотрудников</h3>
        <div class="bar-chart">
          ${state.analytics.employeeKpi.map((item) => `
            <div class="bar-row">
              <div>${escapeHtml(item.name)}</div>
              <div class="bar-track"><div class="bar-fill" style="width:${Math.round(item.replies / kpiMax * 100)}%"></div></div>
              <div>${item.replies}</div>
            </div>
          `).join('')}
        </div>
      </section>
      <section class="panel">
        <h3>Динамика остатков</h3>
        <div class="bar-chart">
          ${state.analytics.productTrend.map((item) => `
            <div class="bar-row">
              <div>${escapeHtml(item.label)}</div>
              <div class="bar-track"><div class="bar-fill" style="width:${Math.round(item.value / productMax * 100)}%"></div></div>
              <div>${item.value}</div>
            </div>
          `).join('')}
        </div>
      </section>
    </div>
  `;
}

function renderAdmin() {
  const blockedUsers = Object.entries(state.security.openEvents).map(([userId, timestamps]) => {
    const user = state.users.find((item) => item.id === userId);
    return { user, count: timestamps.length };
  }).filter(({ user }) => user);
  return `
    <div class="panel">
      <div class="row" style="justify-content: space-between;">
        <div>
          <h3 class="section-title">Панель администратора</h3>
          <p class="section-desc">Пользователи, словари, импорт CSV, экспорт базы и аудит действий.</p>
        </div>
        <div class="row">
          <button class="btn primary" data-action="export-json">Экспорт базы</button>
          <button class="btn" data-action="sync-1c">Обновить склад</button>
        </div>
      </div>
    </div>
    <div class="dashboard-grid">
      <section class="panel">
        <h3>Пользователи</h3>
        <div class="mini-list">
          ${state.users.map((user) => `
            <div class="mini-item">
              <div class="head">
                <strong class="title">${escapeHtml(user.name)}</strong>
                <span class="chip ${user.active ? 'good' : 'danger'}">${escapeHtml(roleLabel(user.role))}</span>
              </div>
              <div class="meta">${escapeHtml(user.login)} · ${escapeHtml(user.email)} · ${escapeHtml(user.schedule)}</div>
              <div class="row">
                <button class="btn" data-action="toggle-user" data-user-id="${escapeHtml(user.id)}">${user.active ? 'Деактивировать' : 'Активировать'}</button>
              </div>
            </div>
          `).join('')}
        </div>
      </section>
      <section class="panel">
        <h3>Словари</h3>
        <div class="stack">
          <div class="ghost-box">
            <strong>Статусы</strong>
            <div class="pill-row">${state.dictionaries.statuses.map((item) => `<span class="chip info">${escapeHtml(item)}</span>`).join('')}</div>
          </div>
          <div class="ghost-box">
            <strong>Теги</strong>
            <div class="pill-row">${state.dictionaries.tags.map((item) => `<span class="chip warn">${escapeHtml(item)}</span>`).join('')}</div>
          </div>
          <div class="ghost-box">
            <strong>Источники</strong>
            <div class="pill-row">${state.dictionaries.sources.map((item) => `<span class="chip good">${escapeHtml(item)}</span>`).join('')}</div>
          </div>
        </div>
      </section>
      <section class="panel">
        <h3>Импорт CSV</h3>
        <form class="form-grid" data-form="admin-import">
          <div class="field">
            <label>Пользователи</label>
            <textarea name="csv">${escapeHtml(state.ui.adminImportDraft)}</textarea>
          </div>
          <button class="btn primary" type="submit">Импортировать</button>
        </form>
      </section>
    </div>

    <div class="dashboard-grid">
      <section class="panel">
        <h3>Антифрод и блокировки</h3>
        <div class="mini-list">
          ${blockedUsers.length ? blockedUsers.map(({ user, count }) => `
            <div class="mini-item">
              <div class="head">
                <strong class="title">${escapeHtml(user.name)}</strong>
                <span class="chip danger">${count} просмотров</span>
              </div>
              <div class="meta">Логин ${escapeHtml(user.login)} · ${escapeHtml(user.email)}</div>
            </div>
          `).join('') : '<div class="empty-state">Пока нет заблокированных сотрудников.</div>'}
        </div>
      </section>
      <section class="panel">
        <h3>Аудит действий</h3>
        <div class="mini-list">
          ${state.audit.slice(0, 10).map((entry) => `
            <div class="mini-item">
              <div class="head">
                <strong class="title">${escapeHtml(entry.action)}</strong>
                <span class="chip info">${escapeHtml(formatDateTime(entry.at))}</span>
              </div>
              <div class="meta">${escapeHtml(entry.actor)} · ${escapeHtml(entry.ip)}</div>
            </div>
          `).join('')}
        </div>
      </section>
    </div>
  `;
}

function renderView() {
  switch (state.ui.view) {
    case 'inbox':
      return renderInbox();
    case 'clients':
      return renderClients();
    case 'tasks':
      return renderTasks();
    case 'products':
      return renderProducts();
    case 'knowledge':
      return renderKnowledge();
    case 'analytics':
      return renderAnalytics();
    case 'admin':
      return renderAdmin();
    case 'dashboard':
    default:
      return renderDashboard();
  }
}

function render() {
  if (!currentUser()) {
    renderLogin();
    return;
  }
  if (state.security.blocked && currentRole() !== 'admin') {
    state.ui.view = 'dashboard';
  }
  renderShell(renderView());
  wireAutoFocus();
}

function wireAutoFocus() {
  const auto = root.querySelector('[autofocus]');
  if (auto) auto.focus();
}

function handleClick(event) {
  const control = event.target.closest('[data-action]');
  if (!control) return;
  const action = control.dataset.action;
  const clientId = control.dataset.clientId;
  const taskId = control.dataset.taskId;
  const userId = control.dataset.userId;
  const view = control.dataset.view;
  const targetId = control.dataset.targetId;
  const sourceId = control.dataset.sourceId;
  const channel = control.dataset.channel;
  const text = control.dataset.text;

  switch (action) {
    case 'send-code':
      sendCode();
      break;
    case 'nav':
      selectView(view);
      break;
    case 'logout':
      logout();
      break;
    case 'quick-test':
    case 'open-quick-test':
      openQuickTest();
      break;
    case 'close-quick-test':
      state.ui.quickTest = null;
      persistState();
      scheduleRender();
      break;
    case 'select-client':
    case 'select-client-row':
    case 'open-client':
      if (clientId) openClientCard(clientId);
      break;
    case 'open-message-client':
      if (clientId) openClientCard(clientId);
      break;
    case 'open-write':
      if (clientId) {
        state.ui.selectedClientId = clientId;
        state.ui.composer.channel = channel || currentClient()?.preferredChannel || 'Telegram';
        state.ui.composer.text = text || '';
        state.ui.view = 'inbox';
        persistState();
        scheduleRender();
      }
      break;
    case 'reply-template':
      state.ui.view = 'inbox';
      state.ui.selectedClientId = clientId || state.ui.selectedClientId;
      state.ui.composer.channel = channel || 'Telegram';
      state.ui.composer.text = text || '';
      persistState();
      scheduleRender();
      break;
    case 'merge-with-duplicate':
      if (targetId && sourceId) mergeClients(targetId, sourceId);
      break;
    case 'open-task':
    case 'select-task':
      if (taskId) {
        selectTask(taskId);
        state.ui.view = 'tasks';
      }
      break;
    case 'task-done':
      if (taskId) updateTask(taskId, { status: 'done' });
      break;
    case 'task-progress':
      if (taskId) updateTask(taskId, { status: 'in_progress' });
      break;
    case 'create-task-template':
      toast('Создайте тикет', 'Форма уже доступна в правой колонке.', 'info');
      break;
    case 'sync-1c':
      import1C();
      break;
    case 'bank-import':
    case 'sync-from-bank':
      bankImport();
      break;
    case 'seed-task':
      state.ui.view = 'tasks';
      persistState();
      scheduleRender();
      break;
    case 'simulate-incoming': {
      const client = state.clients[Math.floor(Math.random() * state.clients.length)];
      const channel = state.channels[Math.floor(Math.random() * state.channels.length)];
      mutate('Incoming message', `${client.name} / ${channel}`, () => {
        state.messages.unshift({
          id: crypto.randomUUID(),
          channel,
          direction: 'in',
          contact: client.phone || client.email || 'unknown',
          clientId: client.id,
          author: client.name,
          text: `Авто-входящее сообщение от ${client.name}`,
          createdAt: nowIso(),
          unread: true,
          assignedTo: currentUser()?.id || null,
        });
        client.history.unshift({ type: 'message', text: `Входящее через ${channel}`, at: nowIso() });
        client.updatedAt = nowIso();
      });
      break;
    }
    case 'create-message-from-selection':
      state.ui.view = 'inbox';
      persistState();
      scheduleRender();
      break;
    case 'open-client':
      if (clientId) openClientCard(clientId);
      break;
    case 'add-sample-client': {
      const samplePhone = `+7999000${Math.floor(100 + Math.random() * 900)}`;
      const existing = findClientByPhone(samplePhone);
      if (!existing) {
        mutate('Create lead', samplePhone, () => {
          state.clients.unshift({
            id: crypto.randomUUID(),
            name: 'Новый лид',
            phone: samplePhone,
            email: '',
            oneCId: '',
            source: 'Telegram',
            preferredChannel: 'Telegram',
            statusHint: 'Лид',
            tags: ['новый'],
            interests: ['Комнатные растения'],
            discountCards: [],
            wishList: ['Фикус Лирата'],
            waitList: ['Фикус Лирата'],
            notesInternal: 'Создан быстро для обработки.',
            quality: 'B',
            blacklist: false,
            greenList: false,
            history: [{ type: 'message', text: 'Карточка создана быстрым действием', at: nowIso() }],
            purchases: [],
            bankPurchases: [],
            channelHistory: ['Telegram'],
            createdAt: nowIso(),
            updatedAt: nowIso(),
          });
          state.ui.selectedClientId = state.clients[0].id;
        });
      }
      break;
    }
    case 'export-json':
      exportData();
      break;
    case 'toggle-user':
      if (userId) {
        mutate('Toggle user', userId, () => {
          const user = state.users.find((item) => item.id === userId);
          if (user) user.active = !user.active;
        });
      }
      break;
    case 'admin-unblock':
      state.security.blocked = false;
      state.security.blockReason = '';
      persistState();
      scheduleRender();
      toast('Блок снят', 'Антифрод отключен вручную администратором.', 'good');
      break;
    default:
      break;
  }
}

function handleInput(event) {
  const target = event.target;
  if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement || target instanceof HTMLTextAreaElement)) return;
  const name = target.dataset.input;
  if (!name) return;
  const value = target.value;
  switch (name) {
    case 'client-query':
      state.ui.filters.clientQuery = value;
      break;
    case 'client-status':
      state.ui.filters.clientStatus = value;
      break;
    case 'client-channel':
      state.ui.filters.clientChannel = value;
      break;
    case 'inbox-search':
      state.ui.filters.messageQuery = value;
      break;
    case 'inbox-channel':
      state.ui.filters.inboxChannel = value;
      break;
    case 'task-query':
      state.ui.filters.taskQuery = value;
      break;
    case 'task-filter':
      state.ui.filters.taskFilter = value;
      break;
    case 'product-query':
      state.ui.filters.productQuery = value;
      break;
    case 'knowledge-role':
      state.ui.filters.knowledgeRole = value;
      break;
    default:
      break;
  }
  persistState();
  scheduleRender();
}

function handleSubmit(event) {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  const formType = form.dataset.form;
  if (!formType) return;
  event.preventDefault();
  const formData = new FormData(form);
  switch (formType) {
    case 'login':
      attemptLogin(formData);
      break;
    case 'quick-test':
      answerQuickTest(formData);
      break;
    case 'client':
      saveClient(formData);
      break;
    case 'task':
      createTask(formData);
      break;
    case 'reply':
      createMessage(formData);
      break;
    case 'admin-import':
      state.ui.adminImportDraft = String(formData.get('csv') || '');
      applyCsvImport(state.ui.adminImportDraft);
      persistState();
      scheduleRender();
      break;
    default:
      break;
  }
}

function heartbeat() {
  if (!currentUser()) return;
  const diff = (Date.now() - new Date(state.security.lastActivityAt).getTime()) / 60000;
  if (diff >= 300 && !state.security.blocked) {
    toast('Автовыход', 'Сеанс завершен после 5 часов бездействия.', 'warn');
    logout('Автовыход после бездействия');
  }
}

root.addEventListener('click', handleClick);
root.addEventListener('submit', handleSubmit);
root.addEventListener('input', handleInput);
window.addEventListener('hashchange', () => {
  const hash = location.hash.replace('#', '');
  if (hash && canAccess(hash)) {
    state.ui.view = hash;
    persistState();
    scheduleRender();
  }
});

setInterval(() => {
  heartbeat();
  if (currentUser()) {
    const elapsed = (Date.now() - new Date(state.security.lastActivityAt).getTime()) / 60000;
    if (elapsed > 1) {
      state.security.inactivityMinutes = Math.floor(elapsed);
      persistState();
    }
  }
}, 30000);

document.addEventListener('visibilitychange', () => {
  if (!document.hidden) {
    state.security.lastActivityAt = nowIso();
    persistState();
  }
});

if (!location.hash || location.hash === '#') {
  location.hash = state.ui.view;
} else {
  const hash = location.hash.replace('#', '');
  if (hash && canAccess(hash)) state.ui.view = hash;
}

if (currentUser()) {
  if (!canAccess(state.ui.view)) state.ui.view = 'dashboard';
}

render();
