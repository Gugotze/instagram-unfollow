import json
from pathlib import Path

from instagrapi import Client

DATA_DIR = Path(__file__).parent / "data"
COOKIES_FILE = DATA_DIR / "cookies.json"
SESSION_FILE = DATA_DIR / "session.json"


def has_session() -> bool:
    return COOKIES_FILE.exists() and SESSION_FILE.exists()


def get_sessionid() -> str | None:
    if not COOKIES_FILE.exists():
        return None
    try:
        return json.loads(COOKIES_FILE.read_text()).get("sessionid")
    except Exception:
        return None


def get_client() -> Client:
    sessionid = get_sessionid()
    if not sessionid:
        raise RuntimeError("Sem sessão. Rode `python login.py` primeiro.")
    cl = Client()
    cl.delay_range = [1, 3]  # pausa aleatória entre requests (mais humano)
    if SESSION_FILE.exists():
        cl.load_settings(SESSION_FILE)
    cl.login_by_sessionid(sessionid)
    cl.dump_settings(SESSION_FILE)
    return cl


def save_cookies(cookies: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    COOKIES_FILE.write_text(json.dumps(cookies, indent=2))
