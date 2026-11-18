"""Dashboard local + API. Rode: .venv/bin/uvicorn app:app --port 8777"""
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

import db
import insta
import sync
import worker
from insta import has_session

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Instagram Unfollow")
_sync_lock = threading.Lock()


@app.on_event("startup")
def _startup() -> None:
    insta.migrate_legacy()
    db.init()
    p = sync.get_progress()
    if p and p.get("state") == "running":
        sync._progress(state="cancelled", msg="Interrompido — servidor reiniciado")
    db.set_setting("sync_cancel", "0")
    worker.resume_if_desired()


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
def api_status():
    return {
        "logged_in": has_session(),
        "account": insta.current_username() or insta.current_account(),
        "stats": db.stats(),
        "worker": worker.status(),
        "sync": sync.get_progress(),
        "last_sync": db.get_setting("last_sync"),
    }


QUERIES = {
    "mutuals": """SELECT pk, username, full_name, profile_pic_url, likes, comments, story_views, dm, score, protected
                  FROM users WHERE is_mutual=1 AND unfollowed_at IS NULL ORDER BY protected DESC, score ASC, pk""",
    "nonfollowers": """SELECT pk, username, full_name, profile_pic_url, likes, comments, story_views, dm, score, protected
                       FROM users WHERE i_follow=1 AND follows_me=0 AND unfollowed_at IS NULL
                       ORDER BY score ASC, pk""",
    "protected": """SELECT pk, username, full_name, profile_pic_url, likes, comments, story_views, dm, score, protected
                    FROM users WHERE protected=1 AND unfollowed_at IS NULL ORDER BY username""",
    "history": """SELECT pk, username, full_name, profile_pic_url, unfollowed_at AS score_label, score
                  FROM users WHERE unfollowed_at IS NOT NULL ORDER BY unfollowed_at DESC""",
}


@app.get("/api/ranking")
def api_ranking(tab: str = "mutuals"):
    sql = QUERIES.get(tab, QUERIES["mutuals"])
    rows = [dict(r) for r in db.conn().execute(sql).fetchall()]
    return {"rows": rows}


class ProtectBody(BaseModel):
    protected: bool


class BulkProtectBody(BaseModel):
    protected: bool
    scope: str = "mutuals"   # mutuals | nonfollowers
    op: str = "<="           # <= | >=
    score: float = 0


@app.post("/api/protect/bulk")
def api_protect_bulk(body: BulkProtectBody):
    op = ">=" if body.op == ">=" else "<="
    cond = "is_mutual=1 AND i_follow=1" if body.scope == "mutuals" else "i_follow=1 AND follows_me=0"
    cur = db.conn().execute(
        f"UPDATE users SET protected=? WHERE unfollowed_at IS NULL AND {cond} AND score {op} ?",
        (int(body.protected), body.score),
    )
    db.conn().commit()
    return {"ok": True, "updated": cur.rowcount}


@app.post("/api/protect/{pk}")
def api_protect(pk: int, body: ProtectBody):
    db.conn().execute("UPDATE users SET protected=? WHERE pk=?", (int(body.protected), pk))
    db.conn().commit()
    return {"ok": True}


@app.post("/api/worker/start")
def api_worker_start():
    return worker.start()


@app.post("/api/worker/stop")
def api_worker_stop():
    return worker.stop()


@app.post("/api/sync")
def api_sync():
    p = sync.get_progress()
    if p and p.get("state") == "running":
        return {"ok": False, "msg": "Sincronização já em andamento"}
    db.set_setting("sync_cancel", "0")
    threading.Thread(target=sync.run_sync, daemon=True, name="sync").start()
    return {"ok": True}


@app.post("/api/refresh_lists")
def api_refresh_lists():
    p = sync.get_progress()
    if p and p.get("state") == "running":
        return {"ok": False, "msg": "Sincronização já em andamento"}
    db.set_setting("sync_cancel", "0")
    threading.Thread(target=sync.refresh_lists, daemon=True, name="refresh-lists").start()
    return {"ok": True}


@app.post("/api/sync/cancel")
def api_sync_cancel():
    db.set_setting("sync_cancel", "1")
    return {"ok": True}


@app.post("/api/cleanup/nonfollowers")
def api_cleanup_nonfollowers():
    db.set_setting("worker_target", "nonfollowers")
    return worker.start()


class SessionBody(BaseModel):
    sessionid: str


@app.post("/api/session")
def api_session(body: SessionBody):
    sid = body.sessionid.strip()
    if not sid:
        return {"ok": False, "msg": "sessionid vazio"}
    try:
        from instagrapi import Client
        cl = Client()
        cl.delay_range = [1, 3]
        cl.login_by_sessionid(sid)
        info = cl.account_info()
        insta.set_account(info.pk)
        cl.dump_settings(insta.session_path())
        insta.save_cookies({"sessionid": sid, "ds_user_id": str(info.pk), "username": info.username})
        return {"ok": True, "username": info.username}
    except Exception as e:
        return {"ok": False, "msg": f"{type(e).__name__}: {e}"}


@app.post("/api/logout")
def api_logout():
    db.set_setting("sync_cancel", "1")
    worker.stop()
    insta.logout()
    return {"ok": True}


class CapBody(BaseModel):
    daily_cap: int


@app.post("/api/settings/cap")
def api_cap(body: CapBody):
    db.set_setting("daily_cap", str(max(1, min(1600, body.daily_cap))))
    return {"ok": True}


class ScoreBody(BaseModel):
    max_score: float


@app.post("/api/settings/score")
def api_score(body: ScoreBody):
    db.set_setting("max_score", str(max(0, min(100, body.max_score))))
    return {"ok": True}


@app.get("/api/log")
def api_log(limit: int = 100):
    rows = [dict(r) for r in db.conn().execute(
        "SELECT pk, username, at, ok, error FROM unfollow_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    return {"rows": rows}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8777)
