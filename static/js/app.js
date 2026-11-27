/* «Слово» — клиентская логика */
(function () {
  'use strict';

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  /* ---------- Уведомления ---------- */
  function toast(message, type) {
    let stack = $('#flashStack');
    if (!stack) {
      stack = document.createElement('div');
      stack.id = 'flashStack';
      stack.className = 'flash-stack';
      document.body.appendChild(stack);
    }
    const el = document.createElement('div');
    el.className = 'flash flash-' + (type || 'success');
    const span = document.createElement('span');
    span.textContent = message;
    const close = document.createElement('button');
    close.className = 'flash-close';
    close.textContent = '×';
    close.addEventListener('click', () => el.remove());
    el.append(span, close);
    stack.appendChild(el);
    setTimeout(() => el.remove(), 5000);
  }

  $$('.flash-close').forEach((btn) => btn.addEventListener('click', () => btn.closest('.flash').remove()));
  $$('.flash').forEach((el) => setTimeout(() => el.remove(), 6000));

  /* ---------- Тема ---------- */
  const savedTheme = localStorage.getItem('slovo-theme');
  if (savedTheme) document.documentElement.dataset.theme = savedTheme;
  const themeToggle = $('#themeToggle');
  if (themeToggle) {
    themeToggle.addEventListener('click', () => {
      const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = next;
      localStorage.setItem('slovo-theme', next);
      renderAllCharts();
    });
  }

  /* ---------- Шапка ---------- */
  const userTrigger = $('#userTrigger');
  const userDropdown = $('#userDropdown');
  if (userTrigger && userDropdown) {
    userTrigger.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = userDropdown.classList.toggle('open');
      userTrigger.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('click', () => {
      userDropdown.classList.remove('open');
      userTrigger.setAttribute('aria-expanded', 'false');
    });
  }
  const menuToggle = $('#menuToggle');
  if (menuToggle) {
    menuToggle.addEventListener('click', () => $('#siteHeader').classList.toggle('nav-open'));
  }

  /* ---------- Прогресс чтения ---------- */
  const progress = $('#readingProgress');
  const articleBody = $('#articleBody');
  if (progress && articleBody) {
    const update = () => {
      const start = articleBody.getBoundingClientRect().top + window.scrollY;
      const total = Math.max(1, articleBody.offsetHeight - window.innerHeight / 2);
      const value = Math.min(1, Math.max(0, (window.scrollY - start + 120) / total));
      progress.style.width = (value * 100).toFixed(1) + '%';
    };
    window.addEventListener('scroll', update, { passive: true });
    update();
  }

  /* ---------- Графики ---------- */
  function drawChart(wrap, data) {
    if (!wrap || !data) return;
    const labels = data.labels || [];
    const values = (data.values || []).map(Number);
    if (!values.length) return;
    const W = 800, H = 260;
    const pad = { l: 42, r: 14, t: 18, b: 34 };
    const innerW = W - pad.l - pad.r;
    const innerH = H - pad.t - pad.b;
    const max = Math.max(...values, 1);
    const niceMax = Math.ceil(max / 5) * 5 || 5;
    const x = (i) => pad.l + (values.length === 1 ? innerW / 2 : (i / (values.length - 1)) * innerW);
    const y = (v) => pad.t + innerH - (v / niceMax) * innerH;

    let grid = '';
    for (let i = 0; i <= 4; i++) {
      const gy = pad.t + (innerH / 4) * i;
      const label = Math.round(niceMax - (niceMax / 4) * i);
      grid += `<line x1="${pad.l}" y1="${gy}" x2="${W - pad.r}" y2="${gy}" stroke="var(--border)" stroke-dasharray="3 5"/>`;
      grid += `<text x="${pad.l - 8}" y="${gy + 4}" text-anchor="end" fill="var(--muted)" font-size="10">${label}</text>`;
    }
    const step = Math.max(1, Math.ceil(labels.length / 8));
    let xlabels = '';
    labels.forEach((label, i) => {
      if (i % step === 0 || i === labels.length - 1) {
        xlabels += `<text x="${x(i)}" y="${H - 10}" text-anchor="middle" fill="var(--muted)" font-size="10">${label.slice(5)}</text>`;
      }
    });
    let line = '', area = '', dots = '';
    values.forEach((v, i) => {
      line += `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)} `;
    });
    area = `${line}L${x(values.length - 1).toFixed(1)},${pad.t + innerH} L${x(0).toFixed(1)},${pad.t + innerH} Z`;
    values.forEach((v, i) => {
      dots += `<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="3.5" fill="var(--surface)" stroke="var(--accent)" stroke-width="2"><title>${labels[i]}: ${v}</title></circle>`;
    });
    const uid = 'grad' + Math.random().toString(36).slice(2, 8);
    wrap.innerHTML =
      `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="График просмотров">` +
      `<defs><linearGradient id="${uid}" x1="0" y1="0" x2="0" y2="1">` +
      `<stop offset="0%" stop-color="var(--accent)" stop-opacity="0.28"/>` +
      `<stop offset="100%" stop-color="var(--accent)" stop-opacity="0.01"/></linearGradient></defs>` +
      grid + xlabels +
      `<path d="${area}" fill="url(#${uid})"/>` +
      `<path d="${line}" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>` +
      dots + '</svg>';
  }
  function renderAllCharts() {
    $$('.chart-wrap').forEach((wrap) => {
      try { drawChart(wrap, JSON.parse(wrap.dataset.chart || 'null')); } catch (e) { /* ignore */ }
    });
  }
  renderAllCharts();

  const periodSwitch = $('#periodSwitch');
  if (periodSwitch) {
    periodSwitch.addEventListener('click', async (e) => {
      const btn = e.target.closest('button[data-days]');
      if (!btn) return;
      $$('button', periodSwitch).forEach((b) => b.classList.toggle('active', b === btn));
      try {
        const res = await fetch('/api/stats?days=' + btn.dataset.days);
        const data = await res.json();
        drawChart($('.chart-wrap'), data);
      } catch (err) { toast('Не удалось загрузить статистику', 'error'); }
    });
  }

  /* ---------- Реакции ---------- */
  function postJSON(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
  }
  $$('[data-action]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const action = btn.dataset.action;
      const id = btn.dataset.id;
      if (action === 'share') {
        try {
          await navigator.clipboard.writeText(window.location.href);
          toast('Ссылка на статью скопирована');
        } catch (e) { toast('Скопируйте ссылку из адресной строки'); }
        return;
      }
      try {
        const res = await postJSON('/api/articles/' + id + '/' + action);
        if (res.status === 401) { toast('Войдите, чтобы продолжить', 'error'); return; }
        const data = await res.json();
        if (action === 'like') {
          btn.classList.toggle('active', data.liked);
          const count = $('#likeCount');
          if (count) count.textContent = data.count;
        } else if (action === 'bookmark') {
          btn.classList.toggle('active', data.saved);
          const label = btn.querySelector('span:last-child');
          if (label) label.textContent = data.saved ? 'Сохранено' : 'Сохранить';
          toast(data.saved ? 'Статья сохранена' : 'Удалено из сохранённого');
        }
      } catch (e) { toast('Ошибка сети', 'error'); }
    });
  });

  /* ---------- Подписки и поддержка автора ---------- */
  $$('[data-follow]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      try {
        const res = await postJSON('/api/authors/' + btn.dataset.follow + '/follow');
        const data = await res.json();
        if (data.error) { toast(data.error, 'error'); return; }
        btn.classList.toggle('btn-primary', data.following);
        btn.classList.toggle('btn-soft', !data.following);
        btn.innerHTML = (data.following ? '✓ Вы подписаны' : '+ Подписаться') +
          ' <span class="follow-count">(' + data.count + ')</span>';
        toast(data.following ? 'Вы подписались на автора' : 'Подписка отменена');
      } catch (e) { toast('Ошибка сети', 'error'); }
    });
  });

  $$('[data-tip]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const articleId = btn.dataset.article;
      const raw = btn.dataset.tip === 'custom' ? ($('#tipCustom') || {}).value : btn.dataset.tip;
      const amount = parseInt(raw, 10);
      if (!amount || amount < 10 || amount > 1000) {
        toast('Укажите сумму от 10 до 1000 кредитов', 'error');
        return;
      }
      if (!confirm('Отправить ' + amount + ' тестовых кредитов автору статьи?')) return;
      try {
        const res = await postJSON('/api/articles/' + articleId + '/tip', { amount });
        const data = await res.json();
        if (data.error) { toast(data.error, 'error'); return; }
        toast('Вы поддержали автора на ' + data.amount + ' кредитов');
        const wallet = $('.wallet-pill');
        if (wallet) wallet.textContent = '◈ ' + data.balance;
        if (btn.dataset.tip === 'custom') $('#tipCustom').value = '';
      } catch (e) { toast('Ошибка сети', 'error'); }
    });
  });

  /* ---------- Комментарии ---------- */
  const commentForm = $('#commentForm');
  if (commentForm) {
    commentForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const input = $('#commentText');
      const content = input.value.trim();
      if (!content) return;
      try {
        const res = await postJSON('/api/articles/' + commentForm.dataset.id + '/comments', { content });
        const data = await res.json();
        if (data.error) { toast(data.error, 'error'); return; }
        const list = $('#commentList');
        const empty = $('.no-comments', list);
        if (empty) empty.remove();
        const item = document.createElement('div');
        item.className = 'comment';
        const avatar = document.createElement('span');
        avatar.className = 'avatar avatar-md';
        avatar.textContent = data.avatar;
        const body = document.createElement('div');
        body.className = 'comment-body';
        const head = document.createElement('div');
        head.className = 'comment-head';
        const strong = document.createElement('strong');
        strong.textContent = data.username;
        const small = document.createElement('small');
        small.textContent = data.date;
        head.append(strong, small);
        const p = document.createElement('p');
        p.textContent = data.content;
        body.append(head, p);
        item.append(avatar, body);
        list.prepend(item);
        input.value = '';
        toast('Комментарий опубликован');
      } catch (err) { toast('Не удалось отправить комментарий', 'error'); }
    });
  }

  /* ---------- Профиль ---------- */
  const avatarPicker = $('#avatarPicker');
  if (avatarPicker) {
    avatarPicker.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-avatar]');
      if (!btn) return;
      $$('.avatar-option', avatarPicker).forEach((b) => b.classList.toggle('active', b === btn));
      $('#avatarInput').value = btn.dataset.avatar;
      const preview = $('#avatarPreview');
      if (preview) preview.textContent = btn.dataset.avatar;
    });
  }
  const namePreview = $('#namePreview');
  if (namePreview) {
    const bind = (inputId, targetId) => {
      const input = $('#' + inputId);
      if (input) input.addEventListener('input', () => { $('#' + targetId).textContent = input.value || '—'; });
    };
    bind('username', 'namePreview');
    bind('bio', 'bioPreview');
  }

  /* ---------- Список статей автора ---------- */
  const statusFilter = $('#statusFilter');
  if (statusFilter) {
    statusFilter.addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-filter]');
      if (!btn) return;
      $$('button', statusFilter).forEach((b) => b.classList.toggle('active', b === btn));
      const value = btn.dataset.filter;
      $$('#articlesTable tbody tr').forEach((row) => {
        row.hidden = value !== 'all' && row.dataset.status !== value;
      });
    });
  }
  $$('[data-delete]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (!confirm('Удалить статью? Это действие нельзя отменить.')) return;
      try {
        const res = await fetch('/api/articles/' + btn.dataset.delete, { method: 'DELETE' });
        if (res.ok) { toast('Статья удалена'); setTimeout(() => location.reload(), 500); }
        else toast('Не удалось удалить статью', 'error');
      } catch (e) { toast('Ошибка сети', 'error'); }
    });
  });

  /* ---------- Демо-доступ ---------- */
  const fillDemo = $('#fillDemo');
  if (fillDemo) {
    fillDemo.addEventListener('click', () => {
      $('[name="login"]').value = 'demo@slovo.ru';
      $('[name="password"]').value = 'demo123';
    });
  }

  /* ---------- Редактор ---------- */
  const editorPage = $('#editorPage');
  if (editorPage) {
    const f = {
      title: $('#articleTitle'), excerpt: $('#articleExcerpt'), content: $('#articleContent'),
      category: $('#articleCategory'), tags: $('#articleTags'), status: $('#articleStatus'),
      metaTitle: $('#metaTitle'), metaDescription: $('#metaDescription'), focusKeyword: $('#focusKeyword'),
    };
    let articleId = editorPage.dataset.id || '';
    const storageKey = articleId ? 'slovo-autosave-' + articleId : 'slovo-autosave-new';
    let cover = $('.cover-option.active')?.dataset.cover || '1';
    let dirty = false;
    let saving = false;

    const countWords = (text) => (text.match(/[\wа-яА-ЯёЁ]+/g) || []).length;

    function counters() {
      const words = countWords(f.content.value);
      $('#wordCount').textContent = words + ' слов';
      $('#readTime').textContent = '~' + Math.max(1, Math.round(words / 200)) + ' мин чтения';
    }

    function seoCheck() {
      const checks = {
        title: f.title.value.length >= 25 && f.title.value.length <= 60,
        desc: f.metaDescription.value.length >= 70 && f.metaDescription.value.length <= 155,
        keyword: !!f.focusKeyword.value.trim() && f.title.value.toLowerCase().includes(f.focusKeyword.value.trim().toLowerCase()),
        content: countWords(f.content.value) >= 300,
      };
      $$('#seoChecklist div').forEach((row) => {
        const key = row.dataset.check;
        row.classList.toggle('ok', !!checks[key]);
        row.textContent = (checks[key] ? '✓ ' : '○ ') + row.textContent.slice(1);
      });
      $('#seoTitleHint').textContent = f.title.value.length + ' / 60 символов';
      $('#seoDescHint').textContent = f.metaDescription.value.length + ' / 155 символов';
    }

    function payload(statusOverride) {
      return {
        title: f.title.value,
        excerpt: f.excerpt.value,
        content: f.content.value,
        category: f.category.value,
        tags: f.tags.value,
        cover: cover,
        status: statusOverride || f.status.value,
        meta_title: f.metaTitle.value,
        meta_description: f.metaDescription.value,
        focus_keyword: f.focusKeyword.value,
      };
    }

    function localBackup() {
      try { localStorage.setItem(storageKey, JSON.stringify(payload())); } catch (e) { /* ignore */ }
    }
    function restoreBackup() {
      try {
        const saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
        if (!saved) return;
        if (!f.title.value && saved.title) f.title.value = saved.title;
        if (!f.content.value && saved.content) f.content.value = saved.content;
        if (!f.excerpt.value && saved.excerpt) f.excerpt.value = saved.excerpt;
        toast('Восстановлен черновик из браузера');
      } catch (e) { /* ignore */ }
    }

    function markDirty() {
      dirty = true;
      $('#saveHint').textContent = 'Есть несохранённые изменения';
      counters();
      seoCheck();
      localBackup();
    }

    Object.values(f).forEach((el) => { if (el) el.addEventListener('input', markDirty); });

    $('#coverPicker')?.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-cover]');
      if (!btn) return;
      $$('.cover-option').forEach((b) => b.classList.toggle('active', b === btn));
      cover = btn.dataset.cover;
      markDirty();
    });

    async function save(statusOverride, quiet) {
      if (!f.title.value.trim()) { toast('Введите заголовок статьи', 'error'); return false; }
      if (saving) return false;
      saving = true;
      $('#saveHint').textContent = 'Сохранение…';
      try {
        const url = articleId ? '/api/articles/' + articleId : '/api/articles';
        const res = await fetch(url, {
          method: articleId ? 'POST' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload(statusOverride)),
        });
        const data = await res.json();
        if (!res.ok) { toast(data.error || 'Ошибка сохранения', 'error'); return false; }
        if (!articleId) {
          articleId = String(data.id);
          editorPage.dataset.id = articleId;
          history.replaceState(null, '', '/editor/' + articleId);
        }
        if (statusOverride === 'published' && data.status === 'published') {
          f.status.value = 'published';
        }
        dirty = false;
        $('#saveHint').textContent = 'Все изменения сохранены';
        localStorage.removeItem(storageKey);
        if (!quiet) toast(statusOverride === 'published' ? 'Статья опубликована' : 'Изменения сохранены');
        return true;
      } catch (e) { toast('Ошибка сети', 'error'); return false; }
      finally { saving = false; }
    }

    $('#saveDraft')?.addEventListener('click', () => save(f.status.value));
    $('#publishBtn')?.addEventListener('click', async () => {
      if (await save('published')) {
        setTimeout(() => { window.location.href = '/dashboard'; }, 700);
      }
    });

    // автосохранение на сервере каждые 20 секунд
    setInterval(() => { if (dirty && !saving) save(f.status.value, true); }, 20000);
    window.addEventListener('beforeunload', (e) => {
      if (dirty) { e.preventDefault(); e.returnValue = ''; }
    });

    // панель форматирования
    const wrappers = {
      bold: ['**', '**'], italic: ['*', '*'],
      h2: ['\n## ', '\n'], h3: ['\n### ', '\n'],
      ul: ['\n- ', '\n'], quote: ['\n> ', '\n'],
      code: ['\n```\n', '\n```\n'], link: ['[', '](https://example.com)'],
    };
    $('#editorToolbar')?.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-md]');
      if (!btn) return;
      const pair = wrappers[btn.dataset.md];
      if (!pair) return;
      const ta = f.content;
      const start = ta.selectionStart, end = ta.selectionEnd;
      const selected = ta.value.slice(start, end) || 'текст';
      ta.value = ta.value.slice(0, start) + pair[0] + selected + pair[1] + ta.value.slice(end);
      ta.focus();
      ta.selectionStart = start + pair[0].length;
      ta.selectionEnd = start + pair[0].length + selected.length;
      markDirty();
    });

    // предпросмотр
    const previewToggle = $('#previewToggle');
    const previewPane = $('#previewPane');
    let previewOn = false;
    if (previewToggle) {
      previewToggle.addEventListener('click', async () => {
        if (previewOn) {
          previewPane.hidden = true;
          f.content.hidden = false;
          previewToggle.textContent = '👁 Предпросмотр';
          previewOn = false;
        } else {
          try {
            const res = await postJSON('/api/preview', { content: f.content.value });
            const data = await res.json();
            previewPane.innerHTML = data.html || '<p>Пока нечего показывать.</p>';
            f.content.hidden = true;
            previewPane.hidden = false;
            previewToggle.textContent = '✏️ Редактор';
            previewOn = true;
          } catch (e) { toast('Не удалось построить предпросмотр', 'error'); }
        }
      });
    }

    counters();
    seoCheck();
    if (!f.title.value) restoreBackup();
    f.status.addEventListener('change', () => {
      $('#saveHint').textContent = f.status.value === 'published' ? 'При сохранении станет виден всем' : 'Статья останется черновиком';
    });
  }
})();
