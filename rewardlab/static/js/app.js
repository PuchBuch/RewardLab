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

// Капча: новая картинка (и новый код на сервере) по запросу
const captchaImg = document.getElementById('captcha');
function loadCaptcha() {
  if (captchaImg) captchaImg.src = captchaImg.dataset.src + '?' + Date.now();
}
document.querySelectorAll('[data-captcha-refresh]').forEach((btn) => btn.addEventListener('click', loadCaptcha));

// Таймер до следующего броска (Dashboard). Когда время вышло — показать капчу и кнопку
(function () {
  const timer = document.getElementById('timer');
  if (!timer) return;
  const btn = document.getElementById('claim');
  const label = document.getElementById('label');
  const box = document.getElementById('captcha-box');
  let left = parseInt(timer.dataset.wait, 10) || 0;
  (function tick() {
    if (left <= 0) {
      btn.disabled = false;
      label.textContent = 'Your roll is';
      timer.textContent = 'Ready';
      timer.classList.add('ready');
      if (box) { box.hidden = false; loadCaptcha(); }
      return;
    }
    const m = Math.floor(left / 60), s = left % 60;
    timer.textContent = String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
    left--;
    setTimeout(tick, 1000);
  })();
})();

// Анимация «барабана»: цифры крутятся и по очереди останавливаются на выпавшем числе
document.querySelectorAll('[data-roll]').forEach((el) => {
  const target = String(el.dataset.roll).padStart(5, '0');
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) { el.textContent = target; return; }
  const started = performance.now();
  (function spin(now) {
    const settled = Math.floor((now - started) / 260);          // сколько цифр уже остановилось
    el.textContent = [...target].map((d, i) => (i < settled ? d : Math.floor(Math.random() * 10))).join('');
    if (settled < target.length) requestAnimationFrame(spin);
    else el.classList.add('done');
  })(started);
});

// Блэкджек: после отправки хода страница перезагружается — вернуть стол на то же место экрана
(function () {
  const table = document.querySelector('.bj-table');
  if (!table) return;
  try {
    const top = sessionStorage.getItem('bjTop');
    sessionStorage.removeItem('bjTop');
    if (top !== null) window.scrollTo(0, window.scrollY + table.getBoundingClientRect().top - Number(top));
  } catch (e) { /* приватный режим */ }
  table.querySelectorAll('form').forEach((form) => form.addEventListener('submit', () => {
    try { sessionStorage.setItem('bjTop', table.getBoundingClientRect().top); } catch (e) { /* приватный режим */ }
  }));
})();

// Копирование ссылки-приглашения
document.querySelectorAll('[data-copy]').forEach((btn) => btn.addEventListener('click', async () => {
  const field = document.getElementById(btn.dataset.copy);
  try { await navigator.clipboard.writeText(field.value); } catch (e) { field.select(); document.execCommand('copy'); }
  const text = btn.textContent;
  btn.textContent = 'Copied!';
  setTimeout(() => { btn.textContent = text; }, 1500);
}));
