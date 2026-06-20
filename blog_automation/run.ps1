# Avvia backend (FastAPI :8000) e frontend (React/Vite :8080) in due finestre.
#
# Uso:   .\run.ps1
# Poi apri http://localhost:8080
#
# Opzioni:
#   .\run.ps1 -Install      installa/aggiorna le dipendenze prima di partire
#   .\run.ps1 -NoBrowser    non aprire automaticamente il browser

param(
    [switch]$Install,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

# Python: usa la .venv del progetto se esiste, altrimenti il python di sistema.
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPy) { $venvPy } else { "python" }

Write-Host "Python: $python" -ForegroundColor Cyan

if ($Install) {
    Write-Host "Installazione dipendenze Python..." -ForegroundColor Yellow
    & $python -m pip install -r (Join-Path $root "requirements.txt")
    Write-Host "Installazione dipendenze frontend..." -ForegroundColor Yellow
    Push-Location (Join-Path $root "web")
    npm install
    Pop-Location
}

# Backend in una nuova finestra (uvicorn con auto-reload).
Write-Host "Avvio backend su http://localhost:8000 ..." -ForegroundColor Green
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$root'; & '$python' -m uvicorn server.app:app --reload --port 8000"
)

# Frontend in un'altra finestra (Vite dev server).
Write-Host "Avvio frontend su http://localhost:8080 ..." -ForegroundColor Green
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$root\web'; npm run dev"
)

if (-not $NoBrowser) {
    Start-Sleep -Seconds 3
    Start-Process "http://localhost:8080"
}

Write-Host ""
Write-Host "Pronto. Backend :8000  |  Frontend :8080" -ForegroundColor Cyan
Write-Host "Chiudi le due finestre PowerShell per fermare i server." -ForegroundColor DarkGray
