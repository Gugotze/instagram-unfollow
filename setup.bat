@echo off
cd /d "%~dp0"

echo ==^> Criando ambiente virtual (.venv)...
python -m venv .venv
if errorlevel 1 goto nopython

set PY=.venv\Scripts\python.exe

echo ==^> Instalando dependencias...
%PY% -m pip install --upgrade pip -q
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto fail

echo ==^> Baixando Chromium do Playwright (login via navegador)...
%PY% -m playwright install chromium
if errorlevel 1 goto fail

echo.
echo Pronto! Proximos passos:
echo   1) Suba o painel:   .venv\Scripts\uvicorn app:app --port 8777
echo   2) Abra:            http://localhost:8777
echo   3) Conecte a conta: cole seu sessionid na pagina
echo      - ou rode .venv\Scripts\python login.py pra login assistido -
echo.
pause
exit /b 0

:nopython
echo.
echo ERRO: Python nao encontrado.
echo Instale em https://python.org marcando "Add python.exe to PATH".
pause
exit /b 1

:fail
echo.
echo Falhou - veja o erro acima.
pause
exit /b 1
