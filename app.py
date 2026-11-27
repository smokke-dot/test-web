"""«Слово» — платформа для авторов статей.

Запуск:  python app.py
Демо-доступ: demo@slovo.ru / demo123
"""

import hashlib
import html
import json
import math
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from email.utils import format_datetime
from xml.sax.saxutils import escape as xml_escape

from flask import (
    Flask, Response, abort, flash, g, jsonify, redirect, render_template,
    request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from db import close_db, get_db, init_db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SECRET_FILE = os.path.join(BASE_DIR, ".secret_key")

if os.path.exists(SECRET_FILE):
    with open(SECRET_FILE, "r", encoding="utf-8") as fh:
        SECRET = fh.read().strip()
else:
    SECRET = secrets.token_hex(32)
    with open(SECRET_FILE, "w", encoding="utf-8") as fh:
        fh.write(SECRET)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET,
    DATABASE=os.path.join(app.instance_path, "site.db"),
    MAX_CONTENT_LENGTH=4 * 1024 * 1024,
)
os.makedirs(app.instance_path, exist_ok=True)
app.teardown_appcontext(close_db)


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def viewer_key():
    raw = (request.remote_addr or "") + "|" + request.headers.get("User-Agent", "")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def detect_source():
    ref = (request.referrer or "").lower()
    if any(x in ref for x in ("google.", "yandex.", "bing.", "mail.ru", "duckduckgo")):
        return "search"
    if any(x in ref for x in ("vk.com", "facebook", "instagram", "telegram", "t.me")):
        return "social"
    return "direct"


TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slugify(text):
    text = text.lower().strip()
    text = "".join(TRANSLIT.get(ch, ch) for ch in text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:64] or "article"


def unique_slug(db, title, exclude_id=None):
    base = slugify(title)
    slug = base
    n = 2
    while True:
        query = "SELECT id FROM articles WHERE slug=?"
        params = [slug]
        if exclude_id:
            query += " AND id!=?"
            params.append(exclude_id)
        if db.execute(query, params).fetchone() is None:
            return slug
        slug = f"{base}-{n}"
        n += 1


def read_time(content):
    words = len(re.findall(r"[\wа-яА-ЯёЁ]+", content or ""))
    return max(1, round(words / 200))


def human_date(value):
    if not value:
        return ""
    try:
        dt = datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(value)
    months = (
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    )
    return f"{dt.day} {months[dt.month - 1]} {dt.year}"


def plural(value, forms):
    forms = forms.split(",")
    n = int(value or 0) % 100
    n1 = n % 10
    if 11 <= n <= 14:
        return forms[2]
    if n1 == 1:
        return forms[0]
    if 2 <= n1 <= 4:
        return forms[1]
    return forms[2]


def word_count(text):
    return len(re.findall(r"[\wа-яА-ЯёЁ]+", text or ""))


def iso_date(value):
    if not value:
        return ""
    try:
        return datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S").strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except ValueError:
        return str(value)


app.jinja_env.filters["human_date"] = human_date
app.jinja_env.filters["read_time"] = read_time
app.jinja_env.filters["plural"] = plural
app.jinja_env.filters["word_count"] = word_count
app.jinja_env.filters["iso_date"] = iso_date


# ---------------------------------------------------------------------------
# Лёгкий Markdown-рендерер
# ---------------------------------------------------------------------------

def _safe_url(url):
    url = html.unescape(url).strip()
    if url.startswith(("http://", "https://", "/", "#", "mailto:")):
        return html.escape(url, quote=True)
    return "#"


def inline_md(text):
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(
        r"!\[([^\]]*)\]\(([^)]+)\)",
        lambda m: f'<img src="{_safe_url(m.group(2))}" alt="{m.group(1)}" loading="lazy">',
        text,
    )
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: f'<a href="{_safe_url(m.group(2))}" target="_blank" rel="noopener">{m.group(1)}</a>',
        text,
    )
    return text


def _is_block_start(s):
    return bool(
        re.match(r"^(#{1,4})\s", s)
        or re.match(r"^[-*]\s", s)
        or re.match(r"^\d+\.\s", s)
        or s.startswith("> ")
        or s.startswith("```")
        or s in ("---", "***", "___")
    )


def render_markdown(source):
    """Возвращает (HTML, список заголовков для оглавления)."""
    if not source:
        return "", []
    lines = html.escape(source.replace("\r\n", "\n")).split("\n")
    out = []
    toc = []
    i = 0
    in_ul = in_ol = in_code = False
    code_lines = []
    code_lang = "text"

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    while i < len(lines):
        raw = lines[i]
        s = raw.strip()

        if s.startswith("```"):
            if in_code:
                out.append(
                    f'<pre data-lang="{code_lang}"><code>{"\n".join(code_lines)}</code></pre>'
                )
                in_code = False
                code_lines = []
            else:
                close_lists()
                in_code = True
                code_lang = s[3:].strip() or "text"
            i += 1
            continue

        if in_code:
            code_lines.append(raw)
            i += 1
            continue

        if not s:
            close_lists()
            i += 1
            continue

        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            close_lists()
            level = len(m.group(1))
            anchor = f"h-{len(toc) + 1}"
            title = re.sub(r"<[^>]+>", "", inline_md(m.group(2)))
            toc.append((level, title, anchor))
            out.append(f'<h{level} id="{anchor}">{inline_md(m.group(2))}</h{level}>')
            i += 1
            continue

        if s.startswith("> "):
            close_lists()
            quote = []
            while i < len(lines) and lines[i].strip().startswith("> "):
                quote.append(lines[i].strip()[2:])
                i += 1
            out.append(f"<blockquote>{inline_md(' '.join(quote))}</blockquote>")
            continue

        if re.match(r"^[-*]\s+", s):
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{inline_md(re.sub(r'^[-*]\s+', '', s))}</li>")
            i += 1
            continue

        if re.match(r"^\d+\.\s+", s):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{inline_md(re.sub(r'^\d+\.\s+', '', s))}</li>")
            i += 1
            continue

        if s in ("---", "***", "___"):
            close_lists()
            out.append("<hr>")
            i += 1
            continue

        close_lists()
        para = [s]
        i += 1
        while i < len(lines) and lines[i].strip() and not _is_block_start(lines[i].strip()):
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{inline_md(' '.join(para))}</p>")

    close_lists()
    if in_code:
        out.append(f'<pre data-lang="{code_lang}"><code>{"\n".join(code_lines)}</code></pre>')
    return "\n".join(out), toc


# ---------------------------------------------------------------------------
# Авторизация
# ---------------------------------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("uid"):
            flash("Войдите в аккаунт, чтобы продолжить", "info")
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


@app.context_processor
def inject_user():
    user = None
    if session.get("uid"):
        user = get_db().execute(
            "SELECT id, username, email, avatar, bio, balance, total_earned, is_admin "
            "FROM users WHERE id=?",
            (session["uid"],),
        ).fetchone()
    return {"current_user": user}


@app.before_request
def load_user():
    g.user = None
    if session.get("uid"):
        g.user = get_db().execute(
            "SELECT * FROM users WHERE id=?", (session["uid"],)
        ).fetchone()
        if g.user is None:
            session.clear()


# ---------------------------------------------------------------------------
# Публичные страницы
# ---------------------------------------------------------------------------

def personalized_feed(rows, uid=None):
    """Алгоритмическая лента «Для вас».

    Учитывает свежесть, вовлечённость (просмотры, лайки, комментарии),
    подписки и интересы автора, уже прочитанные статьи, небольшое
    исследовательское смещение и ограничение однообразия.
    """
    if not rows:
        return []

    db = get_db()
    today = datetime.now(timezone.utc).date()
    max_views = max(r["views"] or 0 for r in rows) or 1
    max_likes = max(r["likes"] or 0 for r in rows) or 1
    max_comments = max(r["comments_count"] or 0 for r in rows) or 1

    following = set()
    loved_authors = {}
    loved_categories = {}
    loved_tags = {}
    read_articles = set()
    read_authors = {}

    def add_interest(user_id, category, tags):
        if user_id:
            loved_authors[user_id] = loved_authors.get(user_id, 0) + 1
        if category:
            loved_categories[category] = loved_categories.get(category, 0) + 1
        for tag in (tags or "").split(","):
            tag = tag.strip().lower()
            if tag:
                loved_tags[tag] = loved_tags.get(tag, 0) + 1

    if uid:
        following = {
            r[0] for r in db.execute(
                "SELECT author_id FROM follows WHERE follower_id=?", (uid,)
            )
        }
        for r in db.execute(
            "SELECT a.user_id, a.category, a.tags FROM bookmarks b "
            "JOIN articles a ON a.id=b.article_id WHERE b.user_id=?", (uid,)
        ):
            add_interest(r[0], r[1], r[2])
        for r in db.execute(
            """SELECT v.article_id, a.user_id, a.category, a.tags
               FROM views v JOIN articles a ON a.id=v.article_id
               WHERE v.user_id=? ORDER BY v.created_at DESC LIMIT 200""", (uid,)
        ):
            read_articles.add(r[0])
            read_authors[r[1]] = read_authors.get(r[1], 0) + 1
            add_interest(r[1], r[2], r[3])

    # лайки привязаны к браузеру, а не к аккаунту
    for r in db.execute(
        """SELECT a.user_id, a.category, a.tags FROM likes l
           JOIN articles a ON a.id=l.article_id WHERE l.viewer_key=?""",
        (viewer_key(),),
    ):
        add_interest(r[0], r[1], r[2])

    def score(row):
        try:
            age = (today - datetime.strptime(row["published_at"][:10], "%Y-%m-%d").date()).days
        except (ValueError, TypeError):
            age = 30
        freshness = math.exp(-max(0, age) / 3.5)
        quality = (
            0.45 * math.log1p(row["views"] or 0) / math.log1p(max_views)
            + 0.35 * math.log1p(row["likes"] or 0) / math.log1p(max_likes)
            + 0.20 * math.log1p(row["comments_count"] or 0) / math.log1p(max_comments)
        )
        interest = 0.0
        if row["user_id"] in following:
            interest += 0.30
        interest += min(0.15, 0.05 * loved_authors.get(row["user_id"], 0))
        interest += min(0.12, 0.04 * loved_categories.get(row["category"], 0))
        tags = {t.strip().lower() for t in (row["tags"] or "").split(",") if t.strip()}
        if tags:
            interest += min(0.10, 0.02 * sum(loved_tags.get(t, 0) for t in tags))
        interest += min(0.10, 0.025 * read_authors.get(row["user_id"], 0))

        penalty = 0.45 if row["id"] in read_articles else 0.0

        # стабильное «исследовательское» смещение: одинаковому пользователю
        # в один день показывается одинаковая лента
        digest = hashlib.md5(
            f"{uid}-{row['id']}-{today.isoformat()}".encode("utf-8")
        ).digest()
        jitter = 0.06 * (int.from_bytes(digest[:4], "big") / 2**32 - 0.5)

        return 0.32 * freshness + 0.36 * quality + 0.32 * interest - penalty + jitter

    ranked = sorted(rows, key=score, reverse=True)

    # diversity: не более двух статей одного автора и трёх одной категории
    # в первой десятке, остальные смещаются ниже, но не теряются
    result, deferred = [], []
    authors, categories = {}, {}
    for row in ranked:
        author = row["user_id"]
        category = row["category"]
        if len(result) < 10 and (
            authors.get(author, 0) >= 2 or categories.get(category, 0) >= 3
        ):
            deferred.append(row)
            continue
        result.append(row)
        authors[author] = authors.get(author, 0) + 1
        categories[category] = categories.get(category, 0) + 1
    return result + deferred


@app.route("/")
def index():
    db = get_db()
    q = request.args.get("q", "").strip()
    cat = request.args.get("cat", "").strip()
    sort = request.args.get("sort", "smart")
    if sort not in ("smart", "new", "popular", "liked", "discussed"):
        sort = "smart"
    following = request.args.get("following") == "1"
    page = max(1, request.args.get("page", 1, type=int) or 1)
    per_page = 9

    where = ["a.status='published'"]
    params = []
    if following:
        if not session.get("uid"):
            flash("Войдите, чтобы смотреть ленту подписок", "info")
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        where.append(
            "EXISTS (SELECT 1 FROM follows f WHERE f.author_id=a.user_id AND f.follower_id=?)"
        )
        params.append(session["uid"])
    if q:
        where.append("(a.title LIKE ? OR a.excerpt LIKE ? OR a.content LIKE ? OR a.tags LIKE ?)")
        params.extend([f"%{q}%"] * 4)
    if cat:
        where.append("a.category=?")
        params.append(cat)
    clause = " AND ".join(where)

    all_rows = db.execute(
        f"""SELECT a.*, u.username, u.avatar,
                   (SELECT COUNT(*) FROM comments c WHERE c.article_id=a.id) AS comments_count
            FROM articles a JOIN users u ON u.id=a.user_id
            WHERE {clause}""",
        params,
    ).fetchall()

    if sort == "smart":
        all_rows = personalized_feed(all_rows, session.get("uid"))
    elif sort == "new":
        all_rows = sorted(
            all_rows, key=lambda r: r["published_at"] or "", reverse=True
        )
    elif sort == "popular":
        all_rows = sorted(all_rows, key=lambda r: r["views"] or 0, reverse=True)
    elif sort == "liked":
        all_rows = sorted(all_rows, key=lambda r: r["likes"] or 0, reverse=True)
    else:
        all_rows = sorted(
            all_rows,
            key=lambda r: ((r["comments_count"] or 0), (r["likes"] or 0)),
            reverse=True,
        )

    total = len(all_rows)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    rows = all_rows[(page - 1) * per_page: page * per_page]

    categories = [
        r[0] for r in db.execute(
            "SELECT DISTINCT category FROM articles WHERE status='published' "
            "AND category!='' ORDER BY category"
        )
    ]
    featured = db.execute(
        """SELECT a.*, u.username FROM articles a JOIN users u ON u.id=a.user_id
           WHERE a.status='published' ORDER BY a.views DESC LIMIT 3"""
    ).fetchall()
    stats = db.execute(
        """SELECT COUNT(*) AS articles,
                  COALESCE(SUM(views),0) AS views,
                  COALESCE(SUM(likes),0) AS likes
           FROM articles WHERE status='published'"""
    ).fetchone()
    authors = db.execute(
        """SELECT u.id, u.username, u.avatar,
                  COUNT(a.id) AS articles, COALESCE(SUM(a.views),0) AS views
           FROM users u JOIN articles a ON a.user_id=u.id
           WHERE a.status='published'
           GROUP BY u.id ORDER BY views DESC LIMIT 4"""
    ).fetchall()

    return render_template(
        "index.html",
        articles=rows,
        categories=categories,
        featured=featured,
        stats=stats,
        authors=authors,
        following=following,
        q=q,
        cat=cat,
        sort=sort,
        page=page,
        pages=pages,
        total=total,
    )


@app.route("/article/<slug>")
def article(slug):
    db = get_db()
    row = db.execute(
        """SELECT a.*, u.username, u.avatar, u.bio,
                  (SELECT COUNT(*) FROM comments c WHERE c.article_id=a.id) AS comments_count
           FROM articles a JOIN users u ON u.id=a.user_id
           WHERE a.slug=? AND a.status='published'""",
        (slug,),
    ).fetchone()
    if row is None:
        abort(404)

    record_view(row["id"])

    content_html, toc = render_markdown(row["content"])
    related = db.execute(
        """SELECT a.*, u.username FROM articles a JOIN users u ON u.id=a.user_id
           WHERE a.status='published' AND a.id!=? AND a.category=?
           ORDER BY a.views DESC LIMIT 3""",
        (row["id"], row["category"]),
    ).fetchall()
    if not related:
        related = db.execute(
            """SELECT a.*, u.username FROM articles a JOIN users u ON u.id=a.user_id
               WHERE a.status='published' AND a.id!=? ORDER BY a.views DESC LIMIT 3""",
            (row["id"],),
        ).fetchall()

    comments = db.execute(
        """SELECT c.*, u.username, u.avatar FROM comments c
           JOIN users u ON u.id=c.user_id WHERE c.article_id=?
           ORDER BY c.created_at ASC""",
        (row["id"],),
    ).fetchall()

    key = viewer_key()
    liked = bool(db.execute(
        "SELECT 1 FROM likes WHERE article_id=? AND viewer_key=?", (row["id"], key)
    ).fetchone())
    bookmarked = bool(session.get("uid") and db.execute(
        "SELECT 1 FROM bookmarks WHERE article_id=? AND user_id=?",
        (row["id"], session["uid"]),
    ).fetchone())
    is_following = bool(session.get("uid") and db.execute(
        "SELECT 1 FROM follows WHERE follower_id=? AND author_id=?",
        (session["uid"], row["user_id"]),
    ).fetchone())
    followers = db.execute(
        "SELECT COUNT(*) FROM follows WHERE author_id=?", (row["user_id"],)
    ).fetchone()[0]

    return render_template(
        "article.html",
        article=row,
        content_html=content_html,
        toc=toc,
        related=related,
        comments=comments,
        liked=liked,
        bookmarked=bookmarked,
        is_following=is_following,
        followers=followers,
        tip_amounts=TIP_AMOUNTS,
    )


def record_view(article_id):
    db = get_db()
    key = viewer_key()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cur = db.execute(
        "INSERT OR IGNORE INTO views (article_id,viewer_key,user_id,day,source,created_at) "
        "VALUES (?,?,?,?,?,?)",
        (article_id, key, session.get("uid"), day, detect_source(), now()),
    )
    if cur.rowcount:
        db.execute("UPDATE articles SET views=views+1 WHERE id=?", (article_id,))
        db.commit()


# ---------------------------------------------------------------------------
# Авторизация
# ---------------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("uid"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        db = get_db()

        if len(username) < 3 or len(username) > 30:
            flash("Имя должно быть от 3 до 30 символов", "error")
        elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            flash("Введите корректный email", "error")
        elif len(password) < 6:
            flash("Пароль должен быть не короче 6 символов", "error")
        elif password != confirm:
            flash("Пароли не совпадают", "error")
        elif db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            flash("Этот email уже занят", "error")
        elif db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            flash("Это имя уже занято", "error")
        else:
            db.execute(
                "INSERT INTO users (username,email,password_hash,bio,avatar,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (username, email, generate_password_hash(password), "", "✍️", now()),
            )
            db.commit()
            uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            session["uid"] = uid
            flash("Добро пожаловать в «Слово»! Пора писать.", "success")
            return redirect(url_for("dashboard"))
        return render_template("auth.html", mode="register", values=request.form)

    return render_template("auth.html", mode="register", values={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("uid"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        login_value = request.form.get("login", "").strip().lower()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE email=? OR username=?",
            (login_value, login_value),
        ).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["uid"] = user["id"]
            flash(f"С возвращением, {user['username']}!", "success")
            nxt = request.form.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
        flash("Неверный логин или пароль", "error")
        return render_template("auth.html", mode="login", values=request.form)

    return render_template(
        "auth.html", mode="login", values={}, next=request.args.get("next", "")
    )


@app.route("/logout")
def logout():
    session.clear()
    flash("Вы вышли из аккаунта", "info")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Личный кабинет
# ---------------------------------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    uid = session["uid"]
    totals = db.execute(
        """SELECT COUNT(*) AS articles,
                  COALESCE(SUM(views),0) AS views,
                  COALESCE(SUM(likes),0) AS likes,
                  COALESCE(SUM(status='published'),0) AS published
           FROM articles WHERE user_id=?""",
        (uid,),
    ).fetchone()
    articles = db.execute(
        """SELECT a.*, (SELECT COUNT(*) FROM comments c WHERE c.article_id=a.id) AS comments_count
           FROM articles a WHERE a.user_id=? ORDER BY a.updated_at DESC LIMIT 6""",
        (uid,),
    ).fetchall()
    chart = daily_stats(uid, 14)
    recent_comments = db.execute(
        """SELECT c.*, u.username, u.avatar, a.title, a.slug
           FROM comments c JOIN users u ON u.id=c.user_id
           JOIN articles a ON a.id=c.article_id
           WHERE a.user_id=? ORDER BY c.created_at DESC LIMIT 4""",
        (uid,),
    ).fetchall()
    return render_template(
        "dashboard.html",
        section="overview",
        totals=totals,
        articles=articles,
        chart=chart,
        recent_comments=recent_comments,
    )


@app.route("/dashboard/articles")
@login_required
def my_articles():
    db = get_db()
    articles = db.execute(
        """SELECT a.*, (SELECT COUNT(*) FROM comments c WHERE c.article_id=a.id) AS comments_count
           FROM articles a WHERE a.user_id=? ORDER BY a.updated_at DESC""",
        (session["uid"],),
    ).fetchall()
    return render_template("my_articles.html", section="articles", articles=articles)


@app.route("/dashboard/stats")
@login_required
def stats_page():
    db = get_db()
    uid = session["uid"]
    chart = daily_stats(uid, 30)
    sources = db.execute(
        """SELECT v.source, COUNT(*) AS n FROM views v
           JOIN articles a ON a.id=v.article_id
           WHERE a.user_id=? GROUP BY v.source ORDER BY n DESC""",
        (uid,),
    ).fetchall()
    top = db.execute(
        """SELECT a.id,a.title,a.slug,a.views,a.likes,a.status,
                  (SELECT COUNT(*) FROM comments c WHERE c.article_id=a.id) AS comments_count
           FROM articles a WHERE a.user_id=? ORDER BY a.views DESC LIMIT 8""",
        (uid,),
    ).fetchall()
    return render_template(
        "stats.html", section="stats", chart=chart, sources=sources, top=top
    )


@app.route("/dashboard/saved")
@login_required
def saved():
    db = get_db()
    articles = db.execute(
        """SELECT a.*, u.username FROM bookmarks b
           JOIN articles a ON a.id=b.article_id
           JOIN users u ON u.id=a.user_id
           WHERE b.user_id=? AND a.status='published'
           ORDER BY b.created_at DESC""",
        (session["uid"],),
    ).fetchall()
    return render_template("saved.html", section="saved", articles=articles)


@app.route("/dashboard/profile", methods=["GET", "POST"])
@login_required
def profile():
    db = get_db()
    uid = session["uid"]
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        bio = request.form.get("bio", "").strip()[:500]
        avatar = request.form.get("avatar", "✍️").strip()[:8] or "✍️"
        password = request.form.get("password", "")
        if len(username) < 3 or len(username) > 30:
            flash("Имя должно быть от 3 до 30 символов", "error")
        elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            flash("Введите корректный email", "error")
        elif db.execute("SELECT 1 FROM users WHERE email=? AND id!=?", (email, uid)).fetchone():
            flash("Этот email уже занят", "error")
        elif db.execute("SELECT 1 FROM users WHERE username=? AND id!=?", (username, uid)).fetchone():
            flash("Это имя уже занято", "error")
        elif password and len(password) < 6:
            flash("Новый пароль должен быть не короче 6 символов", "error")
        else:
            if password:
                db.execute(
                    "UPDATE users SET username=?,email=?,bio=?,avatar=?,password_hash=? WHERE id=?",
                    (username, email, bio, avatar, generate_password_hash(password), uid),
                )
            else:
                db.execute(
                    "UPDATE users SET username=?,email=?,bio=?,avatar=? WHERE id=?",
                    (username, email, bio, avatar, uid),
                )
            db.commit()
            flash("Профиль обновлён", "success")
            return redirect(url_for("profile"))

    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return render_template("profile.html", section="profile", profile=user)


def daily_stats(uid, days):
    db = get_db()
    rows = db.execute(
        """SELECT v.day, COUNT(*) AS n FROM views v
           JOIN articles a ON a.id=v.article_id
           WHERE a.user_id=? AND v.day >= date('now', ?)
           GROUP BY v.day ORDER BY v.day""",
        (uid, f"-{days - 1} day"),
    ).fetchall()
    values = {r["day"]: r["n"] for r in rows}
    labels = []
    data = []
    today = datetime.now(timezone.utc).date()
    for offset in range(days - 1, -1, -1):
        d = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        labels.append(d)
        data.append(values.get(d, 0))
    return {"labels": labels, "values": data}


# ---------------------------------------------------------------------------
# Редактор
# ---------------------------------------------------------------------------

@app.route("/editor/new", endpoint="editor_new")
@app.route("/editor/<int:article_id>")
@login_required
def editor(article_id=None):
    article = None
    if article_id:
        article = get_db().execute(
            "SELECT * FROM articles WHERE id=? AND user_id=?",
            (article_id, session["uid"]),
        ).fetchone()
        if article is None:
            abort(404)
    return render_template("editor.html", article=article, section="articles")


@app.route("/api/articles", methods=["POST"])
@login_required
def api_create_article():
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()[:200]
    content = str(data.get("content", ""))
    if not title:
        return jsonify(error="Введите заголовок"), 400
    db = get_db()
    slug = unique_slug(db, title)
    status = "published" if data.get("status") == "published" else "draft"
    published_at = now() if status == "published" else None
    db.execute(
        """INSERT INTO articles
           (user_id,title,slug,excerpt,content,cover,category,tags,status,
            meta_title,meta_description,focus_keyword,
            created_at,updated_at,published_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            session["uid"], title, slug,
            str(data.get("excerpt", "")).strip()[:500],
            content,
            str(data.get("cover", "1"))[:4],
            str(data.get("category", "Разное")).strip()[:60] or "Разное",
            str(data.get("tags", "")).strip()[:200],
            status,
            str(data.get("meta_title", "")).strip()[:200],
            str(data.get("meta_description", "")).strip()[:300],
            str(data.get("focus_keyword", "")).strip()[:100],
            now(), now(), published_at,
        ),
    )
    db.commit()
    aid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    if status == "published":
        move_credits(
            session["uid"], PUBLISH_BONUS, "bonus",
            f"Бонус за публикацию: {title}", article_id=aid,
        )
        db.commit()
    return jsonify(id=aid, slug=slug, status=status)


@app.route("/api/articles/<int:article_id>", methods=["POST"])
@login_required
def api_update_article(article_id):
    db = get_db()
    row = db.execute(
        "SELECT * FROM articles WHERE id=? AND user_id=?", (article_id, session["uid"])
    ).fetchone()
    if row is None:
        abort(404)
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", row["title"])).strip()[:200]
    if not title:
        return jsonify(error="Введите заголовок"), 400
    status = "published" if data.get("status") == "published" else "draft"
    published_at = row["published_at"] or (now() if status == "published" else None)
    slug = unique_slug(db, title, article_id) if title != row["title"] else row["slug"]
    db.execute(
        """UPDATE articles SET title=?,slug=?,excerpt=?,content=?,cover=?,category=?,
           tags=?,status=?,meta_title=?,meta_description=?,focus_keyword=?,
           updated_at=?,published_at=? WHERE id=?""",
        (
            title, slug,
            str(data.get("excerpt", row["excerpt"])).strip()[:500],
            str(data.get("content", row["content"])),
            str(data.get("cover", row["cover"]))[:4],
            str(data.get("category", row["category"])).strip()[:60] or "Разное",
            str(data.get("tags", row["tags"])).strip()[:200],
            status,
            str(data.get("meta_title", row["meta_title"])).strip()[:200],
            str(data.get("meta_description", row["meta_description"])).strip()[:300],
            str(data.get("focus_keyword", row["focus_keyword"])).strip()[:100],
            now(), published_at, article_id,
        ),
    )
    if status == "published" and row["status"] != "published":
        move_credits(
            session["uid"], PUBLISH_BONUS, "bonus",
            f"Бонус за публикацию: {title}", article_id=article_id,
        )
    db.commit()
    return jsonify(id=article_id, slug=slug, status=status)


@app.route("/api/articles/<int:article_id>", methods=["DELETE"])
@login_required
def api_delete_article(article_id):
    db = get_db()
    row = db.execute(
        "SELECT 1 FROM articles WHERE id=? AND user_id=?", (article_id, session["uid"])
    ).fetchone()
    if row is None:
        abort(404)
    db.execute("DELETE FROM articles WHERE id=?", (article_id,))
    db.commit()
    return jsonify(ok=True)


@app.route("/api/preview", methods=["POST"])
@login_required
def api_preview():
    data = request.get_json(silent=True) or {}
    rendered, _ = render_markdown(str(data.get("content", "")))
    return jsonify(html=rendered)


@app.route("/api/stats")
@login_required
def api_stats():
    days = request.args.get("days", 14, type=int) or 14
    days = min(max(days, 7), 90)
    return jsonify(daily_stats(session["uid"], days))


# ---------------------------------------------------------------------------
# Взаимодействие
# ---------------------------------------------------------------------------

@app.route("/api/articles/<int:article_id>/like", methods=["POST"])
@login_required
def api_like(article_id):
    db = get_db()
    key = viewer_key()
    exists = db.execute(
        "SELECT 1 FROM likes WHERE article_id=? AND viewer_key=?", (article_id, key)
    ).fetchone()
    if exists:
        db.execute("DELETE FROM likes WHERE article_id=? AND viewer_key=?", (article_id, key))
        db.execute(
            "UPDATE articles SET likes=MAX(0,likes-1) WHERE id=?", (article_id,)
        )
        liked = False
    else:
        db.execute(
            "INSERT INTO likes (article_id,viewer_key,created_at) VALUES (?,?,?)",
            (article_id, key, now()),
        )
        db.execute("UPDATE articles SET likes=likes+1 WHERE id=?", (article_id,))
        liked = True
    db.commit()
    count = db.execute("SELECT likes FROM articles WHERE id=?", (article_id,)).fetchone()[0]
    return jsonify(liked=liked, count=count)


@app.route("/api/articles/<int:article_id>/bookmark", methods=["POST"])
@login_required
def api_bookmark(article_id):
    db = get_db()
    uid = session["uid"]
    exists = db.execute(
        "SELECT 1 FROM bookmarks WHERE article_id=? AND user_id=?", (article_id, uid)
    ).fetchone()
    if exists:
        db.execute(
            "DELETE FROM bookmarks WHERE article_id=? AND user_id=?", (article_id, uid)
        )
        saved = False
    else:
        db.execute(
            "INSERT INTO bookmarks (article_id,user_id,created_at) VALUES (?,?,?)",
            (article_id, uid, now()),
        )
        saved = True
    db.commit()
    return jsonify(saved=saved)


@app.route("/api/articles/<int:article_id>/comments", methods=["POST"])
@login_required
def api_comment(article_id):
    data = request.get_json(silent=True) or {}
    content = str(data.get("content", "")).strip()[:1500]
    if not content:
        return jsonify(error="Комментарий пустой"), 400
    db = get_db()
    db.execute(
        "INSERT INTO comments (article_id,user_id,content,created_at) VALUES (?,?,?,?)",
        (article_id, session["uid"], html.escape(content), now()),
    )
    db.commit()
    user = g.user
    return jsonify(
        username=user["username"],
        avatar=user["avatar"],
        content=html.escape(content),
        date=human_date(now()),
        id=db.execute("SELECT last_insert_rowid()").fetchone()[0],
    )


# ---------------------------------------------------------------------------
# Тестовая экономика: подписки, поддержка, начисления, выплаты
# ---------------------------------------------------------------------------

TIP_AMOUNTS = (50, 100, 300, 500)
DAILY_POOL = 100  # тестовых кредитов распределяется между авторами за день
MIN_PAYOUT = 500
PUBLISH_BONUS = 50


def move_credits(user_id, amount, kind, description="", counterparty_id=None, article_id=None):
    """Записывает операцию в журнал и меняет баланс (без commit)."""
    db = get_db()
    db.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount, user_id))
    if amount > 0 and kind in ("tip_in", "view_reward", "bonus"):
        db.execute(
            "UPDATE users SET total_earned=total_earned+? WHERE id=?", (amount, user_id)
        )
    db.execute(
        """INSERT INTO transactions
           (user_id,type,amount,counterparty_id,article_id,description,created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (user_id, kind, amount, counterparty_id, article_id, description, now()),
    )


def accrue_daily_rewards():
    """Один раз в день начисляет авторам долю пула пропорционально просмотрам."""
    db = get_db()
    rows = db.execute(
        """SELECT a.user_id AS uid, v.day AS day, COUNT(*) AS n
           FROM views v JOIN articles a ON a.id=v.article_id
           GROUP BY a.user_id, v.day"""
    ).fetchall()
    by_day = {}
    for r in rows:
        by_day.setdefault(r["day"], []).append(r)
    changed = False
    for day, items in by_day.items():
        total = sum(i["n"] for i in items)
        for item in items:
            if db.execute(
                "SELECT 1 FROM daily_rewards WHERE user_id=? AND day=?",
                (item["uid"], day),
            ).fetchone():
                continue
            amount = max(1, round(DAILY_POOL * item["n"] / total))
            db.execute(
                "INSERT INTO daily_rewards (user_id,day,amount) VALUES (?,?,?)",
                (item["uid"], day, amount),
            )
            move_credits(
                item["uid"], amount, "view_reward",
                f"Начисление за {day}: {item['n']} уникальных просмотров",
            )
            changed = True
    if changed:
        db.commit()


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user or not g.user["is_admin"]:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


@app.route("/api/articles/<int:article_id>/tip", methods=["POST"])
@login_required
def api_tip(article_id):
    db = get_db()
    a = db.execute(
        "SELECT user_id,title,status FROM articles WHERE id=?", (article_id,)
    ).fetchone()
    if a is None or a["status"] != "published":
        abort(404)
    if a["user_id"] == session["uid"]:
        return jsonify(error="Нельзя поддержать свою статью"), 400
    data = request.get_json(silent=True) or {}
    try:
        amount = int(data.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0
    if amount not in TIP_AMOUNTS and not (10 <= amount <= 1000):
        return jsonify(error="Выберите сумму от 10 до 1000 кредитов"), 400
    if g.user["balance"] < amount:
        return jsonify(error="Недостаточно тестовых кредитов"), 400

    move_credits(
        session["uid"], -amount, "tip_out",
        f"Поддержка статьи «{a['title']}»",
        counterparty_id=a["user_id"], article_id=article_id,
    )
    move_credits(
        a["user_id"], amount, "tip_in",
        f"Поддержка от {g.user['username']}: «{a['title']}»",
        counterparty_id=session["uid"], article_id=article_id,
    )
    db.commit()
    return jsonify(balance=g.user["balance"] - amount, amount=amount)


@app.route("/api/authors/<int:author_id>/follow", methods=["POST"])
@login_required
def api_follow(author_id):
    if author_id == session["uid"]:
        return jsonify(error="Нельзя подписаться на себя"), 400
    db = get_db()
    exists = db.execute(
        "SELECT 1 FROM follows WHERE follower_id=? AND author_id=?",
        (session["uid"], author_id),
    ).fetchone()
    if exists:
        db.execute(
            "DELETE FROM follows WHERE follower_id=? AND author_id=?",
            (session["uid"], author_id),
        )
        following = False
    else:
        db.execute(
            "INSERT INTO follows (follower_id,author_id,created_at) VALUES (?,?,?)",
            (session["uid"], author_id, now()),
        )
        following = True
    db.commit()
    count = db.execute(
        "SELECT COUNT(*) FROM follows WHERE author_id=?", (author_id,)
    ).fetchone()[0]
    return jsonify(following=following, count=count)


@app.route("/dashboard/monetization")
@login_required
def monetization():
    accrue_daily_rewards()
    db = get_db()
    uid = session["uid"]
    wallet = db.execute("SELECT balance,total_earned FROM users WHERE id=?", (uid,)).fetchone()
    totals = db.execute(
        """SELECT
             COALESCE(SUM(CASE WHEN type='tip_in' THEN amount ELSE 0 END),0) AS tips,
             COALESCE(SUM(CASE WHEN type='view_reward' THEN amount ELSE 0 END),0) AS rewards,
             COALESCE(SUM(CASE WHEN type='bonus' THEN amount ELSE 0 END),0) AS bonuses
           FROM transactions WHERE user_id=?""",
        (uid,),
    ).fetchone()
    followers = db.execute(
        "SELECT COUNT(*) FROM follows WHERE author_id=?", (uid,)
    ).fetchone()[0]
    transactions = db.execute(
        """SELECT t.*, u.username AS counterparty FROM transactions t
           LEFT JOIN users u ON u.id=t.counterparty_id
           WHERE t.user_id=? ORDER BY t.created_at DESC LIMIT 30""",
        (uid,),
    ).fetchall()
    payouts = db.execute(
        "SELECT * FROM payouts WHERE user_id=? ORDER BY created_at DESC", (uid,)
    ).fetchall()
    daily = db.execute(
        """SELECT substr(created_at,1,10) AS day, SUM(amount) AS n
           FROM transactions WHERE user_id=? AND amount>0
           AND type IN ('tip_in','view_reward','bonus')
           GROUP BY day ORDER BY day DESC LIMIT 14""",
        (uid,),
    ).fetchall()
    daily = list(reversed(daily))
    chart = {
        "labels": [r["day"] for r in daily],
        "values": [r["n"] for r in daily],
    }
    return render_template(
        "monetization.html", section="monetization", wallet=wallet, totals=totals,
        followers=followers, transactions=transactions, payouts=payouts,
        chart=chart, min_payout=MIN_PAYOUT, tip_amounts=TIP_AMOUNTS,
    )


@app.route("/dashboard/monetization/payout", methods=["POST"])
@login_required
def request_payout():
    db = get_db()
    try:
        amount = int(request.form.get("amount", ""))
    except (TypeError, ValueError):
        amount = 0
    method = request.form.get("method", "Карта •••• 4242").strip()[:60] or "Карта •••• 4242"
    uid = session["uid"]
    pending = db.execute(
        "SELECT 1 FROM payouts WHERE user_id=? AND status='pending'", (uid,)
    ).fetchone()
    if amount < MIN_PAYOUT:
        flash(f"Минимальная сумма выплаты — {MIN_PAYOUT} кредитов", "error")
    elif amount > g.user["balance"]:
        flash("Недостаточно средств на балансе", "error")
    elif pending:
        flash("У вас уже есть заявка на обработке", "error")
    else:
        db.execute(
            "INSERT INTO payouts (user_id,amount,method,status,created_at) VALUES (?,?,?,?,?)",
            (uid, amount, method, "pending", now()),
        )
        move_credits(uid, -amount, "payout", f"Заявка на выплату: {method}")
        db.commit()
        flash("Заявка создана. В тестовом режиме её обработает админ.", "success")
    return redirect(url_for("monetization"))


@app.route("/admin/payouts")
@login_required
@admin_required
def admin_payouts():
    rows = get_db().execute(
        """SELECT p.*, u.username, u.email FROM payouts p
           JOIN users u ON u.id=p.user_id
           ORDER BY (p.status='pending') DESC, p.created_at DESC"""
    ).fetchall()
    return render_template("admin_payouts.html", payouts=rows)


@app.route("/admin/payouts/<int:payout_id>", methods=["POST"])
@login_required
@admin_required
def process_payout(payout_id):
    db = get_db()
    row = db.execute("SELECT * FROM payouts WHERE id=?", (payout_id,)).fetchone()
    if row is None or row["status"] != "pending":
        abort(404)
    action = request.form.get("action")
    if action == "paid":
        db.execute(
            "UPDATE payouts SET status='paid', processed_at=? WHERE id=?",
            (now(), payout_id),
        )
        flash("Выплата отмечена как выполненная", "success")
    elif action == "rejected":
        db.execute(
            "UPDATE payouts SET status='rejected', processed_at=? WHERE id=?",
            (now(), payout_id),
        )
        move_credits(
            row["user_id"], row["amount"], "refund",
            f"Возврат по отклонённой заявке №{payout_id}",
        )
        flash("Заявка отклонена, кредиты возвращены автору", "info")
    else:
        abort(400)
    db.commit()
    return redirect(url_for("admin_payouts"))


# ---------------------------------------------------------------------------
# SEO: robots, sitemap, RSS
# ---------------------------------------------------------------------------

@app.route("/robots.txt")
def robots_txt():
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /dashboard\n"
        "Disallow: /editor\n"
        "Disallow: /login\n"
        "Disallow: /register\n"
        "Disallow: /api/\n"
        "Disallow: /admin\n"
        "\n"
        f"Sitemap: {url_for('sitemap_xml', _external=True)}\n"
    )
    return Response(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    db = get_db()
    rows = db.execute(
        "SELECT slug,updated_at FROM articles WHERE status='published' "
        "ORDER BY published_at DESC"
    ).fetchall()
    items = []
    for path, lastmod in [(url_for("index", _external=True), None)] + [
        (url_for("article", slug=r["slug"], _external=True), r["updated_at"][:10])
        for r in rows
    ]:
        item = f"<url><loc>{xml_escape(path)}</loc>"
        if lastmod:
            item += f"<lastmod>{lastmod}</lastmod>"
        item += "</url>"
        items.append(item)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(items)
        + "</urlset>"
    )
    return Response(xml, mimetype="application/xml")


@app.route("/rss.xml")
@app.route("/feed.xml", endpoint="feed_rss")
def feed_rss():
    db = get_db()
    rows = db.execute(
        """SELECT a.*, u.username FROM articles a JOIN users u ON u.id=a.user_id
           WHERE a.status='published' ORDER BY a.published_at DESC LIMIT 20"""
    ).fetchall()
    link = url_for("index", _external=True)
    items = []
    for a in rows:
        url = url_for("article", slug=a["slug"], _external=True)
        try:
            dt = datetime.strptime(a["published_at"][:19], "%Y-%m-%d %H:%M:%S")
            pub = format_datetime(dt.replace(tzinfo=timezone.utc))
        except (ValueError, TypeError):
            pub = ""
        description = a["excerpt"] or a["content"][:200]
        items.append(
            "<item>"
            f"<title>{xml_escape(a['title'])}</title>"
            f"<link>{xml_escape(url)}</link>"
            f"<guid isPermaLink=\"true\">{xml_escape(url)}</guid>"
            f"<description>{xml_escape(description)}</description>"
            f"<category>{xml_escape(a['category'])}</category>"
            f"<pubDate>{pub}</pubDate>"
            "</item>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        f"<title>Слово — статьи</title><link>{xml_escape(link)}</link>"
        "<description>Платформа для авторов: статьи, статистика, читатели.</description>"
        + "".join(items)
        + "</channel></rss>"
    )
    return Response(xml, mimetype="application/rss+xml")


# ---------------------------------------------------------------------------
# Ошибки
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="Страница не найдена"), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, message="Доступ только для администратора"), 403


@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", code=500, message="Что-то пошло не так"), 500


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
