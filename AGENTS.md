# Instagram_Unfollow

Ferramenta local para avaliar mutuals do Instagram por interação e dar unfollow em ritmo humano.

## Rodar

- Login (1x, abre Chrome): `.venv/bin/python login.py`
- Dashboard + worker: `.venv/bin/uvicorn app:app --port 8777` → http://localhost:8777
- Sincronizar sozinho: `.venv/bin/python -c "import sync; sync.run_sync()"`

## Estrutura

- `login.py` — captura cookies via Playwright → `data/accounts/<pk>/cookies.json` + `session.json`
- `insta.py` — client instagrapi (login por sessionid, delay_range 1-3s). Multi-conta: `data/current` guarda o pk ativo; `set_account()`, `logout()` (para worker, apaga sessão+chrome-profile, mantém DB), `migrate_legacy()`
- `sync.py` — followers/following + likes/comentários em posts, viewers/likes de stories, threads de DM → score em SQLite. `refresh_lists()` é a versão leve: só baixa followers/following e atualiza flags de relação (sem mexer em scores)
- `worker.py` — thread de unfollow: lotes 8-12, pausa 4.5-6.5min, teto settings.daily_cap (máx 1600 via API), pausa 23h-8h, auto-retomada após bloqueio. `settings.worker_target` = "mutuals" (default, score≤max_score) ou "nonfollowers" (limpeza da aba "Não te seguem", ignora score; volta pra mutuals quando a fila zera)
- `app.py` — FastAPI + `static/index.html`
- Dados: `data/accounts/<pk>/unfollow.db` por conta (users, settings, unfollow_log)

## Pesos do score

like +1, comment +2, story view +1 (+1 se liked), DM thread +3 (+2 se ativa em 45 dias) — só threads com atividade no último ano (DM_RANGE_DAYS).

`sync.rescore_dm()` refaz só o componente DM sem sync completo.
