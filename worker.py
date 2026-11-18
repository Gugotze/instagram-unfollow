"""Worker de unfollow: lotes de ~10, pausa ~5 min, teto diário, pausa noturna, auto-retomada."""
import json
import random
import threading
import time
from datetime import datetime, timedelta

import db
import insta
from insta import get_client

BATCH_RANGE = (8, 12)
COOLDOWN_RANGE = (270, 390)   # ~5 min entre lotes
MICRO_RANGE = (3, 8)          # entre unfollows dentro do lote
NIGHT_START = 23              # pausa entre 23h e 08h
NIGHT_END = 8
DEFAULT_CAP = 150

_state = {
    "running": False,
    "mode": "idle",           # idle | working | cooldown | night_pause | capped | blocked | done | error
    "msg": "",
    "next_action_at": None,
    "today": 0,
    "done_batch": 0,
    "thread": None,
}
_lock = threading.Lock()


def _save() -> None:
    s = {k: v for k, v in _state.items() if k != "thread"}
    db.set_setting("worker_state", json.dumps(s))


def status() -> dict:
    with _lock:
        s = {k: v for k, v in _state.items() if k != "thread"}
    s["today"] = db.unfollowed_today()
    s["cap"] = int(db.get_setting("daily_cap", str(DEFAULT_CAP)))
    s["max_score"] = float(db.get_setting("max_score", "0") or 0)
    s["target"] = db.get_setting("worker_target", "mutuals") or "mutuals"
    return s


def start() -> dict:
    with _lock:
        if _state["running"]:
            pass
        else:
            _state.update(running=True, mode="working", msg="Iniciando…", next_action_at=None)
            t = threading.Thread(target=_loop, daemon=True, name="unfollow-worker")
            _state["thread"] = t
            t.start()
            db.set_setting("worker_desired", "1")
    _save()
    return status()


def stop() -> dict:
    with _lock:
        _state.update(running=False, mode="idle", msg="Pausado pelo usuário", next_action_at=None)
    db.set_setting("worker_desired", "0")
    _save()
    return status()


def resume_if_desired() -> None:
    """No boot do app: se o worker estava ligado, religa."""
    if db.get_setting("worker_desired") == "1":
        start()


def _night_bounds() -> tuple[int, int]:
    s = int(db.get_setting("night_start", str(NIGHT_START)) or NIGHT_START)
    e = int(db.get_setting("night_end", str(NIGHT_END)) or NIGHT_END)
    return s, e


def _is_night(now: datetime) -> bool:
    s, e = _night_bounds()
    return now.hour >= s or now.hour < e


def _next_morning(now: datetime) -> datetime:
    _, e = _night_bounds()
    base = now.replace(hour=e, minute=0, second=0, microsecond=0)
    while base <= now:
        base += timedelta(days=1)
    return base


def _blocked_reason(e: Exception) -> str | None:
    name = type(e).__name__
    if name in {"FeedbackRequired", "ChallengeRequired", "PleaseWaitFewMinutes", "RateLimitError"}:
        return name
    txt = str(e).lower()
    if any(k in txt for k in ("feedback_required", "try again later", "we restrict",
                              "challenge_required", "few minutes", "rate limit")):
        return name or "Blocked"
    return None


def _sleep_while(resume_at: datetime) -> None:
    while _state["running"] and datetime.now() < resume_at:
        time.sleep(min(60, max(1, (resume_at - datetime.now()).total_seconds())))


def _loop() -> None:
    db.use_account(insta.current_account())
    try:
        cl = get_client()
    except Exception as e:
        _state.update(running=False, mode="error", msg=f"Sessão inválida: {e}")
        db.set_setting("worker_desired", "0")
        _save()
        return

    while _state["running"]:
        now = datetime.now()

        if _is_night(now):
            wake = _next_morning(now)
            _state.update(mode="night_pause", msg=f"Pausa noturna até {wake:%H:%M}",
                          next_action_at=wake.isoformat(timespec="seconds"))
            _save()
            _sleep_while(wake)
            continue

        cap = int(db.get_setting("daily_cap", str(DEFAULT_CAP)))
        today = db.unfollowed_today()
        if today >= cap:
            wake = _next_morning(now)
            _state.update(mode="capped", msg=f"Teto de {cap}/dia atingido ({today}). Retomo {wake:%d/%m %H:%M}.",
                          next_action_at=wake.isoformat(timespec="seconds"))
            _save()
            _sleep_while(wake)
            continue

        max_score = float(db.get_setting("max_score", "0") or 0)
        target = db.get_setting("worker_target", "mutuals") or "mutuals"
        cands = db.next_candidates(min(random.randint(*BATCH_RANGE), cap - today), max_score, target)
        if not cands:
            msg = ("Limpeza de não-seguidores concluída — zerou a fila." if target == "nonfollowers"
                   else f"Fila vazia — todo mundo com score ≤ {max_score:g} foi processado.")
            db.set_setting("worker_target", "mutuals")
            _state.update(running=False, mode="done", msg=msg)
            db.set_setting("worker_desired", "0")
            _save()
            break

        _state.update(mode="working", msg=f"Unfollow em lote de {len(cands)}…",
                      next_action_at=None, done_batch=0)
        _save()

        resume_at = None
        for c in cands:
            if not _state["running"] or _is_night(datetime.now()):
                break
            if db.unfollowed_today() >= int(db.get_setting("daily_cap", str(DEFAULT_CAP))):
                break
            try:
                cl.user_unfollow(str(c["pk"]))
                db.mark_unfollowed(c["pk"], c["username"], True)
                _state["done_batch"] += 1
                _state["today"] = db.unfollowed_today()
                _save()
            except Exception as e:
                reason = _blocked_reason(e)
                db.mark_unfollowed(c["pk"], c["username"], False, f"{type(e).__name__}: {e}")
                if reason:
                    resume_at = _next_morning(datetime.now())
                    _state.update(mode="blocked",
                                  msg=f"Instagram sinalizou limite ({reason}). Pausado até {resume_at:%d/%m %H:%M}.",
                                  next_action_at=resume_at.isoformat(timespec="seconds"))
                    _save()
                    break
                if type(e).__name__ == "LoginRequired":
                    _state.update(running=False, mode="error", msg="Sessão expirou — rode login.py de novo.")
                    db.set_setting("worker_desired", "0")
                    _save()
                    return
            time.sleep(random.uniform(*MICRO_RANGE))

        if resume_at:
            _sleep_while(resume_at)
            continue

        if not _state["running"]:
            break
        cooldown = random.uniform(*COOLDOWN_RANGE)
        _state.update(mode="cooldown", msg="Pausa entre lotes",
                      next_action_at=(datetime.now() + timedelta(seconds=cooldown)).isoformat(timespec="seconds"))
        _save()
        _sleep_while(datetime.now() + timedelta(seconds=cooldown))

    _save()
