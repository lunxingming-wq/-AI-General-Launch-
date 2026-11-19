@echo off
setlocal EnableDelayedExpansion

chcp 936 >nul
title 本地大模型智能启动中心 (显存/内存自适应优化版)
color 0B

cd /d "%~dp0"
if exist "%~dp0cudart-llama-bin-win-cuda-13.3-x64" set "PATH=%~dp0cudart-llama-bin-win-cuda-13.3-x64;%PATH%"

:: =====================================================
:: 自动检测可用 Python 环境
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
:: 模型选择主菜单
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
        set "MODEL_NAME_!m_count!=[本地] %%A"
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
            set "MODEL_NAME_!m_count!=[本地] %%~nxF"
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
    echo [错误] 未在 models 文件夹或 model_dirs.txt 配置的目录中找到任何 GGUF 模型！
echo        请将 .gguf 模型放入 models 文件夹，或在 model_dirs.txt 中添加外部模型路径。
    pause
    exit
)

cls
echo ============================================================
echo                    本地大模型 - 模型选择
echo ============================================================
for /L %%I in (1,1,!m_count!) do (
    echo  [%%I] !MODEL_NAME_%%I! ^(!MODEL_SIZE_%%I!^)
)
echo ------------------------------------------------------------
echo  [0] 退出程序
echo ============================================================
echo.
set "m_choice="
set /p m_choice=请选择模型 (直接回车默认 [1]): 

if defined m_choice set "m_choice=!m_choice: =!"
if "%m_choice%"=="" set m_choice=1
if "%m_choice%"=="0" (
    "%PYTHON%" "%~dp0memory_optimizer.py" --restore >nul 2>nul
    exit /b 0
)

if not defined MODEL_%m_choice% (
    echo 输入无效，请按任意键重新选择...
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

:: 自动检测是否有匹配的视觉组件 (mmproj)
set "MMPROJ="
for %%D in ("!MODEL!") do set "MODEL_DIR=%%~dpD"
for %%F in ("%~dp0models\*mmproj*.gguf" "!MODEL_DIR!*mmproj*.gguf") do (
    if exist "%%~fF" set "MMPROJ=%%~fF"
)

goto SELECT_OPTIMIZE

:: =====================================================
:: 显存与内存深度腾退优化选择 (在模型选定后立即介入)
:: =====================================================
:SELECT_OPTIMIZE
cls
"%PYTHON%" "%~dp0memory_optimizer.py" --menu "!MODEL_NAME!" "!MODEL_SIZE!"

echo.
set "opt_choice="
set /p opt_choice=请选择优化模式 (直接回车默认 [1]): 

if defined opt_choice set "opt_choice=!opt_choice: =!"
if "!opt_choice!"=="0" (
    "%PYTHON%" "%~dp0memory_optimizer.py" --restore >nul 2>nul
    set "m_choice="
    goto SELECT_MODEL
)
if "!opt_choice!"=="" set "opt_choice=1"

if not "!opt_choice!"=="1" if not "!opt_choice!"=="2" if not "!opt_choice!"=="3" if not "!opt_choice!"=="4" (
    echo [提示] 输入无效，请输入数字 1-4，或输入 0 返回模型选择。
    timeout /t 2 >nul 2>nul
    goto SELECT_OPTIMIZE
)

if "!opt_choice!"=="4" (
    echo.
    echo [提示] 保持当前显存内存现状，不进行后台清理...
    timeout /t 1 >nul 2>nul
    goto SELECT_STRATEGY
)

"%PYTHON%" "%~dp0memory_optimizer.py" --optimize !opt_choice!
timeout /t 1 >nul 2>nul
goto SELECT_STRATEGY

:: =====================================================
:: 运行策略与显存选择菜单
:: =====================================================
:SELECT_STRATEGY
cls
echo ============================================================
echo 当前选中模型: !MODEL_NAME! (!MODEL_SIZE!)
if defined MMPROJ echo 关联视觉组件: !MMPROJ!
echo ============================================================
echo.

if "!IS_OVERSIZED!"=="1" goto OVERSIZED_MENU

:: -----------------------------------------------------
:: 普通体量模型策略 (如 8B / 9B / 12B 等)
:: -----------------------------------------------------
echo 请选择适合您当前需求的运行模式 (已列出功能说明与预计占用)：
echo.
echo [1] 极速全显存模式 (模型与上下文全部驻留显存)
echo     - 适用场景: 主力深度使用、长篇创作。推理速度最快。
echo     - 资源占用: 尽可能占满显存 - 预留极少显存 - 上下文长度自适应最大化
echo.
echo [2] 显存泡模型 + 内存跑上下文 (超长上下文分离模式)
echo     - 适用场景: 既要显卡全速推理，又要 32K~128K 超长上下文且绝不爆显存。
echo     - 资源占用: 模型全部装入显存 - 上下文(KV Cache)存入系统物理内存
echo.
echo [3] 均衡多任务模式 (模型主要层驻留显存)
echo     - 适用场景: 日常流畅对话、轻度后台办公。稳定且不易爆显存。
echo     - 资源占用: 显存保留约 4GB 供系统使用 - 上下文长度自适应约 32K
echo.
echo [4] 自定义显存占用模式 (自定义显存分配限制 / 多任务共存)
echo     - 适用场景: 需同时运行大型软件 (如 ComfyUI、3D游戏等)。
echo     - 资源占用: 精确限制显存占用 [支持输入任意大小] - 剩余层与上下文转入内存
echo.
echo [5] 纯内存计算模式 (完全不使用显存)
echo     - 适用场景: 显卡需全力运行其他高负载应用。
echo     - 资源占用: 显存 0 占用 - 物理内存深度占用 [保留 2.0G 防卡顿] - 上下文自适应
echo.
echo ------------------------------------------------------------
echo [0] 返回显存与内存优化选择
echo ============================================================
echo.
set "s_choice="
set /p s_choice=请选择运行策略 (默认 1): 

if defined s_choice set "s_choice=!s_choice: =!"
if "!s_choice!"=="0" (
    set "opt_choice="
    goto SELECT_OPTIMIZE
)
if "%s_choice%"=="" set s_choice=1
if "%s_choice%"=="4" goto CUSTOM_VRAM_MENU

goto APPLY_STRATEGY

:: -----------------------------------------------------
:: 较大体量模型策略 (如 26B / 27B / 31B / 35B 等超显存模型)
:: -----------------------------------------------------
:OVERSIZED_MENU
echo 检测到该模型体量较大 (!MODEL_SIZE!)，已为您提供内存/显存分配策略：
echo.
echo [1] 显卡最大化加速模式 (模型部分入显存 + 上下文入显存)
echo     - 适用场景: 超大模型推理，追求最高单步生成速度。
echo     - 资源占用: 显存预留 2.0G 供上下文 - 其余入显存 - 剩余入内存
echo.
echo [2] 显存泡模型 + 内存跑上下文 (超大模型+超长上下文推荐)
echo     - 适用场景: 充分利用显卡显存装载最多模型层，并利用系统内存承载超长上下文。
echo     - 资源占用: 显存泡满模型层 (不占KV) - 上下文全部存入系统物理内存
echo.
echo [3] 显存内存均衡共存模式 (严格限制显存占用)
echo     - 适用场景: 超大模型推理的同时兼顾中度后台任务。
echo     - 资源占用: 显存控制在约 6GB 以内 - 物理内存深度占用 - 上下文长度自适应
echo.
echo [4] 自定义显存占用模式 (自定义显存分配限制 / 多任务共存)
echo     - 适用场景: 需同时运行大型软件 (如 ComfyUI、3D游戏等)。
echo     - 资源占用: 精确限制显存占用 [支持输入任意大小] - 剩余层与上下文转入内存
echo.
echo [5] 纯内存极限模式 (完全不使用显存)
echo     - 适用场景: 显卡需全力运行其他高负载应用。
echo     - 资源占用: 显存 0 占用 - 物理内存极限占用 [保留 2.0G 防爆] - 上下文长度自适应
echo.
echo ------------------------------------------------------------
echo [0] 返回显存与内存优化选择
echo ============================================================
echo.
set "s_choice="
set /p s_choice=请选择运行策略 (推荐 1): 

if defined s_choice set "s_choice=!s_choice: =!"
if "!s_choice!"=="0" (
    set "opt_choice="
    goto SELECT_OPTIMIZE
)
if "%s_choice%"=="" set s_choice=1
if "%s_choice%"=="4" goto CUSTOM_VRAM_MENU

goto APPLY_STRATEGY

:: -----------------------------------------------------
:: 自定义显存子菜单
:: -----------------------------------------------------
:CUSTOM_VRAM_MENU
cls
echo ============================================================
echo 当前模型: !MODEL_NAME! (!MODEL_SIZE!)
echo 请选择您希望模型占用的显存大小 (系统将根据您的选择自动分层)：
echo ============================================================
echo.
echo  * 架构特点: 所有选项的上下文 (KV Cache) 均已配置跑在系统物理内存中 (-nkvo)
echo  * 显存恒定: 显卡显存恒定不随长对话膨胀，为后台 ComfyUI / 游戏保留安全空间
echo.
echo [1] 极低显存 (占用约 2.5 GB 显存 - 上下文驻留内存 - 预留约 9.5 GB 给 ComfyUI / 游戏)
echo [2] 中低显存 (占用约 4.0 GB 显存 - 上下文驻留内存 - 预留约 8.0 GB 给 ComfyUI / 游戏)
echo [3] 平衡显存 (占用约 6.0 GB 显存 - 上下文驻留内存 - 预留约 6.0 GB 给 ComfyUI / 游戏)
echo [4] 较多显存 (占用约 8.0 GB 显存 - 上下文驻留内存 - 预留约 4.0 GB 给其他程序)
echo [5] 自定义显存大小 (支持直接输入数值如 3.5、5、7、10 等，上下文均跑在内存中)
echo.
echo ------------------------------------------------------------
echo [0] 返回策略选择
echo ============================================================
echo.
set "v_choice="
set /p v_choice=请选择显存分配档位 (默认 2，也可直接输入数字如 5): 

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
    set /p input_vram=请输入希望模型占用的显存大小 (GB，例如 3.5、5、8、10，上下文驻留内存): 
    if not defined input_vram set input_vram=4.0
    set "TARGET_VRAM=!input_vram!"
)

if not "%v_choice%"=="1" if not "%v_choice%"=="2" if not "%v_choice%"=="3" if not "%v_choice%"=="4" if not "%v_choice%"=="5" (
    set "TARGET_VRAM=!v_choice!"
)

goto APPLY_STRATEGY

:: -----------------------------------------------------
:: 自动计算策略配置
:: -----------------------------------------------------
:APPLY_STRATEGY
echo.
echo 正在自动计算分层与最佳上下文长度...
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
if not defined MODE set MODE=极速全显存模式 (回退默认计算)
if not defined EXTRA_FLAGS set EXTRA_FLAGS=
if "%EXTRA_FLAGS%"=="-" set "EXTRA_FLAGS="
if not defined REMAIN_LAYERS set REMAIN_LAYERS=0
if not defined MODEL_VRAM_EST set MODEL_VRAM_EST=0
if not defined APPLIED_VRAM set APPLIED_VRAM=0
if not defined TOTAL_BLOCKS set TOTAL_BLOCKS=40

echo.
echo ------------------------------------------------------------
echo [已完成自动策略计算]
echo  * 运行模式: !MODE!
echo  * 显存分配目标: !APPLIED_VRAM! GB
echo  * 显卡装载层数: !NGL! / !TOTAL_BLOCKS! 层 [模型约占 !MODEL_VRAM_EST! GB 显存]
echo  * 内存装载层数: !REMAIN_LAYERS! 层
echo  * 上下文容量: !CTX! Tokens
echo ------------------------------------------------------------
echo [1] 确认当前策略并继续 (直接回车默认)
echo [0] 返回重新选择策略
echo ============================================================
echo.
set "strat_confirm="
set /p strat_confirm=请选择 (默认 1): 
if defined strat_confirm set "strat_confirm=!strat_confirm: =!"
if "!strat_confirm!"=="0" (
    set "s_choice="
    set "TARGET_VRAM="
    goto SELECT_STRATEGY
)
goto SELECT_TEMPLATE

:: =====================================================
:: 角色设定选择
:: =====================================================
:SELECT_TEMPLATE
cls
echo ============================================================
echo 当前模型: !MODEL_NAME! (!MODEL_SIZE!)
echo 运行模式: !MODE!
echo ============================================================
echo.
echo 可用角色设定列表 (* 标注当前已激活)：
echo.

"%PYTHON%" "%~dp0role_manager.py" --list-short 2>nul

echo.
echo ------------------------------------------------------------
echo [N] 原生默认模式 (不注入任何角色设定，适合代码/翻译/英文)
echo [E] 临时输入自定义角色设定 (空行回车结束，可选转存永久)
echo [M] 角色设定管理中心 (新增 / 编辑 / 查看 / 删除 / 记事本)
echo [0] 返回策略选择
echo ============================================================
echo.
set "t_choice="
set /p t_choice=请选择角色编号或操作 (直接回车沿用当前激活角色): 

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
    echo [提示] 输入无效！请输入列表中的有效角色编号，或输入 N / E / M / 0。
    timeout /t 2 >nul 2>nul
    goto SELECT_TEMPLATE
)

:ROLE_APPLIED
set "ROLE_NAME="
for /f "usebackq delims=" %%R in (`""%PYTHON%" "%~dp0role_manager.py" --current-name" 2^>nul`) do (
    set "ROLE_NAME=%%R"
)
if not defined ROLE_NAME set "ROLE_NAME=原生默认 (无角色)"
goto SELECT_LIMIT

:: =====================================================
:: 单次生成最大长度限制选择
:: =====================================================
:SELECT_LIMIT
cls
echo ============================================================
echo 当前配置确认：
echo 模型: !MODEL_NAME! (!MODEL_SIZE!)
echo 策略: !MODE!
echo 角色: !ROLE_NAME!
echo ============================================================
echo.
echo 请选择单次生成长度限制：
echo.
echo [1] 短文本模式   (约 500 字左右 ^| 限制 1500 Tokens)
echo [2] 中等文本模式 (约 1000 字左右 ^| 限制 3000 Tokens)
echo [3] 长文本模式   (约 3000 字左右 ^| 限制 7500 Tokens)
echo [4] 超长文章模式 (一次可达 5000 字 ^| 限制 12000 Tokens)
echo [5] 无限制生成   (由模型自行停止 ^| 设置为 -1)
echo.
echo ------------------------------------------------------------
echo [0] 返回角色设定选择
echo ============================================================
echo.
set "limit_choice="
set "N_PREDICT=3000"
set /p limit_choice=请选择 (默认 2): 

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

:: 1. 清理残留旧进程与端口
taskkill /F /IM llama-server.exe >nul 2>nul
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8080" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>nul
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8081" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>nul
chcp 936 >nul

:: 1.5 检测当前模型架构是否使用 Qwen 自定义模板 (非 Qwen 自动改用 GGUF 原生模板)
set "LLAMA_CUSTOM_TEMPLATE=0"
for /f "usebackq delims=" %%T in (`""%PYTHON%" "%~dp0model_manager.py" --check-template-compat "!MODEL!"" 2^>nul`) do (
    if "%%T"=="USE_CUSTOM" set "LLAMA_CUSTOM_TEMPLATE=1"
)

:: 2. 启动后台 Web 与 API 统一中枢 server_core.py (监听 8080 端口)
start "" /b "%PYTHON%" "%~dp0server_core.py" > "%~dp0server_core.log" 2>&1

:: 3. 验证 8080 端口是否就绪 (等待最多 3 秒)
set "PORT_ARG=8081"
set "CORE_READY=0"
for /L %%w in (1,1,6) do (
    if "!CORE_READY!"=="0" (
        "%PYTHON%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=1)" >nul 2>nul
        if not errorlevel 1 set "CORE_READY=1"
        if "!CORE_READY!"=="0" ping -n 1 -w 500 127.0.0.1 >nul 2>nul
    )
)

:: 如果 server_core.py 未能启动，则由 llama-server 原生直接托管 8080 端口，确保 http://127.0.0.1:8080 始终可用
if "!CORE_READY!"=="0" (
    echo [提示] Web 统一中枢未就绪，由 llama-server 原生托管 8080 端口...
    set "PORT_ARG=8080"
)

:: 4. 打印详细的模型显存/内存资源占用标注及访问端点面板
"%PYTHON%" "%~dp0model_manager.py" --print-resource-banner "!MODEL!" "!NGL!" "!CTX!" "!EXTRA_FLAGS!" "!MODE!" "!ROLE_NAME!" "!N_PREDICT!" "!TOTAL_BLOCKS!" 2>nul

set "LLAMA_BIN="
if exist "%~dp0llama-server.exe" set "LLAMA_BIN=%~dp0llama-server.exe"
if not defined LLAMA_BIN (
    where llama-server.exe >nul 2>nul && set "LLAMA_BIN=llama-server.exe"
)
if not defined LLAMA_BIN (
    echo.
    echo [错误] 未找到 llama-server.exe ！
    echo        请先从 llama.cpp 官方 Releases 下载 Windows 预编译包，
    echo        并将 llama-server.exe 及对应 .dll 文件解压至本目录后重试。
    echo.
    "%PYTHON%" "%~dp0memory_optimizer.py" --restore >nul 2>nul
    pause
    goto SELECT_MODEL
)

echo [正在载入模型权重并启动推理引擎，请稍候...]
echo.

if "!LLAMA_CUSTOM_TEMPLATE!"=="1" (
    if defined MMPROJ (
        "!LLAMA_BIN!" -m "!MODEL!" --mmproj "!MMPROJ!" --chat-template-file "%~dp0_active_template.jinja" --path "%~dp0web" --fit off -ngl !NGL! -c !CTX! -n !N_PREDICT! -fa on --cont-batching -np 1 --host 127.0.0.1 --port !PORT_ARG! --log-file "%~dp0llama_server.log" !EXTRA_FLAGS!
    ) else (
        "!LLAMA_BIN!" -m "!MODEL!" --chat-template-file "%~dp0_active_template.jinja" --path "%~dp0web" --fit off -ngl !NGL! -c !CTX! -n !N_PREDICT! -fa on --cont-batching -np 1 --host 127.0.0.1 --port !PORT_ARG! --log-file "%~dp0llama_server.log" !EXTRA_FLAGS!
    )
) else (
    echo [提示] 检测到非 Qwen 架构模型，已自动切换为模型内置原生对话模板。
    if defined MMPROJ (
        "!LLAMA_BIN!" -m "!MODEL!" --mmproj "!MMPROJ!" --path "%~dp0web" --fit off -ngl !NGL! -c !CTX! -n !N_PREDICT! -fa on --cont-batching -np 1 --host 127.0.0.1 --port !PORT_ARG! --log-file "%~dp0llama_server.log" !EXTRA_FLAGS!
    ) else (
        "!LLAMA_BIN!" -m "!MODEL!" --path "%~dp0web" --fit off -ngl !NGL! -c !CTX! -n !N_PREDICT! -fa on --cont-batching -np 1 --host 127.0.0.1 --port !PORT_ARG! --log-file "%~dp0llama_server.log" !EXTRA_FLAGS!
    )
)

:AFTER_START
:: 1. 模型退出后第一时间立刻恢复动态壁纸与后台资源，无需任何按键等待！
"%PYTHON%" "%~dp0memory_optimizer.py" --restore >nul 2>nul
taskkill /F /IM llama-server.exe >nul 2>nul
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8080" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>nul
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8081" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>nul
chcp 936 >nul
echo.
echo ============================================================
echo [提示] 模型已运行结束，动态壁纸与后台资源已自动恢复。
echo ============================================================
echo.
echo [1] 重新启动当前配置
echo [2] 返回角色设定选择
echo [3] 返回策略与显存配置
echo [0] 返回模型选择菜单
echo ============================================================
echo.
set "restart_choice="
set /p restart_choice=请选择 (默认 1): 

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
