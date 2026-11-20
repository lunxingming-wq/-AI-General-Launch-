@echo off
setlocal EnableDelayedExpansion

chcp 65001 >nul
title Local LLM Smart Launcher (VRAM/RAM Adaptive Edition)
color 0B

cd /d "%~dp0"
for /d %%C in ("%~dp0cudart-llama-bin-*") do set "PATH=%%~fC;%PATH%"

:: =====================================================
:: Auto-Detect Available Python Environment
:: =====================================================
set "PYTHON="
if exist "%~dp0venv\Scripts\python.exe" set "PYTHON=%~dp0venv\Scripts\python.exe"
if not defined PYTHON if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not defined PYTHON if exist "%~dp0python\python.exe" set "PYTHON=%~dp0python\python.exe"
if not defined PYTHON if exist "%~dp0runtime\python.exe" set "PYTHON=%~dp0runtime\python.exe"
if not defined PYTHON (
    where python.exe >nul 2>nul && (
        for /f "delims=" %%P in ('where python.exe 2^>nul') do (
            echo %%P | findstr /i "WindowsApps" >nul
            if errorlevel 1 (
                "%%P" -c "exit(0)" >nul 2>nul
                if not errorlevel 1 if not defined PYTHON set "PYTHON=%%P"
            )
        )
    )
)
if not defined PYTHON set "PYTHON=python"

:: =====================================================
:: Model Selection Main Menu
:: =====================================================
:SELECT_MODEL
set m_count=0
for /f "usebackq tokens=1,2,3,4,5,6,7,8,9,10,11,12,13 delims=|" %%A in (`""%PYTHON%" "%~dp0model_manager.py" --list" 2^>nul`) do (
    set /a m_count+=1
    set "MODEL_!m_count!=%%B"
    set "MODEL_PATH_!m_count!=%%B"
    set "MODEL_NAME_!m_count!=%%C"
    set "MODEL_SIZE_!m_count!=%%D"
    set "MODEL_OVERSIZED_!m_count!=%%E"
    set "MODEL_HIGH_NGL_!m_count!=%%F"
    set "MODEL_LOW_NGL_!m_count!=%%G"
    set "MODEL_BLOCKS_!m_count!=%%H"
    set "MODEL_REMAIN_HIGH_!m_count!=%%I"
    set "MODEL_REMAIN_LOW_!m_count!=%%J"
    set "MODEL_PURE_RAM_CTX_!m_count!=%%K"
    set "MODEL_PURE_RAM_CTX_LABEL_!m_count!=%%L"
    set "MODEL_REMAIN_RAM_!m_count!=%%M"
)

if !m_count!==0 (
    for /f "usebackq tokens=1,2 delims=|" %%A in (`powershell -NoProfile -Command "Get-ChildItem models\*.gguf -ErrorAction SilentlyContinue | Where-Object { $_.Name -notmatch 'mmproj' } | ForEach-Object { '{0}|{1:N2} GB' -f $_.Name, ($_.Length / 1GB) }" 2^>nul`) do (
        set /a m_count+=1
        set "MODEL_!m_count!=%~dp0models\%%A"
        set "MODEL_PATH_!m_count!=%~dp0models\%%A"
        set "MODEL_NAME_!m_count!=[Local] %%A"
        set "MODEL_SIZE_!m_count!=%%B"
        set "MODEL_OVERSIZED_!m_count!=0"
        set "MODEL_HIGH_NGL_!m_count!=28"
        set "MODEL_LOW_NGL_!m_count!=12"
        set "MODEL_BLOCKS_!m_count!=32"
        set "MODEL_REMAIN_HIGH_!m_count!=4"
        set "MODEL_REMAIN_LOW_!m_count!=20"
        set "MODEL_PURE_RAM_CTX_!m_count!=49152"
        set "MODEL_PURE_RAM_CTX_LABEL_!m_count!=48K"
        set "MODEL_REMAIN_RAM_!m_count!=1.8"
    )
)

if !m_count!==0 (
    for %%F in (models\*.gguf) do (
        echo %%~nxF | find /I "mmproj" >nul
        if errorlevel 1 (
            set /a m_count+=1
            set "MODEL_!m_count!=%~dp0models\%%~nxF"
            set "MODEL_PATH_!m_count!=%~dp0models\%%~nxF"
            set "MODEL_NAME_!m_count!=[Local] %%~nxF"
            set "MODEL_SIZE_!m_count!=%%~zF B"
            set "MODEL_OVERSIZED_!m_count!=0"
            set "MODEL_HIGH_NGL_!m_count!=28"
            set "MODEL_LOW_NGL_!m_count!=12"
            set "MODEL_BLOCKS_!m_count!=32"
            set "MODEL_REMAIN_HIGH_!m_count!=4"
            set "MODEL_REMAIN_LOW_!m_count!=20"
            set "MODEL_PURE_RAM_CTX_!m_count!=49152"
            set "MODEL_PURE_RAM_CTX_LABEL_!m_count!=48K"
            set "MODEL_REMAIN_RAM_!m_count!=1.8"
        )
    )
)

if !m_count!==0 (
    cls
    echo [Error] No GGUF model files found in "models\" or "model_dirs.txt"!
    echo         Please place .gguf models in "models\" or add paths in "model_dirs.txt".
    echo.
    echo  [F] Install / Update llama-server ^& CUDA runtime (auto-detect hardware)
    echo  [0] Exit
    echo.
    set "empty_choice="
    set /p empty_choice=Select option (default 0): 
    if /I "!empty_choice!"=="F" (
        cls
        "%PYTHON%" "%~dp0llama_fetcher.py" menu
        echo.
        pause
        goto SELECT_MODEL
    )
    exit /b 0
)

cls
echo ============================================================
echo                  Local LLM - Model Selection
echo ============================================================
for /L %%I in (1,1,!m_count!) do (
    echo  [%%I] !MODEL_NAME_%%I! ^(!MODEL_SIZE_%%I!^)
)
echo ------------------------------------------------------------
echo  [F] Install / Update llama-server ^& CUDA runtime (auto-detect hardware)
echo  [0] Exit
echo ============================================================
echo.
set "m_choice="
set /p m_choice=Select a model or action (Enter for [1]): 

if defined m_choice set "m_choice=!m_choice: =!"
if "%m_choice%"=="" set m_choice=1
if /I "!m_choice!"=="F" (
    cls
    "%PYTHON%" "%~dp0llama_fetcher.py" menu
    echo.
    pause
    goto SELECT_MODEL
)
if "%m_choice%"=="0" (
    "%PYTHON%" "%~dp0memory_optimizer.py" --restore >nul 2>nul
    exit /b 0
)

if not defined MODEL_%m_choice% (
    echo Invalid selection, press any key to choose again...
    pause >nul
    goto SELECT_MODEL
)

set "MODEL=!MODEL_PATH_%m_choice%!"
set "MODEL_NAME=!MODEL_NAME_%m_choice%!"
set "MODEL_SIZE=!MODEL_SIZE_%m_choice%!"
set "IS_OVERSIZED=!MODEL_OVERSIZED_%m_choice%!"
set "HIGH_NGL=!MODEL_HIGH_NGL_%m_choice%!"
set "LOW_NGL=!MODEL_LOW_NGL_%m_choice%!"
set "BLOCKS=!MODEL_BLOCKS_%m_choice%!"
set "REMAIN_HIGH=!MODEL_REMAIN_HIGH_%m_choice%!"
set "REMAIN_LOW=!MODEL_REMAIN_LOW_%m_choice%!"
set "PURE_RAM_CTX=!MODEL_PURE_RAM_CTX_%m_choice%!"
set "PURE_RAM_CTX_LABEL=!MODEL_PURE_RAM_CTX_LABEL_%m_choice%!"
set "REMAIN_RAM=!MODEL_REMAIN_RAM_%m_choice%!"

:: Auto-detect matching multimodal vision projector (mmproj)
set "MMPROJ="
for %%D in ("!MODEL!") do set "MODEL_DIR=%%~dpD"
for %%F in ("%~dp0models\*mmproj*.gguf" "!MODEL_DIR!*mmproj*.gguf") do (
    if exist "%%~fF" set "MMPROJ=%%~fF"
)

goto SELECT_OPTIMIZE

:: =====================================================
:: VRAM & RAM Optimization Menu (Right After Model Selection)
:: =====================================================
:SELECT_OPTIMIZE
cls
"%PYTHON%" "%~dp0memory_optimizer.py" --menu "!MODEL_NAME!" "!MODEL_SIZE!"

echo.
set "opt_choice="
set /p opt_choice=Select optimization mode (Enter for [1]): 

if defined opt_choice set "opt_choice=!opt_choice: =!"
if "!opt_choice!"=="0" (
    "%PYTHON%" "%~dp0memory_optimizer.py" --restore >nul 2>nul
    set "m_choice="
    goto SELECT_MODEL
)
if "!opt_choice!"=="" set "opt_choice=1"

if not "!opt_choice!"=="1" if not "!opt_choice!"=="2" if not "!opt_choice!"=="3" if not "!opt_choice!"=="4" (
    echo [Tip] Invalid input. Enter 1-4, or 0 to return to model selection.
    timeout /t 2 >nul 2>nul
    goto SELECT_OPTIMIZE
)

if "!opt_choice!"=="4" (
    echo.
    echo [Info] Keeping current memory/VRAM state unchanged...
    timeout /t 1 >nul 2>nul
    goto SELECT_STRATEGY
)

"%PYTHON%" "%~dp0memory_optimizer.py" --optimize !opt_choice!
timeout /t 1 >nul 2>nul
goto SELECT_STRATEGY

:: =====================================================
:: Execution Strategy & VRAM Allocation Menu
:: =====================================================
:SELECT_STRATEGY
cls
echo ============================================================
echo Selected Model: !MODEL_NAME! (!MODEL_SIZE!)
if defined MMPROJ echo Vision Component: !MMPROJ!
echo ============================================================
echo.

if "!IS_OVERSIZED!"=="1" goto OVERSIZED_MENU

:: -----------------------------------------------------
:: Standard Model Strategies (e.g., 8B / 9B / 12B)
:: -----------------------------------------------------
echo Choose a runtime strategy (with usage notes and resource estimates):
echo.
echo [1] Full-Speed VRAM Mode (Model ^& Context fully on GPU)
echo     - Best for: Primary deep sessions and long-form writing. Fastest speed.
echo     - Resources: Maximizes VRAM usage - minimal reserve - auto-maximized context
echo.
echo [2] Model in VRAM + KV Cache in RAM (Long-Context Split Mode)
echo     - Best for: Full GPU layer compute with 32K-128K context and zero VRAM OOM.
echo     - Resources: Model weights in VRAM - Context (KV Cache) stored in system RAM
echo.
echo [3] Balanced Multitask Mode (Main Layers in VRAM)
echo     - Best for: Smooth daily chat alongside light background apps. Stable.
echo     - Resources: Reserves ~4GB VRAM for system/apps - ~32K adaptive context
echo.
echo [4] Custom VRAM Cap Mode (Limit VRAM / Co-run Heavy Apps)
echo     - Best for: Running alongside ComfyUI, 3D games, or GPU workloads.
echo     - Resources: Strict VRAM cap (any GB value) - extra layers ^& KV in RAM
echo.
echo [5] Pure RAM Compute Mode (0 VRAM Used)
echo     - Best for: Keeping 100%% of GPU VRAM free for other heavy workloads.
echo     - Resources: 0 VRAM used - deep system RAM usage [keeps 2.0G safety buffer]
echo.
echo ------------------------------------------------------------
echo [0] Back to VRAM/RAM Optimization
echo ============================================================
echo.
set "s_choice="
set /p s_choice=Select strategy (default 1): 

if defined s_choice set "s_choice=!s_choice: =!"
if "!s_choice!"=="0" (
    set "opt_choice="
    goto SELECT_OPTIMIZE
)
if "%s_choice%"=="" set s_choice=1
if "%s_choice%"=="4" goto CUSTOM_VRAM_MENU

goto APPLY_STRATEGY

:: -----------------------------------------------------
:: Large / Oversized Model Strategies (e.g., 26B / 27B / 31B / 35B)
:: -----------------------------------------------------
:OVERSIZED_MENU
echo Large model detected (!MODEL_SIZE!). Available hybrid VRAM/RAM strategies:
echo.
echo [1] Max GPU Acceleration (Partial Layers + KV Cache in VRAM)
echo     - Best for: Large models prioritizing maximum tokens/sec speed.
echo     - Resources: Reserves 2.0G VRAM for context - rest in VRAM - overflow in RAM
echo.
echo [2] Model in VRAM + KV Cache in RAM (Recommended for Long Context)
echo     - Best for: Packing maximum model layers into VRAM while holding long KV in RAM.
echo     - Resources: Fills VRAM with model layers (no KV) - full context in system RAM
echo.
echo [3] Balanced Hybrid Mode (Strict VRAM Limit)
echo     - Best for: Large model inference while keeping medium background apps smooth.
echo     - Resources: Caps VRAM around ~6GB - heavy RAM usage - adaptive context
echo.
echo [4] Custom VRAM Cap Mode (Limit VRAM / Co-run Heavy Apps)
echo     - Best for: Running alongside ComfyUI, 3D games, or GPU workloads.
echo     - Resources: Strict VRAM cap (any GB value) - extra layers ^& KV in RAM
echo.
echo [5] Pure RAM Extreme Mode (0 VRAM Used)
echo     - Best for: Keeping 100%% of GPU VRAM free for other heavy workloads.
echo     - Resources: 0 VRAM used - maximum RAM usage [keeps 2.0G safety buffer]
echo.
echo ------------------------------------------------------------
echo [0] Back to VRAM/RAM Optimization
echo ============================================================
echo.
set "s_choice="
set /p s_choice=Select strategy (recommended 1): 

if defined s_choice set "s_choice=!s_choice: =!"
if "!s_choice!"=="0" (
    set "opt_choice="
    goto SELECT_OPTIMIZE
)
if "%s_choice%"=="" set s_choice=1
if "%s_choice%"=="4" goto CUSTOM_VRAM_MENU

goto APPLY_STRATEGY

:: -----------------------------------------------------
:: Custom VRAM Submenu
:: -----------------------------------------------------
:CUSTOM_VRAM_MENU
cls
echo ============================================================
echo Current Model: !MODEL_NAME! (!MODEL_SIZE!)
echo Select target VRAM budget for model layers (auto-offloads rest):
echo ============================================================
echo.
echo  * Architecture: Context (KV Cache) runs in system RAM (-nkvo) for all options
echo  * Constant VRAM: GPU footprint stays flat across long chats (safe for games/ComfyUI)
echo.
echo [1] Ultra-Low VRAM (~2.5 GB VRAM - KV in RAM - leaves maximum headroom)
echo [2] Low-Medium VRAM (~4.0 GB VRAM - KV in RAM - good for ComfyUI / gaming)
echo [3] Balanced VRAM  (~6.0 GB VRAM - KV in RAM - higher throughput)
echo [4] High VRAM      (~8.0 GB VRAM - KV in RAM - leaves room for OS/light apps)
echo [5] Exact Custom GB (enter any value such as 3.5, 5, 7, 10; KV stays in RAM)
echo.
echo ------------------------------------------------------------
echo [0] Back to Strategy Selection
echo ============================================================
echo.
set "v_choice="
set /p v_choice=Select VRAM preset (default 2, or type GB directly e.g. 5): 

if defined v_choice set "v_choice=!v_choice: =!"
if "%v_choice%"=="0" (
    set "s_choice="
    goto SELECT_STRATEGY
)
if "%v_choice%"=="" set v_choice=2

set "TARGET_VRAM=4.0"
if "%v_choice%"=="1" set "TARGET_VRAM=2.5"
if "%v_choice%"=="2" set "TARGET_VRAM=4.0"
if "%v_choice%"=="3" set "TARGET_VRAM=6.0"
if "%v_choice%"=="4" set "TARGET_VRAM=8.0"
if "%v_choice%"=="5" (
    echo.
    set "input_vram="
    set /p input_vram=Enter target VRAM size in GB (e.g. 3.5, 5, 8, 10; KV stays in RAM): 
    if not defined input_vram set input_vram=4.0
    set "TARGET_VRAM=!input_vram!"
)

if not "%v_choice%"=="1" if not "%v_choice%"=="2" if not "%v_choice%"=="3" if not "%v_choice%"=="4" if not "%v_choice%"=="5" (
    set "TARGET_VRAM=!v_choice!"
)

goto APPLY_STRATEGY

:: -----------------------------------------------------
:: Calculate Layer Offload & Context Plan
:: -----------------------------------------------------
:APPLY_STRATEGY
echo.
echo Calculating optimal layer offload and context capacity...
set "TARGET_VRAM=!TARGET_VRAM!"
if not defined TARGET_VRAM set TARGET_VRAM=0.0
for /f "usebackq tokens=1,2,3,4,5,6,7,8 delims=:" %%A in (`""%PYTHON%" "%~dp0model_manager.py" --calc-strategy "!MODEL!" "!s_choice!" "!IS_OVERSIZED!" "!TARGET_VRAM!" "!opt_choice!"" 2^>nul`) do (
    set "NGL=%%A"
    set "CTX=%%B"
    set "MODE=%%C"
    set "EXTRA_FLAGS=%%D"
    set "REMAIN_LAYERS=%%E"
    set "MODEL_VRAM_EST=%%F"
    set "APPLIED_VRAM=%%G"
    set "TOTAL_BLOCKS=%%H"
)

if not defined NGL set NGL=99
if not defined CTX set CTX=16384
if not defined MODE set MODE=Full-Speed VRAM Mode (Fallback)
if not defined EXTRA_FLAGS set EXTRA_FLAGS=
if "%EXTRA_FLAGS%"=="-" set "EXTRA_FLAGS="
if not defined REMAIN_LAYERS set REMAIN_LAYERS=0
if not defined MODEL_VRAM_EST set MODEL_VRAM_EST=0
if not defined APPLIED_VRAM set APPLIED_VRAM=0
if not defined TOTAL_BLOCKS set TOTAL_BLOCKS=40

echo.
echo ------------------------------------------------------------
echo [Auto Strategy Calculation Complete]
echo  * Run Mode:       !MODE!
echo  * VRAM Budget:    !APPLIED_VRAM! GB
echo  * GPU Layers:     !NGL! / !TOTAL_BLOCKS! layers [~ !MODEL_VRAM_EST! GB VRAM]
echo  * RAM Layers:     !REMAIN_LAYERS! layers
echo  * Context Size:   !CTX! Tokens
echo ------------------------------------------------------------
echo [1] Confirm strategy and continue (Enter for default)
echo [0] Back to re-select strategy
echo ============================================================
echo.
set "strat_confirm="
set /p strat_confirm=Confirm (default 1): 
if defined strat_confirm set "strat_confirm=!strat_confirm: =!"
if "!strat_confirm!"=="0" (
    set "s_choice="
    set "TARGET_VRAM="
    goto SELECT_STRATEGY
)
goto SELECT_TEMPLATE

:: =====================================================
:: Role Preset Selection
:: =====================================================
:SELECT_TEMPLATE
cls
echo ============================================================
echo Selected Model: !MODEL_NAME! (!MODEL_SIZE!)
echo Run Mode:       !MODE!
echo ============================================================
echo.
echo Available Role Presets (* marks currently active role):
echo.

"%PYTHON%" "%~dp0role_manager.py" --list-short 2>nul

echo.
echo ------------------------------------------------------------
echo [N] Native Default Mode (no role injection; ideal for code/translation)
echo [E] Temporary Custom Role (empty line to finish; optional permanent save)
echo [M] Role Preset Manager (Add / Edit / View / Delete / Notepad)
echo [0] Back to Strategy Selection
echo ============================================================
echo.
set "t_choice="
set /p t_choice=Select role number or action (Enter keeps current active role): 

if defined t_choice set "t_choice=!t_choice: =!"
if "!t_choice!"=="0" (
    set "s_choice="
    set "TARGET_VRAM="
    goto SELECT_STRATEGY
)
if /I "!t_choice!"=="N" (
    "%PYTHON%" "%~dp0role_manager.py" --apply-none >nul 2>nul
    goto ROLE_APPLIED
)
if /I "!t_choice!"=="E" (
    "%PYTHON%" "%~dp0role_manager.py" --custom
    if errorlevel 1 goto SELECT_TEMPLATE
    goto ROLE_APPLIED
)
if /I "!t_choice!"=="M" (
    "%PYTHON%" "%~dp0role_manager.py" --manage
    goto SELECT_TEMPLATE
)
if "!t_choice!"=="" (
    "%PYTHON%" "%~dp0role_manager.py" --apply-current >nul 2>nul
    goto ROLE_APPLIED
)

"%PYTHON%" "%~dp0role_manager.py" --apply "!t_choice!" >nul
if errorlevel 1 (
    echo.
    echo [Tip] Invalid input! Enter a valid role number from the list, or N / E / M / 0.
    timeout /t 2 >nul 2>nul
    goto SELECT_TEMPLATE
)

:ROLE_APPLIED
set "ROLE_NAME="
for /f "usebackq delims=" %%R in (`""%PYTHON%" "%~dp0role_manager.py" --current-name" 2^>nul`) do (
    set "ROLE_NAME=%%R"
)
if not defined ROLE_NAME set "ROLE_NAME=Native Default (No Role)"
goto SELECT_LIMIT

:: =====================================================
:: Max Generation Length Selection
:: =====================================================
:SELECT_LIMIT
cls
echo ============================================================
echo Configuration Summary:
echo Model:    !MODEL_NAME! (!MODEL_SIZE!)
echo Strategy: !MODE!
echo Role:     !ROLE_NAME!
echo ============================================================
echo.
echo Select maximum tokens per single response:
echo.
echo [1] Short Response   (~500 words   ^| Limit 1500 Tokens)
echo [2] Medium Response  (~1000 words  ^| Limit 3000 Tokens)
echo [3] Long Response    (~3000 words  ^| Limit 7500 Tokens)
echo [4] Ultra-Long Draft (~5000 words  ^| Limit 12000 Tokens)
echo [5] Unlimited        (Stop at EOS   ^| Set -1)
echo.
echo ------------------------------------------------------------
echo [0] Back to Role Selection
echo ============================================================
echo.
set "limit_choice="
set "N_PREDICT=3000"
set /p limit_choice=Select option (default 2, or type custom token limit): 

if defined limit_choice set "limit_choice=!limit_choice: =!"
if "!limit_choice!"=="0" (
    set "t_choice="
    goto SELECT_TEMPLATE
)

if "!limit_choice!"=="" set "limit_choice=2"
if "!limit_choice!"=="1" set "N_PREDICT=1500"
if "!limit_choice!"=="2" set "N_PREDICT=3000"
if "!limit_choice!"=="3" set "N_PREDICT=7500"
if "!limit_choice!"=="4" set "N_PREDICT=12000"
if "!limit_choice!"=="5" set "N_PREDICT=-1"

if not "!limit_choice!"=="1" if not "!limit_choice!"=="2" if not "!limit_choice!"=="3" if not "!limit_choice!"=="4" if not "!limit_choice!"=="5" (
    set /a test_num=limit_choice 2>nul
    if "!test_num!"=="!limit_choice!" (
        set "N_PREDICT=!limit_choice!"
    ) else (
        set "N_PREDICT=3000"
    )
)
if not defined N_PREDICT set "N_PREDICT=3000"
if "!N_PREDICT!"=="" set "N_PREDICT=3000"
goto START

:START
cls
if not defined N_PREDICT set "N_PREDICT=3000"
if "!N_PREDICT!"=="" set "N_PREDICT=3000"

:: 1. Clean up stale processes and listening ports
taskkill /F /IM llama-server.exe >nul 2>nul
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8080" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>nul
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8081" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>nul
chcp 65001 >nul

:: 1.5 Check if model architecture uses custom Qwen template (non-Qwen uses GGUF built-in template)
set "LLAMA_CUSTOM_TEMPLATE=0"
for /f "usebackq delims=" %%T in (`""%PYTHON%" "%~dp0model_manager.py" --check-template-compat "!MODEL!"" 2^>nul`) do (
    if "%%T"=="USE_CUSTOM" set "LLAMA_CUSTOM_TEMPLATE=1"
)

:: 2. Start background Web & API hub server_core.py (port 8080)
start "" /b "%PYTHON%" "%~dp0server_core.py" > "%~dp0server_core.log" 2>&1

:: 3. Wait up to 3 seconds for port 8080 readiness
set "PORT_ARG=8081"
set "CORE_READY=0"
for /L %%w in (1,1,6) do (
    if "!CORE_READY!"=="0" (
        "%PYTHON%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=1)" >nul 2>nul
        if not errorlevel 1 set "CORE_READY=1"
        if "!CORE_READY!"=="0" ping -n 1 -w 500 127.0.0.1 >nul 2>nul
    )
)

:: Fallback: let llama-server serve port 8080 directly if server_core.py did not come up
if "!CORE_READY!"=="0" (
    echo [Info] Web hub not ready, letting llama-server bind port 8080 directly...
    set "PORT_ARG=8080"
)

:: 4. Print detailed VRAM/RAM allocation summary and access endpoints
"%PYTHON%" "%~dp0model_manager.py" --print-resource-banner "!MODEL!" "!NGL!" "!CTX!" "!EXTRA_FLAGS!" "!MODE!" "!ROLE_NAME!" "!N_PREDICT!" "!TOTAL_BLOCKS!" 2>nul

if not exist "%~dp0llama-server.exe" (
    where llama-server.exe >nul 2>nul || (
        echo [Info] llama-server.exe not found. Running automatic hardware-matched downloader...
        "%PYTHON%" "%~dp0llama_fetcher.py" ensure
        if errorlevel 1 (
            "%PYTHON%" "%~dp0memory_optimizer.py" --restore >nul 2>nul
            pause
            goto SELECT_MODEL
        )
    )
)

set "LLAMA_BIN="
if exist "%~dp0llama-server.exe" set "LLAMA_BIN=%~dp0llama-server.exe"
if not defined LLAMA_BIN (
    where llama-server.exe >nul 2>nul && set "LLAMA_BIN=llama-server.exe"
)
if not defined LLAMA_BIN (
    echo.
    echo [Error] llama-server.exe was not found!
    echo         Choose [F] in the main menu to auto-download llama.cpp + CUDA runtime,
    echo         or manually extract a Windows release into this folder.
    echo.
    "%PYTHON%" "%~dp0memory_optimizer.py" --restore >nul 2>nul
    pause
    goto SELECT_MODEL
)

echo [Loading model weights and starting inference engine, please wait...]
echo.

if "!LLAMA_CUSTOM_TEMPLATE!"=="1" (
    if defined MMPROJ (
        "!LLAMA_BIN!" -m "!MODEL!" --mmproj "!MMPROJ!" --chat-template-file "%~dp0_active_template.jinja" --path "%~dp0web" --fit off -ngl !NGL! -c !CTX! -n !N_PREDICT! -fa on --cont-batching -np 1 --host 127.0.0.1 --port !PORT_ARG! --log-file "%~dp0llama_server.log" !EXTRA_FLAGS!
    ) else (
        "!LLAMA_BIN!" -m "!MODEL!" --chat-template-file "%~dp0_active_template.jinja" --path "%~dp0web" --fit off -ngl !NGL! -c !CTX! -n !N_PREDICT! -fa on --cont-batching -np 1 --host 127.0.0.1 --port !PORT_ARG! --log-file "%~dp0llama_server.log" !EXTRA_FLAGS!
    )
) else (
    echo [Info] Non-Qwen architecture detected; switched automatically to built-in GGUF chat template.
    if defined MMPROJ (
        "!LLAMA_BIN!" -m "!MODEL!" --mmproj "!MMPROJ!" --path "%~dp0web" --fit off -ngl !NGL! -c !CTX! -n !N_PREDICT! -fa on --cont-batching -np 1 --host 127.0.0.1 --port !PORT_ARG! --log-file "%~dp0llama_server.log" !EXTRA_FLAGS!
    ) else (
        "!LLAMA_BIN!" -m "!MODEL!" --path "%~dp0web" --fit off -ngl !NGL! -c !CTX! -n !N_PREDICT! -fa on --cont-batching -np 1 --host 127.0.0.1 --port !PORT_ARG! --log-file "%~dp0llama_server.log" !EXTRA_FLAGS!
    )
)

:AFTER_START
:: Immediately restore paused apps/wallpapers as soon as the model exits
"%PYTHON%" "%~dp0memory_optimizer.py" --restore >nul 2>nul
taskkill /F /IM llama-server.exe >nul 2>nul
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8080" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>nul
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8081" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>nul
chcp 65001 >nul
echo.
echo ============================================================
echo [Info] Model session ended. Background apps and wallpaper restored.
echo ============================================================
echo.
echo [1] Restart current configuration
echo [2] Return to Role Selection
echo [3] Return to Strategy ^& VRAM Configuration
echo [0] Return to Model Selection
echo ============================================================
echo.
set "restart_choice="
set /p restart_choice=Select option (default 1): 

if defined restart_choice set "restart_choice=!restart_choice: =!"
if "%restart_choice%"=="" goto START
if "%restart_choice%"=="1" goto START
if "%restart_choice%"=="2" goto SELECT_TEMPLATE
if "%restart_choice%"=="3" goto SELECT_STRATEGY
if "%restart_choice%"=="0" (
    "%PYTHON%" "%~dp0memory_optimizer.py" --restore >nul 2>nul
    goto SELECT_MODEL
)
"%PYTHON%" "%~dp0memory_optimizer.py" --restore >nul 2>nul
goto SELECT_MODEL
