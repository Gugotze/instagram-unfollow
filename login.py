"""Login único: abre um Chrome, você loga no Instagram, e a sessão é capturada.

Depois disso nenhum navegador é necessário — tudo roda via API.
"""
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from insta import PROFILE_DIR, cookies_path, save_cookies, session_path, set_account


def main() -> None:
    print("Abrindo o navegador...")
    print("1) Faça login no Instagram na janela que abrir (com 2FA se tiver).")
    print("2) Assim que aparecer seu feed, a sessão será capturada automaticamente.\n")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            no_viewport=True,
            locale="pt-BR",
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.instagram.com/", wait_until="domcontentloaded")

        sessionid = None
        cookies_map: dict[str, str] = {}
        print("Aguardando login", end="", flush=True)
        for _ in range(600):  # até 10 min
            time.sleep(1)
            print(".", end="", flush=True)
            try:
                cookies = ctx.cookies("https://www.instagram.com")
                cookies_map = {c["name"]: c["value"] for c in cookies}
                sessionid = cookies_map.get("sessionid")
                if sessionid and "login" not in page.url:
                    break
            except Exception:
                pass
        print()

        if not sessionid:
            ctx.close()
            sys.exit("Não detectei sessão. Rode `python login.py` de novo.")

        # valida a sessão via API e salva o device fingerprint
        from instagrapi import Client

        cl = Client()
        cl.login_by_sessionid(sessionid)
        info = cl.account_info()
        set_account(info.pk)
        cl.dump_settings(session_path())

        keep = {k: cookies_map.get(k) for k in ("sessionid", "csrftoken", "ds_user_id", "mid", "ig_did") if cookies_map.get(k)}
        keep["sessionid"] = sessionid
        keep["username"] = info.username
        save_cookies(keep)

        print(f"\nLogado como @{info.username} (pk {info.pk}).")
        print(f"Sessão salva em {cookies_path()}. Pode fechar o navegador.")
        ctx.close()

if __name__ == "__main__":
    main()
