@echo off
REM ---------------------------------------------------------------
REM  Ground Intel - push the pending commits
REM
REM  Nothing on the live server has any of this yet. Waiting to ship:
REM    * the whole irrigation stack (9 map layers)
REM    * village-level irrigation, auto-run on the searched area
REM    * Minor Irrigation Census (village wells) via the mandi API key
REM    * the map-token fix (no more invisible layers)
REM    * the full PDF / Excel report
REM    * 2,626 archived ground-truth points folded into the classifier
REM
REM  Double-click this file, or run it from a terminal in
REM  F:\AgriRadiusPro
REM ---------------------------------------------------------------
cd /d "%~dp0"

echo Commits waiting to be pushed:
git log origin/main..HEAD --oneline
echo.

echo Pushing to GitHub...
git push origin main
set RC=%ERRORLEVEL%

echo.
if not "%RC%"=="0" (
  echo *** PUSH FAILED - copy everything above and send it to Claude.
) else (
  echo Push succeeded. Give the server ~5 minutes, then reload
  echo https://groundintel.oneroot.farm
  echo.
  echo On first restart the server harvests, by itself, in the
  echo background: village boundaries, the India-WRIS canal command
  echo areas, and the Minor Irrigation Census. No SSH needed.
)
echo.
pause
