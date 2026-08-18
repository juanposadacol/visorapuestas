@echo off
REM Arranque rapido en Windows sin generar el .exe
setlocal
if not exist .venv (
    echo Creando entorno virtual...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)
python run.py %*
endlocal
