$ErrorActionPreference = "Stop"

$agentRoot = Split-Path -Parent $PSScriptRoot
# Use the same Windows Store Python runtime as agent2. On this machine its
# network policy allows the ERP VLAN; the E:\pythen runtime is blocked with
# WinError 10013 when opening 172.20.0.114:3306.
$pythonExe = if (Test-Path "C:\Users\Administrator\AppData\Local\Microsoft\WindowsApps\python.exe") {
  "C:\Users\Administrator\AppData\Local\Microsoft\WindowsApps\python.exe"
} elseif (Test-Path "E:\pythen\python.exe") { "E:\pythen\python.exe" } else { "python" }

$env:APP_ENV = "development"
$env:DATABASE_URL = "sqlite+aiosqlite:///./storage/demo-host.db"
$env:STORAGE_PATH = Join-Path $agentRoot "storage"
$env:REDIS_URL = "redis://127.0.0.1:6379/0"
$env:CORS_ORIGINS = "http://127.0.0.1:5177,http://localhost:5177,http://127.0.0.1:5173,http://localhost:5173"
$env:VITE_API_BASE_URL = "http://127.0.0.1:18001/api/v1"

Write-Host "Starting agent backend on http://127.0.0.1:18001"
Start-Process -FilePath $pythonExe -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","18001","--app-dir","backend" -WorkingDirectory $agentRoot

Write-Host "Starting host-built frontend on http://127.0.0.1:5177"
Start-Process -FilePath "npm.cmd" -ArgumentList "run","dev:host" -WorkingDirectory (Join-Path $agentRoot "frontend")
