"""Sincroniza followers/following + sinais de interação e grava o ranking no SQLite."""
import json
import time
import traceback
from datetime import datetime, timedelta, timezone

import db
from insta import get_client

MEDIA_LIMIT = 50          # posts recentes analisados
DM_RANGE_DAYS = 365       # DMs contam se a thread teve atividade no último ano
DM_MAX_THREADS = 800      # teto de segurança na paginação
DM_RECENT_DAYS = 45

W_LIKE = 1
W_COMMENT = 2
W_STORY = 1
W_DM = 3
W_DM_RECENT = 2

PROGRESS_KEY = "sync_progress"


def _progress(**kw) -> None:
    kw["at"] = datetime.now().isoformat(timespec="seconds")
    db.set_setting(PROGRESS_KEY, json.dumps(kw))


def get_progress() -> dict | None:
    raw = db.get_setting(PROGRESS_KEY)
    return json.loads(raw) if raw else None


def _to_dt(ts) -> datetime | None:
    try:
        if ts is None:
            return None
        if isinstance(ts, (int, float)):
            ts = ts / 1_000_000 if ts > 1e12 else ts  # alguns campos vêm em microssegundos
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        if isinstance(ts, datetime):
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    return None


def _recency_bonus(ts) -> int:
    dt = _to_dt(ts)
    if dt is None:
        return 0
    return W_DM_RECENT if (datetime.now(timezone.utc) - dt).days <= DM_RECENT_DAYS else 0


def _collect_dm_scores(cl, touch) -> None:
    """Percorre threads de DM até atividade mais antiga que DM_RANGE_DAYS (ou teto)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=DM_RANGE_DAYS)
    cursor, fetched, page = None, 0, 0
    while fetched < DM_MAX_THREADS:
        chunk, cursor = cl.direct_threads_chunk(None, None, 1, cursor)
        page += 1
        old_found = False
        for t in chunk:
            dt = _to_dt(getattr(t, "last_activity_at", None))
            if dt is not None and dt < cutoff:
                old_found = True
                continue  # thread com mais de 1 ano: não pontua
            bonus = W_DM + _recency_bonus(getattr(t, "last_activity_at", None))
            for u in getattr(t, "users", []) or []:
                touch(int(u.pk), u.username, u.full_name or "", str(u.profile_pic_url or ""))["dm"] += bonus
            fetched += 1
        _progress(state="running", step="dm", done=fetched,
                  msg=f"DMs: {fetched} threads analisadas (pág. {page})")
        if old_found or not cursor or not chunk:
            break
        time.sleep(1)


def rescore_dm() -> None:
    """Atualiza só a coluna dm + score, percorrendo threads do último ano."""
    db.init()
    cl = get_client()
    dm_map: dict[int, int] = {}

    def touch(pk, *a):
        return dm_map.setdefault(pk, 0)

    cutoff = datetime.now(timezone.utc) - timedelta(days=DM_RANGE_DAYS)
    cursor, fetched, page = None, 0, 0
    while fetched < DM_MAX_THREADS:
        chunk, cursor = cl.direct_threads_chunk(None, None, 1, cursor)
        page += 1
        old_found = False
        for t in chunk:
            dt = _to_dt(getattr(t, "last_activity_at", None))
            if dt is not None and dt < cutoff:
                old_found = True
                continue
            bonus = W_DM + _recency_bonus(getattr(t, "last_activity_at", None))
            for u in getattr(t, "users", []) or []:
                pk = int(u.pk)
                dm_map[pk] = dm_map.get(pk, 0) + bonus
            fetched += 1
        print(f"DMs: {fetched} threads (pág. {page})", flush=True)
        if old_found or not cursor or not chunk:
            break
        time.sleep(1)

    c = db.conn()
    c.execute("UPDATE users SET dm=0")
    for pk, v in dm_map.items():
        c.execute("UPDATE users SET dm=? WHERE pk=?", (v, pk))
    c.execute("UPDATE users SET score=likes+comments+story_views+dm")
    c.commit()
    print(f"Concluído: {fetched} threads, {len(dm_map)} pessoas com DM")


def refresh_lists() -> None:
    """Sync leve: só atualiza followers/following e as flags de relação (sem analisar interações)."""
    db.init()
    started = time.time()
    try:
        cl = get_client()
        _progress(state="running", step="session", msg="Validando sessão…")
        me = cl.user_id or cl.account_info().pk

        _progress(state="running", step="lists", msg="Baixando seguidores…")
        followers = {int(k): v for k, v in cl.user_followers(me).items()}
        _progress(state="running", step="lists", msg="Baixando quem você segue…")
        following = {int(k): v for k, v in cl.user_following(me).items()}

        _progress(state="running", step="save", msg="Atualizando relações…")
        now = datetime.now().isoformat(timespec="seconds")
        c = db.conn()
        existing = {r["pk"] for r in c.execute("SELECT pk FROM users")}
        for pk, u in following.items():
            follows_me = 1 if pk in followers else 0
            if pk in existing:
                c.execute(
                    """UPDATE users SET username=?, full_name=?, profile_pic_url=?,
                                       follows_me=?, i_follow=1, is_mutual=?, unfollowed_at=NULL, updated_at=?
                       WHERE pk=?""",
                    (u.username, u.full_name or "", str(u.profile_pic_url or ""), follows_me, follows_me, now, pk),
                )
            else:
                db.upsert_user({"pk": pk, "username": u.username, "full_name": u.full_name or "",
                                "profile_pic_url": str(u.profile_pic_url or ""), "follows_me": follows_me,
                                "i_follow": 1, "is_mutual": follows_me, "likes": 0, "comments": 0,
                                "story_views": 0, "dm": 0, "score": 0, "updated_at": now})
        # quem sumiu do following (unfollow fora do app)
        for row in c.execute("SELECT pk FROM users WHERE i_follow=1 AND unfollowed_at IS NULL").fetchall():
            if row["pk"] not in following:
                c.execute("UPDATE users SET i_follow=0, is_mutual=0, unfollowed_at=? WHERE pk=?", (now, row["pk"]))
        c.commit()

        st = db.stats()
        _progress(state="done", msg="Listas atualizadas", elapsed=round(time.time() - started),
                  not_following_back=st["not_following_back"])
        db.set_setting("last_sync", now)
    except Exception as e:
        traceback.print_exc()
        _progress(state="error", msg=f"{type(e).__name__}: {e}")


def run_sync() -> None:
    db.init()
    started = time.time()
    try:
        cl = get_client()
        _progress(state="running", step="session", msg="Validando sessão…")
        me = cl.user_id or cl.account_info().pk

        _progress(state="running", step="lists", msg="Baixando seguidores…")
        followers = {int(k): v for k, v in cl.user_followers(me).items()}
        _progress(state="running", step="lists", msg="Baixando quem você segue…")
        following = {int(k): v for k, v in cl.user_following(me).items()}

        scores: dict[int, dict] = {}

        def touch(pk, username="", full_name="", pic=""):
            s = scores.setdefault(pk, {"username": username, "full_name": full_name, "profile_pic_url": pic,
                                       "likes": 0, "comments": 0, "story_views": 0, "dm": 0})
            if username:
                s["username"], s["full_name"], s["profile_pic_url"] = username, full_name, pic
            return s

        # posts: likes e comentários
        _progress(state="running", step="media", msg="Baixando seus posts…", done=0, total=MEDIA_LIMIT)
        medias = cl.user_medias(me, amount=MEDIA_LIMIT)
        for i, m in enumerate(medias):
            _progress(state="running", step="media", done=i + 1, total=len(medias),
                      msg=f"Post {i + 1}/{len(medias)} — curtidas")
            try:
                for u in cl.media_likers(str(m.pk)):
                    touch(int(u.pk), u.username, u.full_name or "", str(u.profile_pic_url or ""))["likes"] += W_LIKE
            except Exception:
                pass
            try:
                for c in cl.media_comments(str(m.pk), amount=0):
                    u = c.user
                    touch(int(u.pk), u.username, u.full_name or "", str(u.profile_pic_url or ""))["comments"] += W_COMMENT
            except Exception:
                pass

        # stories ativos: viewers (e likes, se vierem)
        try:
            stories = cl.user_stories(me)
        except Exception:
            stories = []
        for i, st in enumerate(stories):
            _progress(state="running", step="stories", done=i + 1, total=len(stories),
                      msg=f"Story {i + 1}/{len(stories)}")
            try:
                for v in cl.story_viewers(st.pk):
                    s = touch(int(v.pk), v.username or "", v.full_name or "", str(v.profile_pic_url or ""))
                    s["story_views"] += W_STORY + (1 if getattr(v, "has_liked", False) else 0)
            except Exception:
                pass

        # DMs: threads com atividade no último ano
        _progress(state="running", step="dm", msg="Analisando threads de DM…")
        try:
            _collect_dm_scores(cl, touch)
        except Exception:
            pass

        # grava: universo = todo mundo que eu sigo
        _progress(state="running", step="save", msg="Gravando ranking…")
        now = datetime.now().isoformat(timespec="seconds")
        for pk, u in following.items():
            s = scores.get(pk, {})
            follows_me = 1 if pk in followers else 0
            row = {
                "pk": pk,
                "username": u.username,
                "full_name": u.full_name or "",
                "profile_pic_url": str(u.profile_pic_url or ""),
                "follows_me": follows_me,
                "i_follow": 1,
                "is_mutual": follows_me,
                "likes": s.get("likes", 0),
                "comments": s.get("comments", 0),
                "story_views": s.get("story_views", 0),
                "dm": s.get("dm", 0),
                "updated_at": now,
            }
            row["score"] = row["likes"] + row["comments"] + row["story_views"] + row["dm"]
            db.upsert_user(row)
        # quem não aparece mais em following mas consta como i_follow=1 (unfollow fora do app)
        for row in db.conn().execute("SELECT pk FROM users WHERE i_follow=1 AND unfollowed_at IS NULL").fetchall():
            if row["pk"] not in following:
                db.conn().execute("UPDATE users SET i_follow=0, is_mutual=0, unfollowed_at=? WHERE pk=?",
                                  (now, row["pk"]))
        db.conn().commit()

        stats = db.stats()
        _progress(state="done", msg="Sincronização concluída", elapsed=round(time.time() - started),
                  **{k: stats[k] for k in ("total_following", "mutuals_pending", "not_following_back")})
        db.set_setting("last_sync", now)
    except Exception as e:
        traceback.print_exc()
        _progress(state="error", msg=f"{type(e).__name__}: {e}")
