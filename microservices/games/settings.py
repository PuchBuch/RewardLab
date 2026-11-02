"""Настройки игр. Все числа на странице «How it works» берутся отсюда (через GET /info)."""

# ─── Ежечасная награда: «счастливое число» ────────────────────
CLAIM_COOLDOWN   = 3600    # секунд между бросками
MAX_STREAK_BONUS = 10      # максимум бонуса за серию дней (добавляется к выигрышу)
LUCKY_MAX        = 10000   # выпадает число от 0 до LUCKY_MAX включительно
LUCKY_TIERS = [            # (до какого числа включительно, награда)
    (9885,  10),
    (9985,  50),
    (9993,  250),
    (9997,  1000),
    (9999,  5000),
    (10000, 25000),        # джекпот
]

# ─── Викторина ────────────────────────────────────────────────
QUIZ_REWARD = 20
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

# ─── Блэкджек на виртуальные баллы ────────────────────────────
BJ_CHIPS = [5, 10, 25, 50, 100]  # доступные ставки
BJ_DECKS = 6                     # колод в шузе (новый шуз на каждую раздачу)
