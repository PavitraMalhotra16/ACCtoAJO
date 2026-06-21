<#
  Start (or restart) the ACC->AJO backend cleanly on a fixed port.
  Frees the port and clears any stale uvicorn first, so it always lands clean,
  then runs from the backend/ dir (no cwd surprises). Ctrl+C to stop.

  Usage:
    powershell -ExecutionPolicy Bypass -File scripts\start-backend.ps1
    powershell -ExecutionPolicy Bypass -File scripts\start-backend.ps1 -Port 8000
#>
param([int]$Port = 8001)
$ErrorActionPreference = 'SilentlyContinue'

$root    = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'

Write-Host "Freeing port $Port and clearing stale uvicorn..."
# Kill whatever currently listens on the port (the running server / orphaned worker).
Get-NetTCPConnection -LocalPort $Port -State Listen |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
# Kill any lingering uvicorn for this app (reloader parents etc.).
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'uvicorn' -and $_.CommandLine -match 'main:app' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Milliseconds 1000

Set-Location $backend
# Prefer the project venv's interpreter so the deps are guaranteed present,
# regardless of which shell/PATH invokes this script.
$venvPy = Join-Path $backend '.venv\Scripts\python.exe'
$py = if (Test-Path $venvPy) { $venvPy } else { 'python' }
Write-Host "Backend -> http://127.0.0.1:$Port   (Ctrl+C to stop)"
# No --reload on purpose: a reload kills in-flight background migrations and can
# spawn duplicate workers that fight over the port.
& $py -m uvicorn main:app --host 127.0.0.1 --port $Port
