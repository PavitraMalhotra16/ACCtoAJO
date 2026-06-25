<#
  Stop the ACC->AJO backend + frontend and clear their dev ports.
  Use this to wipe stale instances when things get into a weird state.

  Usage:
    powershell -ExecutionPolicy Bypass -File scripts\stop-dev.ps1
#>
$ErrorActionPreference = 'SilentlyContinue'

Get-CimInstance Win32_Process |
  Where-Object {
    ($_.Name -eq 'python.exe' -and $_.CommandLine -match 'uvicorn' -and $_.CommandLine -match 'main:app') -or
    ($_.Name -eq 'node.exe'   -and $_.CommandLine -match 'vite')
  } |
  ForEach-Object { Write-Host "stopped PID $($_.ProcessId)  ($($_.Name))"; Stop-Process -Id $_.ProcessId -Force }

foreach ($p in 8000, 8001, 5173, 5174, 5175, 5176) {
  Get-NetTCPConnection -LocalPort $p -State Listen |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
}
Write-Host "Dev servers stopped."
