"""Настройки игровой механики. Все числа на странице «How it works» берутся отсюда."""

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # корень проекта
DATABASE = os.path.join(BASE_DIR, "rewards.db")

# ─── Ежечасная награда ────────────────────────────────────────
CLAIM_COOLDOWN   = 3600    # секунд между наградами
BASE_REWARD      = 10      # базовая награда
MAX_STREAK_BONUS = 10      # максимум бонуса за серию дней
RANDOM_BONUS     = 5       # случайная добавка 0..N
QUIZ_REWARD      = 20

# ─── Реферальная программа ────────────────────────────────────
# Пригласивший получает долю от всего, что зарабатывает друг
# (сверху, награда друга не уменьшается). Доля растёт с числом активных друзей.
REF_TIERS = [            # (минимум активных друзей, доля, название)
    (0,  0.10, "Bronze"),
    (3,  0.15, "Silver"),
    (10, 0.20, "Gold"),
]
REF_ACTIVATION_CLAIMS = 3    # после стольких наград друг считается активным
REF_BONUS_INVITER     = 50   # разовый бонус пригласившему за активного друга
REF_BONUS_FRIEND      = 25   # разовый приветственный бонус самому другу

# ─── Еженедельный конкурс (понедельник 00:00 – воскресенье 23:59 UTC) ──
CONTEST_PRIZES = [100, 50, 25]   # призы за 1, 2 и 3 место

# ─── Защита от накрутки ───────────────────────────────────────
REG_PER_NETWORK_DAY = 3          # максимум новых аккаунтов с одного IP за 24 часа

# ─── Блэкджек на виртуальные баллы ────────────────────────────
BJ_CHIPS = [5, 10, 25, 50, 100]  # доступные ставки
BJ_DECKS = 6                     # колод в шузе (новый шуз на каждую раздачу)

# ─── Админ-панель ─────────────────────────────────────────────
ADMIN_SESSION_TTL = 15 * 60      # секунд без активности до повторного входа

# ─── Вопросы викторины ────────────────────────────────────────
QUIZ = [
    {"q": "What does “Wasser” mean?", "options": ["water", "bread", "milk", "coffee"], "answer": 0},
    {"q": "Which article goes with “Fenster”?", "options": ["der", "die", "das"], "answer": 2},
    {"q": "Translate: “Ich lerne Deutsch.”", "options": ["I am learning German.", "I speak English.", "I work in Berlin.", "I like tea."], "answer": 0},
    {"q": "What does “Danke” mean?", "options": ["please", "thank you", "sorry", "goodbye"], "answer": 1},
    {"q": "Which article goes with “Stadt”?", "options": ["der", "die", "das"], "answer": 1},
    {"q": "What does “Bahnhof” mean?", "options": ["airport", "bakery", "train station", "hospital"], "answer": 2},
    {"q": "How do you say “good morning”?", "options": ["Gute Nacht", "Guten Morgen", "Guten Abend", "Auf Wiedersehen"], "answer": 1},
    {"q": "Which article goes with “Haus”?", "options": ["der", "die", "das"], "answer": 2},
]
