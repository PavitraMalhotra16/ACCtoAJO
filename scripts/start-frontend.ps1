<#
  Start (or restart) the ACC->AJO frontend (Vite) cleanly.
  Clears stale vite dev servers first so it lands on the default port. Ctrl+C to stop.

  Usage:
    powershell -ExecutionPolicy Bypass -File scripts\start-frontend.ps1
#>
param([int]$Port = 5174)
$ErrorActionPreference = 'SilentlyContinue'

$root     = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root 'frontend_app'

Write-Host "Clearing stale vite dev servers..."
Get-NetTCPConnection -LocalPort $Port -State Listen |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq 'node.exe' -and $_.CommandLine -match 'vite' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Milliseconds 800

Set-Location $frontend
Write-Host "Frontend (Vite) starting - proxies /api to the backend (see vite.config.ts)."
npm run dev
