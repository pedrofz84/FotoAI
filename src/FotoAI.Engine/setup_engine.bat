@echo off
setlocal
cd /d "%~dp0"
echo === FotoAI - preparar o motor Python ===

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")

if not exist ".venv\Scripts\python.exe" (
    echo A criar ambiente virtual em .venv ...
    %PY% -m venv .venv || goto :erro
)
set "VPY=.venv\Scripts\python.exe"

"%VPY%" -m pip install --upgrade pip || goto :erro

where nvidia-smi >nul 2>nul
if %errorlevel%==0 (
    echo GPU NVIDIA detetada: a instalar torch com CUDA ...
    "%VPY%" -m pip install torch --index-url https://download.pytorch.org/whl/cu124 || goto :erro
) else (
    echo Sem GPU NVIDIA: a instalar torch para CPU ...
    "%VPY%" -m pip install torch --index-url https://download.pytorch.org/whl/cpu || goto :erro
)

"%VPY%" -m pip install -r requirements.txt || goto :erro

echo.
"%VPY%" -c "import torch, loguru, rawpy, pillow_heif, qdrant_client, sentence_transformers; print('Tudo instalado. GPU CUDA ativa:', torch.cuda.is_available())" || goto :erro
echo.
echo Pronto. Ja podes abrir a app FotoAI.
pause
exit /b 0

:erro
echo.
echo Algo falhou. Ve as mensagens acima.
pause
exit /b 1
