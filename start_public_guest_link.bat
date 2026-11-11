@echo off
title LAGGAM IPHOTOO - Public Guest QR Tunnel
echo ================================================
echo LAGGAM IPHOTOO - TEMPORARY PUBLIC GUEST LINK
echo ================================================
where cloudflared >nul 2>nul
if errorlevel 1 (
  echo cloudflared is not installed.
  echo Try installing it with this command:
  echo winget install --id Cloudflare.cloudflared --exact
  echo Then close this window and run this file again.
  pause
  exit /b 1
)
echo.
echo Make sure start_laggam_local.bat is already running.
echo Copy the https://...trycloudflare.com address printed below.
echo Create/open events using that public address so QR links are correct.
echo Keep this window open. The public link stops when this window closes.
echo.
cloudflared tunnel --url http://127.0.0.1:8000
pause
