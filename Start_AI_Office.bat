@echo off
REM ---------------------------------------------------------------
REM  SU Media AI Office - lokal start
REM  Dobbeltklik denne fil for at starte dashboardet i din browser.
REM  Luk vinduet (eller tryk Ctrl+C) for at stoppe appen igen.
REM ---------------------------------------------------------------

REM Skift til scriptets egen mappe (projektroden), uanset hvorfra det startes.
cd /d "%~dp0"

echo Starter SU Media AI Office...
echo Dashboardet aabner i din browser paa http://localhost:8501
echo.

python -m streamlit run dashboard/app.py

REM Naar serveren stopper (eller ikke kunne starte), holdes vinduet aabent,
REM saa en eventuel fejlbesked kan laeses.
echo.
echo AI Office er stoppet.
pause
