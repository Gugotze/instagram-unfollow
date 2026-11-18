import sqlite3
import threading
from datetime import datetime, date
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

_DDL = """
CREATE TABLE IF NOT EXISTS users (
    pk INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    full_name TEXT,
    profile_pic_url TEXT,
    follows_me INTEGER DEFAULT 0,
    i_follow INTEGER DEFAULT 0,
    is_mutual INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    story_views INTEGER DEFAULT 0,
    dm INTEGER DEFAULT 0,
    score REAL DEFAULT 0,
    protected INTEGER DEFAULT 0,
    unfollowed_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS unfollow_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pk INTEGER,
    username TEXT,
    at TEXT,
    ok INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_users_score ON users(is_mutual, protected, unfollowed_at, score);
"""

_local = threading.local()


def _db_path() -> Path:
    try:
        acct = (DATA_DIR / "current").read_text().strip() or "default"
    except Exception:
        acct = "default"
    d = DATA_DIR / "accounts" / acct
    d.mkdir(parents=True, exist_ok=True)
    return d / "unfollow.db"


def conn() -> sqlite3.Connection:
    path = str(_db_path())
    if getattr(_local, "path", None) != path:
        old = getattr(_local, "c", None)
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        c.executescript(_DDL)
        _local.c, _local.path = c, path
    return _local.c


def init() -> None:
    conn()


def get_setting(key: str, default: str | None = None) -> str | None:
    row = conn().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    c = conn()
    c.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    c.commit()


def upsert_user(u: dict) -> None:
    c = conn()
    c.execute(
        """INSERT INTO users(pk, username, full_name, profile_pic_url, follows_me, i_follow, is_mutual,
                             likes, comments, story_views, dm, score, updated_at)
           VALUES(:pk,:username,:full_name,:profile_pic_url,:follows_me,:i_follow,:is_mutual,
                  :likes,:comments,:story_views,:dm,:score,:updated_at)
           ON CONFLICT(pk) DO UPDATE SET
             username=excluded.username, full_name=excluded.full_name, profile_pic_url=excluded.profile_pic_url,
             follows_me=excluded.follows_me, i_follow=excluded.i_follow, is_mutual=excluded.is_mutual,
             likes=excluded.likes, comments=excluded.comments, story_views=excluded.story_views,
             dm=excluded.dm, score=excluded.score, updated_at=excluded.updated_at""",
        u,
    )
    c.commit()


def next_candidates(limit: int, max_score: float = 0, scope: str = "mutuals") -> list[sqlite3.Row]:
    if scope == "nonfollowers":
        return conn().execute(
            """SELECT pk, username, score FROM users
               WHERE i_follow=1 AND follows_me=0 AND protected=0 AND unfollowed_at IS NULL
               ORDER BY score ASC, pk ASC LIMIT ?""",
            (limit,),
        ).fetchall()
    return conn().execute(
        """SELECT pk, username, score FROM users
           WHERE is_mutual=1 AND protected=0 AND unfollowed_at IS NULL AND i_follow=1 AND score<=?
           ORDER BY score ASC, pk ASC LIMIT ?""",
        (max_score, limit),
    ).fetchall()


def mark_unfollowed(pk: int, username: str, ok: bool, error: str | None = None) -> None:
    c = conn()
    now = datetime.now().isoformat(timespec="seconds")
    c.execute("INSERT INTO unfollow_log(pk, username, at, ok, error) VALUES(?,?,?,?,?)", (pk, username, now, int(ok), error))
    if ok:
        c.execute("UPDATE users SET i_follow=0, is_mutual=0, unfollowed_at=? WHERE pk=?", (now, pk))
    c.commit()


def unfollowed_today() -> int:
    row = conn().execute(
        "SELECT COUNT(*) AS n FROM unfollow_log WHERE ok=1 AND date(at)=date('now','localtime')"
    ).fetchone()
    return row["n"]


def stats() -> dict:
    c = conn()
    def one(sql, *a):
        return c.execute(sql, a).fetchone()[0]
    max_score = float(get_setting("max_score", "0") or 0)
    target = get_setting("worker_target", "mutuals") or "mutuals"
    mutuals_queue = one("SELECT COUNT(*) FROM users WHERE is_mutual=1 AND unfollowed_at IS NULL AND protected=0 AND score<=?", max_score)
    nonf_pending = one("SELECT COUNT(*) FROM users WHERE i_follow=1 AND follows_me=0 AND protected=0 AND unfollowed_at IS NULL")
    return {
        "total_following": one("SELECT COUNT(*) FROM users WHERE i_follow=1"),
        "mutuals_pending": one("SELECT COUNT(*) FROM users WHERE is_mutual=1 AND unfollowed_at IS NULL AND protected=0"),
        "queue": nonf_pending if target == "nonfollowers" else mutuals_queue,
        "protected": one("SELECT COUNT(*) FROM users WHERE protected=1 AND unfollowed_at IS NULL"),
        "not_following_back": one("SELECT COUNT(*) FROM users WHERE i_follow=1 AND follows_me=0 AND unfollowed_at IS NULL"),
        "nonfollowers_pending": nonf_pending,
        "unfollowed_total": one("SELECT COUNT(*) FROM unfollow_log WHERE ok=1"),
        "unfollowed_today": unfollowed_today(),
    }
