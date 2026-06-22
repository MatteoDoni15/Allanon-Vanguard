<#
.SYNOPSIS
    Pulisce il progetto dai file/cartelle inutili (cache, build, temporanei).

.DESCRIPTION
    Rimuove ricorsivamente cose come __pycache__, *.pyc, cache di pytest,
    cartelle di build Python/Node e file temporanei. NON tocca i sorgenti,
    .git, requirements.txt, package.json, ecc.

    Per default fa un "dry run" (mostra solo cosa cancellerebbe).
    Usa -Apply per eliminare davvero.
    Usa -IncludeNodeModules per rimuovere anche node_modules (si reinstalla con npm install).

.EXAMPLE
    .\cleanup.ps1                 # mostra cosa verrebbe eliminato
    .\cleanup.ps1 -Apply          # elimina davvero
    .\cleanup.ps1 -Apply -IncludeNodeModules
#>

[CmdletBinding()]
param(
    [switch]$Apply,
    [switch]$IncludeNodeModules
)

# Lavora sempre dalla cartella in cui si trova lo script
$root = $PSScriptRoot
if (-not $root) { $root = Get-Location }
Write-Host "Root progetto: $root" -ForegroundColor Cyan

# Cartelle da eliminare (per nome, ovunque nel progetto)
$dirPatterns = @(
    '__pycache__',
    '.pytest_cache',
    '.mypy_cache',
    '.ruff_cache',
    '.ipynb_checkpoints',
    '.vite',
    'dist',
    'build',
    '.parcel-cache',
    '*.egg-info'
)

# File da eliminare (per estensione/nome, ovunque nel progetto)
$filePatterns = @(
    '*.pyc',
    '*.pyo',
    '*.pyd',
    '*.log',
    '*.tmp',
    '.DS_Store',
    'Thumbs.db'
)

if ($IncludeNodeModules) {
    $dirPatterns += 'node_modules'
}

# Non scendere mai dentro queste cartelle durante la ricerca
$excludeRoots = @('.git')

$totalBytes = 0
$count = 0

function Test-Excluded($path) {
    foreach ($ex in $excludeRoots) {
        if ($path -match "\\$([regex]::Escape($ex))(\\|$)") { return $true }
    }
    return $false
}

# --- Cartelle ---
foreach ($pattern in $dirPatterns) {
    Get-ChildItem -Path $root -Directory -Recurse -Force -Filter $pattern -ErrorAction SilentlyContinue |
        Where-Object { -not (Test-Excluded $_.FullName) } |
        ForEach-Object {
            $size = (Get-ChildItem $_.FullName -Recurse -Force -File -ErrorAction SilentlyContinue |
                     Measure-Object -Property Length -Sum).Sum
            if (-not $size) { $size = 0 }
            $totalBytes += $size
            $count++
            $mb = [math]::Round($size / 1MB, 2)
            Write-Host ("[DIR ]  {0}  ({1} MB)" -f $_.FullName, $mb) -ForegroundColor Yellow
            if ($Apply) {
                Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
}

# --- File ---
foreach ($pattern in $filePatterns) {
    Get-ChildItem -Path $root -File -Recurse -Force -Filter $pattern -ErrorAction SilentlyContinue |
        Where-Object { -not (Test-Excluded $_.FullName) } |
        ForEach-Object {
            $totalBytes += $_.Length
            $count++
            Write-Host ("[FILE]  {0}" -f $_.FullName) -ForegroundColor DarkYellow
            if ($Apply) {
                Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
            }
        }
}

$totalMb = [math]::Round($totalBytes / 1MB, 2)
Write-Host ""
if ($Apply) {
    Write-Host ("Eliminati {0} elementi, liberati ~{1} MB." -f $count, $totalMb) -ForegroundColor Green
} else {
    Write-Host ("Trovati {0} elementi (~{1} MB). Niente eliminato (dry run)." -f $count, $totalMb) -ForegroundColor Green
    Write-Host "Esegui di nuovo con  -Apply  per eliminare davvero." -ForegroundColor Green
}
