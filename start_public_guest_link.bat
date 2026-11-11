@echo off
title LAGGAM IPHOTOO - Public Guest QR Tunnel
set CLOUDFLARED=cloudflared
if exist "%~dp0cloudflared.exe" set CLOUDFLARED="%~dp0cloudflared.exe"
where cloudflared >nul 2>nul
if errorlevel 1 if not exist "%~dp0cloudflared.exe" (
  echo cloudflared is not installed.
  echo Download the Windows 64-bit executable from:
  echo https://developers.cloudflare.com/tunnel/downloads/
  echo Save it as cloudflared.exe in this folder, then run this file again.
  pause
  exit /b 1
)
echo ================================================
echo LAGGAM IPHOTOO - TEMPORARY PUBLIC GUEST LINK
echo ================================================
echo Make sure start_laggam_local.bat is already running.
echo Copy the https://...trycloudflare.com address printed below.
echo Open that public address in your laptop browser BEFORE creating the event.
echo Keep this window open. The public link stops when this window closes.
echo.
%CLOUDFLARED% tunnel --url http://127.0.0.1:8000
pause
