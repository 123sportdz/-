@echo off
rem _env_local.bat - keeps ALL tool caches inside the project folder.
rem Call this from every entry script (after cd /d "%~dp0").
rem Effect: nothing is written to C:\Users\...\.cache or AppData,
rem so the project can live entirely on D: (or any drive).

if not exist .cache mkdir .cache
if not exist .cache\hf mkdir .cache\hf
if not exist .cache\torch mkdir .cache\torch
if not exist .cache\pip mkdir .cache\pip
if not exist .cache\mpl mkdir .cache\mpl
if not exist .cache\yolo mkdir .cache\yolo

set "HF_HOME=%~dp0.cache\hf"
set "TORCH_HOME=%~dp0.cache\torch"
set "PIP_CACHE_DIR=%~dp0.cache\pip"
set "MPLCONFIGDIR=%~dp0.cache\mpl"
set "YOLO_CONFIG_DIR=%~dp0.cache\yolo"

exit /b 0
