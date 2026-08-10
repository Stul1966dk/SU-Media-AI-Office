@echo off
REM ---------------------------------------------------------------
REM  SU Media AI Office - lokal start
REM  Dobbeltklik denne fil for at starte dashboardet i din browser.
REM  Luk vinduet (eller tryk Ctrl+C) for at stoppe appen igen.
REM ---------------------------------------------------------------

REM Skift til scriptets egen mappe (projektroden), uanset hvorfra det startes.
cd /d "%~dp0"

echo Starter SU Media AI Office...
echo Dashboardet aabner automatisk i Chrome paa http://localhost:8501
echo.

REM Vent i baggrunden til serveren svarer, og aabn saa Chrome paa dashboardet.
REM Falder tilbage til standardbrowseren, hvis Chrome ikke kan findes.
start "" powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 60;$i++){try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('localhost',8501);$c.Close();break}catch{Start-Sleep -Milliseconds 500}};$chrome=(Get-Command chrome -ErrorAction SilentlyContinue).Source;if(-not $chrome){$p='C:\Program Files\Google\Chrome\Application\chrome.exe';if(Test-Path $p){$chrome=$p}};if($chrome){Start-Process $chrome 'http://localhost:8501'}else{Start-Process 'http://localhost:8501'}"

REM Start serveren headless, saa kun Chrome aabnes (ikke ogsaa standardbrowseren).
python -m streamlit run dashboard/app.py --server.headless true

REM Naar serveren stopper (eller ikke kunne starte), holdes vinduet aabent,
REM saa en eventuel fejlbesked kan laeses.
echo.
echo AI Office er stoppet.
pause
