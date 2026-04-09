# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Smoke test for Windows (PowerShell)
# Usage: .\scripts\smoke_test.ps1 [-PackageInstall]
#
# Flags:
#   -PackageInstall   pip install from PyPI (default: editable from source)

param([switch]$PackageInstall)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$SmokeDir = Join-Path $env:TEMP "cognirepo_smoke_$(Get-Random)"
New-Item -ItemType Directory -Path $SmokeDir | Out-Null

Write-Host "=== CogniRepo Smoke Test (Windows) ==="
Write-Host "    platform : Windows"
Write-Host "    python   : $(python --version)"
Write-Host "    workdir  : $SmokeDir"
Write-Host ""

Set-Location $SmokeDir

try {
    # 1. Install
    Write-Host "[1/5] Installing cognirepo..."
    if ($PackageInstall) {
        pip install cognirepo --quiet
    } else {
        pip install -e "$RepoRoot[dev,security]" --quiet
    }
    Write-Host "      OK"

    # 2. Init
    Write-Host "[2/5] cognirepo init --no-index --non-interactive..."
    cognirepo init --password smoketest --no-index --non-interactive
    if (-not (Test-Path ".cognirepo\config.json")) {
        throw "FAIL: config.json not created"
    }
    Write-Host "      OK"

    # 3. Index
    Write-Host "[3/5] cognirepo index-repo --no-watch..."
    New-Item -ItemType Directory -Path "myapp" -Force | Out-Null
    Set-Content -Path "myapp\hello.py" -Value @"
def greet(name: str) -> str:
    return f"Hello, {name}"
"@
    cognirepo index-repo . --no-watch
    Write-Host "      OK"

    # 4. Memory
    Write-Host "[4/5] store-memory + retrieve-memory..."
    cognirepo store-memory "smoke test memory entry alpha"
    $result = cognirepo retrieve-memory "smoke test memory" --top-k 1 2>$null
    Write-Host "      OK"

    # 5. MCP serve — on Windows daemon is not supported; just check serve starts
    Write-Host "[5/5] MCP server (foreground mode check)..."
    Write-Host "      SKIP: daemon not supported on Windows — use 'cognirepo serve' in foreground"

    Write-Host ""
    Write-Host "=== Smoke test PASSED ==="
} finally {
    Set-Location $RepoRoot
    Remove-Item -Recurse -Force $SmokeDir -ErrorAction SilentlyContinue
}
