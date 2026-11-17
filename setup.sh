#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Criando ambiente virtual (.venv)…"
python3 -m venv .venv
PY=.venv/bin/python

echo "==> Instalando dependências…"
$PY -m pip install --upgrade pip -q
$PY -m pip install -r requirements.txt

echo "==> Baixando Chromium do Playwright (login via navegador)…"
$PY -m playwright install chromium

cat <<'EOF'

Pronto! Próximos passos:

  1) Suba o painel:   .venv/bin/uvicorn app:app --port 8777
  2) Abra:            http://localhost:8777
  3) Conecte a conta: cole seu sessionid na página
     — ou rode .venv/bin/python login.py pra login assistido —

EOF
