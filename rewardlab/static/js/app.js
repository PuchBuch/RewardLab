// Тема: светлая / тёмная. Выбор хранится в localStorage, без выбора — как в системе.
(function () {
  const root = document.documentElement;
  const meta = document.querySelector('meta[name="theme-color"]');
  const media = matchMedia('(prefers-color-scheme: dark)');
  const isDark = () => (root.dataset.theme ? root.dataset.theme === 'dark' : media.matches);
  const syncMeta = () => { if (meta) meta.content = getComputedStyle(root).getPropertyValue('--bg').trim(); };

  document.querySelectorAll('[data-theme-toggle]').forEach((btn) => btn.addEventListener('click', () => {
    const next = isDark() ? 'light' : 'dark';
    root.dataset.theme = next;
    try { localStorage.setItem('theme', next); } catch (e) { /* приватный режим */ }
    syncMeta();
  }));
  media.addEventListener('change', syncMeta);
  syncMeta();
})();

// Таймер до следующего бонуса (Dashboard)
(function () {
  const timer = document.getElementById('timer');
  if (!timer) return;
  const btn = document.getElementById('claim');
  const label = document.getElementById('label');
  let left = parseInt(timer.dataset.wait, 10) || 0;
  (function tick() {
    if (left <= 0) {
      btn.disabled = false;
      label.textContent = 'Your bonus is';
      timer.textContent = 'Ready';
      timer.classList.add('ready');
      return;
    }
    const m = Math.floor(left / 60), s = left % 60;
    timer.textContent = String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
    left--;
    setTimeout(tick, 1000);
  })();
})();

// Копирование ссылки-приглашения
document.querySelectorAll('[data-copy]').forEach((btn) => btn.addEventListener('click', async () => {
  const field = document.getElementById(btn.dataset.copy);
  try { await navigator.clipboard.writeText(field.value); } catch (e) { field.select(); document.execCommand('copy'); }
  const text = btn.textContent;
  btn.textContent = 'Copied!';
  setTimeout(() => { btn.textContent = text; }, 1500);
}));
