@echo off
chcp 65001 >nul
title Clasificador de Constancias Academicas
cd /d "%~dp0"

echo ============================================================
echo    Clasificador de Constancias Academicas
echo ============================================================
echo.

rem --- 1. Python ---------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo [X] No se encontro Python. Instalelo desde https://www.python.org/downloads/
    echo     y marque la opcion "Add python.exe to PATH".
    pause
    exit /b 1
)

rem --- 2. Dependencias (solo se instalan si faltan) ----------------
python -c "import pymupdf, rapidocr_onnxruntime, openpyxl, PIL, numpy" >nul 2>&1
if errorlevel 1 (
    echo Instalando dependencias por primera vez, espere unos minutos...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [X] No se pudieron instalar las dependencias.
        pause
        exit /b 1
    )
)

rem --- 3. Ollama / Qwen (opcional) ----------------------------------
curl -s -m 2 http://localhost:11434/api/version >nul 2>&1
if errorlevel 1 (
    if exist "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" (
        echo Iniciando Ollama...
        start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
    ) else (
        where ollama >nul 2>&1 && start "" /min ollama serve
    )
    rem esperar hasta 20 segundos a que responda
    for /l %%i in (1,1,10) do (
        curl -s -m 2 http://localhost:11434/api/version >nul 2>&1 && goto ollama_ok
        timeout /t 2 /nobreak >nul
    )
    echo [!] Ollama no respondio: se clasificara solo con el algoritmo de reglas.
    goto arrancar
)
:ollama_ok
echo Ollama listo.

rem --- 4. Arrancar la app (abre el navegador) -----------------------
:arrancar
echo.
echo La aplicacion se abrira en su navegador.
echo NO cierre esta ventana mientras use la aplicacion (para salir, cierrela o presione Ctrl+C).
echo.
python pdf_organizer.py %*
if errorlevel 1 pause
