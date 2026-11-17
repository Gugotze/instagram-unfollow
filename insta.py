import json
import shutil
from pathlib import Path

from instagrapi import Client

DATA_DIR = Path(__file__).parent / "data"
CURRENT_FILE = DATA_DIR / "current"
PROFILE_DIR = DATA_DIR / "chrome-profile"  # compartilhado, limpo no logout


def current_account() -> str | None:
    try:
        v = CURRENT_FILE.read_text().strip()
        return v or None
    except Exception:
        return None


def acct_dir(create: bool = True) -> Path:
    acct = current_account() or "default"
    d = DATA_DIR / "accounts" / acct
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def set_account(pk) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CURRENT_FILE.write_text(str(pk))
    acct_dir().mkdir(parents=True, exist_ok=True)


def cookies_path() -> Path:
    return acct_dir() / "cookies.json"


def session_path() -> Path:
    return acct_dir() / "session.json"


def has_session() -> bool:
    return cookies_path().exists() and session_path().exists()


def get_sessionid() -> str | None:
    p = cookies_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text()).get("sessionid")
    except Exception:
        return None


def current_username() -> str | None:
    try:
        return json.loads(cookies_path().read_text()).get("username")
    except Exception:
        return None


def get_client() -> Client:
    sessionid = get_sessionid()
    if not sessionid:
        raise RuntimeError("Sem sessão. Rode `python login.py` ou conecte pela página.")
    cl = Client()
    cl.delay_range = [1, 3]  # pausa aleatória entre requests (mais humano)
    sp = session_path()
    if sp.exists():
        cl.load_settings(sp)
    cl.login_by_sessionid(sessionid)
    cl.dump_settings(sp)
    return cl


def save_cookies(cookies: dict) -> None:
    acct_dir().mkdir(parents=True, exist_ok=True)
    cookies_path().write_text(json.dumps(cookies, indent=2))


def logout() -> None:
    """Desloga a conta ativa: remove a sessão dela e o perfil do navegador. O banco fica."""
    for p in (cookies_path(), session_path()):
        if p.exists():
            p.unlink()
    if CURRENT_FILE.exists():
        CURRENT_FILE.unlink()
    if PROFILE_DIR.exists():
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)


def migrate_legacy() -> None:
    """Move data/{cookies,session,unfollow.db} antigas para data/accounts/<pk>/."""
    cookies = DATA_DIR / "cookies.json"
    if not cookies.exists() or CURRENT_FILE.exists():
        return
    try:
        pk = str(json.loads(cookies.read_text()).get("ds_user_id") or "")
    except Exception:
        pk = ""
    acct = pk or "conta1"
    dest = DATA_DIR / "accounts" / acct
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("cookies.json", "session.json", "unfollow.db"):
        src = DATA_DIR / name
        if src.exists():
            src.rename(dest / name)
    CURRENT_FILE.write_text(acct)
    print(f"Dados migrados para accounts/{acct}")
