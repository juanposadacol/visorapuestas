@echo off
REM Genera dist\VisorUnder\VisorUnder.exe  (requisito 2, fase 12)
REM Ejecutar desde la carpeta del proyecto con el entorno virtual activado.

setlocal
echo === Instalando dependencias de compilacion ===
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt || goto :error

echo.
echo === Ejecutando los tests antes de empaquetar ===
python -m pytest || goto :error

echo.
echo === Generando el ejecutable ===
python -m PyInstaller visorunder.spec --noconfirm || goto :error

echo.
echo === LISTO ===
echo El programa esta en:  dist\VisorUnder\VisorUnder.exe
echo Copia la carpeta dist\VisorUnder completa si quieres llevarlo a otro equipo.
goto :end

:error
echo.
echo *** Fallo la generacion. Revisa los mensajes anteriores. ***
exit /b 1

:end
endlocal
