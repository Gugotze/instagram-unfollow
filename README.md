# IG Cleanup — Unfollow

Ferramenta local pra limpar seu "seguindo" no Instagram: pontua cada pessoa pela
interação real com você (curtidas, comentários, visualizações de story, DMs) e
remove em ritmo humano, começando por quem menos interage.

> ⚠️ **Aviso:** automação viola os Termos de Uso do Instagram. O app já limita o
> ritmo e pausa sozinho em caso de bloqueio, mas a responsabilidade pela conta é
> sua. Tudo roda 100% na sua máquina — sua sessão nunca sai daqui.

## Requisitos

- **Python 3.10+** — [python.org](https://www.python.org/downloads/) (no Windows,
  marque **"Add python.exe to PATH"** na instalação; no Mac, `brew install python`
  ou o instalador do site)
- ~500 MB de disco livre
- Não precisa criar app no Meta for Developers nem ter Chrome instalado
  (o Playwright baixa o Chromium dele)

## Instalação

**Mac / Linux**

```bash
git clone https://github.com/Gugotze/instagram-unfollow
cd instagram-unfollow
./setup.sh
```

**Windows**

```
git clone https://github.com/Gugotze/instagram-unfollow
cd instagram-unfollow
setup.bat
```

**Manual (qualquer sistema)**

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt          # Windows: .venv\Scripts\pip
.venv/bin/python -m playwright install chromium    # opcional, só pro login assistido
```

## Rodar

```
.venv/bin/uvicorn app:app --port 8777              # Windows: .venv\Scripts\uvicorn
```

Abra **http://localhost:8777**

## Login (uma vez só)

**Opção A — colar `sessionid` (mais simples):** estando logado no
instagram.com, aperte F12 → Application/Armazenamento → Cookies → copie o valor
de `sessionid` e cole no painel "Conectar sua conta" da página.

**Opção B — navegador assistido:**

```
.venv/bin/python login.py                          # Windows: .venv\Scripts\python login.py
```

Abre um Chrome, você entra no Instagram (com 2FA, se tiver) e a sessão é
capturada automaticamente.

## Como usar

1. **Sincronizar** — monta a fila analisando seus posts, stories e DMs.
   Leva alguns minutos na primeira vez.
2. **Proteger** — marque amigos/família na aba "Protegidos"; eles nunca entram
   na fila.
3. **Iniciar** — o worker remove em lotes de 8–12, com ~5 min de pausa entre
   lotes.

**Limites embutidos:** teto diário (padrão 150, ajustável na página até 1600),
pausa noturna 23h–8h, e pausa automática até o dia seguinte se o Instagram
sinalizar bloqueio.

**Score:** like +1 · comentário +2 · story view +1 (+1 se curtiu) · thread de DM
+3 (+2 se ativa em 45 dias). Quanto menor o score, menos a pessoa interage com
você — é por ela que o worker começa.

## Onde ficam seus dados

Tudo em `data/`:

- `cookies.json` + `session.json` — sua sessão do Instagram
- `unfollow.db` — ranking, protegidos e histórico
- `chrome-profile/` — perfil do navegador do login assistido

**Nunca compartilhe a pasta `data/`** — ela é o acesso completo à sua conta.
Pra resetar tudo, apague `data/` e logue de novo.

## Problemas comuns

- **"Sessão expirou" / LoginRequired** → refaça o login (opção A ou B).
- **"bloqueado pelo IG"** → normal em volume alto; o worker retoma sozinho no
  dia seguinte. Se acontecer seguido, baixe o teto diário — insistir pode
  restringir a conta.
- **Sincronizar falha ou trava** → a API privada do Instagram muda sem aviso;
  atualize o instagrapi: `pip install -U instagrapi`.

## Estrutura

| Arquivo | Função |
|---|---|
| `login.py` | captura a sessão via Chrome (Playwright) |
| `insta.py` | client instagrapi (login por `sessionid`) |
| `sync.py` | baixa seguidores/interações e calcula o score |
| `worker.py` | thread de unfollow com ritmo humano |
| `app.py` + `static/` | API FastAPI + dashboard |
| `db.py` | SQLite em `data/unfollow.db` |
