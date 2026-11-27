"""Слой базы данных SQLite для платформы «Слово».

Все функции работают внутри контекста приложения Flask.
"""

import os
import sqlite3

from flask import current_app, g


SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    bio           TEXT    NOT NULL DEFAULT '',
    avatar        TEXT    NOT NULL DEFAULT '✍️',
    balance       INTEGER NOT NULL DEFAULT 1000,
    total_earned  INTEGER NOT NULL DEFAULT 0,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS articles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title        TEXT    NOT NULL,
    slug         TEXT    NOT NULL UNIQUE,
    excerpt      TEXT    NOT NULL DEFAULT '',
    content      TEXT    NOT NULL DEFAULT '',
    cover        TEXT    NOT NULL DEFAULT '1',
    category     TEXT    NOT NULL DEFAULT 'Разное',
    tags         TEXT    NOT NULL DEFAULT '',
    status       TEXT    NOT NULL DEFAULT 'draft',
    meta_title   TEXT    NOT NULL DEFAULT '',
    meta_description TEXT NOT NULL DEFAULT '',
    focus_keyword TEXT   NOT NULL DEFAULT '',
    views        INTEGER NOT NULL DEFAULT 0,
    likes        INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL,
    published_at TEXT
);

CREATE TABLE IF NOT EXISTS views (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    viewer_key TEXT    NOT NULL,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    day        TEXT    NOT NULL,
    source     TEXT    NOT NULL DEFAULT 'direct',
    created_at TEXT    NOT NULL,
    UNIQUE(article_id, viewer_key, day)
);

CREATE TABLE IF NOT EXISTS likes (
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    viewer_key TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    PRIMARY KEY (article_id, viewer_key)
);

CREATE TABLE IF NOT EXISTS bookmarks (
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT    NOT NULL,
    PRIMARY KEY (article_id, user_id)
);

CREATE TABLE IF NOT EXISTS comments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content    TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS follows (
    follower_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    author_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT    NOT NULL,
    PRIMARY KEY (follower_id, author_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type           TEXT    NOT NULL,
    amount         INTEGER NOT NULL,
    counterparty_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    article_id     INTEGER REFERENCES articles(id) ON DELETE SET NULL,
    description    TEXT    NOT NULL DEFAULT '',
    created_at     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_rewards (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day     TEXT    NOT NULL,
    amount  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);

CREATE TABLE IF NOT EXISTS payouts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount       INTEGER NOT NULL,
    method       TEXT    NOT NULL DEFAULT 'Карта •••• 4242',
    status       TEXT    NOT NULL DEFAULT 'pending',
    created_at   TEXT    NOT NULL,
    processed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_articles_user   ON articles(user_id);
CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
CREATE INDEX IF NOT EXISTS idx_views_article   ON views(article_id);
CREATE INDEX IF NOT EXISTS idx_views_day       ON views(day);
CREATE INDEX IF NOT EXISTS idx_comments_art    ON comments(article_id);
"""


def get_db():
    """Возвращает соединение с БД для текущего запроса."""
    if "db" not in g:
        path = current_app.config["DATABASE"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        g.db = sqlite3.connect(path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Создаёт структуру БД и демо-данные при первом запуске."""
    path = current_app.config["DATABASE"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)

    # совместимость с уже существующей базой
    for table, additions in (
        ("articles", (
            ("meta_title", "TEXT NOT NULL DEFAULT ''"),
            ("meta_description", "TEXT NOT NULL DEFAULT ''"),
            ("focus_keyword", "TEXT NOT NULL DEFAULT ''"),
        )),
        ("users", (
            ("balance", "INTEGER NOT NULL DEFAULT 1000"),
            ("total_earned", "INTEGER NOT NULL DEFAULT 0"),
            ("is_admin", "INTEGER NOT NULL DEFAULT 0"),
        )),
        ("views", (
            ("user_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL"),
        )),
    ):
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        for name, declaration in additions:
            if name not in columns:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
    db.commit()

    # обновляем уже существующего демо-пользователя до админа с кошельком
    demo = db.execute(
        "SELECT id,is_admin FROM users WHERE email='demo@slovo.ru'"
    ).fetchone()
    if demo and not demo[1]:
        db.execute(
            "UPDATE users SET is_admin=1,balance=2700,total_earned=2200 WHERE id=?",
            (demo[0],),
        )
        if not db.execute(
            "SELECT 1 FROM transactions WHERE user_id=? LIMIT 1", (demo[0],)
        ).fetchone():
            _seed_wallet(db, demo[0])
        db.commit()

    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed_demo(db)

    db.close()


def seed_demo(db):
    """Наполняем сайт примерами, чтобы интерфейс сразу выглядел живым."""
    from datetime import datetime, timedelta, timezone

    from werkzeug.security import generate_password_hash

    def stamp(days_ago=0):
        return (
            datetime.now(timezone.utc) - timedelta(days=days_ago)
        ).strftime("%Y-%m-%d %H:%M:%S")

    db.execute(
        "INSERT INTO users (username,email,password_hash,bio,avatar,balance,total_earned,is_admin,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "Анна Ветрова",
            "demo@slovo.ru",
            generate_password_hash("demo123"),
            "Пишу о дизайне, технологиях и о том, как устроена наша жизнь. Автор блога «Слово».",
            "✍️",
            2700,
            2200,
            1,
            stamp(90),
        ),
    )
    uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    demo_articles = [
        {
            "title": "Как писать так, чтобы читали до конца",
            "slug": "kak-pisat-chtoby-chitali-do-konca",
            "excerpt": "Семь приёмов, которые превращают сухой текст в историю, которую невозможно оторваться.",
            "content": """# Как писать так, чтобы читали до конца

Хороший текст — это не вдохновение, а ремесло. Вот приёмы, которые работают в любом жанре.

## Начинайте с конфликта

Первый абзац решает всё. Не объясняйте, о чём статья — сразу покажите проблему:

> «Я написал 300 статей, и никто их не читал. Пока не понял одну простую вещь».

## Пишите как говорите

Представьте, что рассказываете другу за кофе. Короткие предложения, живые слова, никаких канцеляризмов.

- заменяйте «осуществить» на «сделать»;
- убирайте «в настоящее время» — сейчас уже всё понятно;
- оставляйте только те прилагательные, которые несут смысл.

### Рисуйте картинку словами

Вместо «однажды в лесу» напишите «под ногами хрустела остывшая хвоя».

## Добавляйте структуру

| Приём | Эффект |
| ----- | ------ |
| Подзаголовки | Глаза отдыхают |
| Списки | Информация усваивается |
| Цитаты | Текст дышит |

## Заканчивайте действием

Не ставьте точку на пустом месте. Оставьте читателю вопрос или шаг, который он сделает прямо сейчас.

**Главное правило:** пишите для одного конкретного человека. Остальные подтянутся сами.""",
            "cover": "3",
            "category": "Письмо",
            "tags": "писательство, советы, тексты",
            "views": 2847,
            "likes": 196,
            "days": 1,
        },
        {
            "title": "Дизайн интерфейса: 10 деталей, которые решают всё",
            "slug": "dizajn-interfejsa-10-detail",
            "excerpt": "Микродетали, от которых зависит, останется ли пользователь на вашем сайте.",
            "content": """# Дизайн интерфейса: 10 деталей, которые решают всё

Пользователь не замечает хороший интерфейс — он просто делает то, что нужно. Разбираем детали, из которых складывается это ощущение.

## 1. Скорость важнее красоты

Сайт, который открывается за 3 секунды, теряет почти треть посетителей. Оптимизируйте картинки и скрипты в первую очередь.

## 2. Понятная иерархия

Один главный заголовок на экран. Второстепенное — тише, главное — крупнее.

## 3. Клик по всей строке

Никто не хочет попадать в крошечную галочку. Увеличьте область нажатия.

```css
.checkbox-label {
  padding: 12px;
  cursor: pointer;
}
```

## 4. Состояния загрузки

Пустой экран пугает. Скелетон или спиннер говорят: «мы работаем, подожди».

## 5. Честные ошибки

Вместо «Ошибка 500» напишите: «Не получилось сохранить. Попробуйте ещё раз через минуту».

---

Хороший интерфейс — это забота, выраженная в пикселях.""",
            "cover": "5",
            "category": "Дизайн",
            "tags": "ui, ux, интерфейсы",
            "views": 1923,
            "likes": 143,
            "days": 3,
        },
        {
            "title": "Утренний ритуал, который меняет продуктивность",
            "slug": "utrennij-ritual-produktivnost",
            "excerpt": "20 минут, которые дают больше, чем три часа хаотичной работы.",
            "content": """# Утренний ритуал, который меняет продуктивность

Я перепробовал десятки систем. Работает только та, которую не надо насильно заставлять себя делать.

## Правило первого часа

Первый час после пробуждения — самый ценный. Не отдавайте его почте и соцсетям.

1. Стакан воды.
2. 10 минут тишины.
3. Одна задача, которая сегодня важнее всех.

> Продуктивность — это не делать больше. Это делать важнее.

## Вечерняя подготовка

Запишите главную задачу вечером. Утром не придётся тратить силу воли на выбор.

Попробуйте завтра — и сравните ощущения через неделю.""",
            "cover": "2",
            "category": "Жизнь",
            "tags": "привычки, продуктивность",
            "views": 1204,
            "likes": 88,
            "days": 6,
        },
        {
            "title": "Черновик, который никто не увидит: как победить страх писать",
            "slug": "chernovik-i-strah-pisat",
            "excerpt": "Разрешите себе писать плохо — и впервые напишете хорошо.",
            "content": """# Черновик, который никто не увидит

Страх начать — главный враг любого автора. Лечится он просто: разрешите себе плохой черновик.

## Не редактируйте на ходу

Пишите вместе, редактируйте потом. Это два разных человека внутри вас.

## Ставьте таймер

25 минут, никаких остановок. Не нравится предложение — оставьте его, вернётесь позже.

## Показывайте раньше, чем готово

Один читатель на раннем этапе ценнее десяти на финале.

**Помните:** идеальный текст — враг опубликованного.""",
            "cover": "4",
            "category": "Письмо",
            "tags": "писательство, мотивация",
            "views": 876,
            "likes": 64,
            "days": 9,
        },
    ]

    for a in demo_articles:
        created = stamp(a["days"] + 2)
        published = stamp(a["days"])
        db.execute(
            "INSERT INTO articles (user_id,title,slug,excerpt,content,cover,category,tags,"
            "status,views,likes,created_at,updated_at,published_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                uid,
                a["title"],
                a["slug"],
                a["excerpt"],
                a["content"],
                a["cover"],
                a["category"],
                a["tags"],
                "published",
                a["views"],
                a["likes"],
                created,
                published,
                published,
            ),
        )
        aid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        # распределяем просмотры по последним дням для красивого графика
        for d in range(13, -1, -1):
            n = max(0, int(a["views"] / 30) + (d % 4) * 3 - (d // 5))
            if n:
                for _ in range(n):
                    db.execute(
                        "INSERT OR IGNORE INTO views (article_id,viewer_key,day,source,created_at) "
                        "VALUES (?,?,?,?,?)",
                        (
                            aid,
                            f"demo-{aid}-{d}-{_}",
                            (
                                datetime.now(timezone.utc)
                                - timedelta(days=d)
                            ).strftime("%Y-%m-%d"),
                            ["direct", "search", "social"][(aid + d) % 3],
                            published,
                        ),
                    )

    db.execute(
        "INSERT INTO comments (article_id,user_id,content,created_at) VALUES (?,?,?,?)",
        (
            1,
            uid,
            "Очень вовремя прочитала. Про «писать для одного человека» — именно то, что я забывала.",
            stamp(0),
        ),
    )

    _seed_wallet(db, uid)
    db.commit()


def _seed_wallet(db, uid):
    """Демо-история операций с кошельком (только тестовые кредиты)."""
    from datetime import datetime, timedelta, timezone

    def stamp(days):
        return (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%d %H:%M:%S")

    demo_ops = [
        ("topup", 1000, "Стартовые тестовые кредиты", 80),
        ("tip_in", 750, "Поддержка от читателя Марины", 40),
        ("view_reward", 950, "Начисление за просмотры статей", 12),
        ("tip_in", 500, "Поддержка от читателя Игоря", 5),
        ("payout", -500, "Выплата на карту •••• 4242", 2),
    ]
    for kind, amount, description, days in demo_ops:
        db.execute(
            "INSERT INTO transactions (user_id,type,amount,description,created_at) "
            "VALUES (?,?,?,?,?)",
            (uid, kind, amount, description, stamp(days)),
        )
    db.execute(
        "INSERT INTO payouts (user_id,amount,method,status,created_at,processed_at) "
        "VALUES (?,?,?,?,?,?)",
        (uid, 500, "Карта •••• 4242", "paid", stamp(2), stamp(1)),
    )
