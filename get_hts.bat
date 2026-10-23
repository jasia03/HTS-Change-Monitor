@echo off
REM Downloads all 2025-2026 HTS files into data\raw using Windows' built-in curl.
REM Skips files you already have. --fail means a blocked download saves nothing.

set BASE=https://www.usitc.gov/sites/default/files/tata/hts
set UA=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36
if not exist data\raw mkdir data\raw

call :get 2025HTSBasic hts_2025_basic_edition_json.json
for /L %%n in (1,1,32) do call :get 2025HTSRev%%n hts_2025_revision_%%n_json.json
call :get 2026HTSBasic hts_2026_basic_edition_json.json
for /L %%n in (1,1,21) do call :get 2026HTSRev%%n hts_2026_revision_%%n_json.json

echo.
echo Done. Files in data\raw:
dir /b data\raw | find /c ".json"
goto :eof

:get
if exist data\raw\%1.json (
  echo %1  already have it
  goto :eof
)
curl.exe -s -L --fail -A "%UA%" -e "https://www.usitc.gov/harmonized_tariff_information/hts/archive/list" -o data\raw\%1.json %BASE%/%2
if errorlevel 1 (
  echo %1  BLOCKED
) else (
  echo %1  OK
)
timeout /t 1 /nobreak >nul
goto :eof
