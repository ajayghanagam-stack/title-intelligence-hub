#Requires -Version 5.1
<#
.SYNOPSIS
    Start the full Title Intelligence Hub dev stack on Windows.

.DESCRIPTION
    Windows / PowerShell port of ./start-dev.sh. Supports both
    Title Intelligence (TI) and Title Search & Abstracting (TSA).

    Infrastructure (Postgres + Temporal) runs in Docker.
    Backend, Temporal worker, and frontend run locally for fast reloads.

    Usage:  .\start-dev-windows.ps1
    Stop:   Ctrl+C in this window (cleanup runs in a finally block).

.NOTES
    First-time setup:
        Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
    If 'python' is not on PATH, run scripts/seed.py with 'py' or activate
    the venv before launching this script.
#>

$ErrorActionPreference = "Stop"

$RootDir    = $PSScriptRoot
$BackendDir = Join-Path $RootDir 'backend'
$FrontendDir = Join-Path $RootDir 'frontend'

# Track child processes for cleanup
$script:ChildProcs = @()

function Write-Stage   { param([string]$Msg) Write-Host $Msg -ForegroundColor Cyan }
function Write-OK      { param([string]$Msg) Write-Host $Msg -ForegroundColor Green }
function Write-Warn    { param([string]$Msg) Write-Host $Msg -ForegroundColor Yellow }

function Test-Port {
    param([int]$Port)
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $task = $client.ConnectAsync('127.0.0.1', $Port)
        $ok = $task.Wait(500)
        $client.Close()
        return $ok -and $client.Connected -eq $false -or $ok
    } catch {
        return $false
    }
}

function Stop-PortHolders {
    param([int]$Port, [string]$Label)
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { return }
    $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
    if (-not $pids) { return }
    Write-Warn "       Killing stale $Label process(es) on port ${Port}: $($pids -join ', ')"
    foreach ($procId in $pids) {
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
    $remaining = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
                 Select-Object -ExpandProperty OwningProcess -Unique
    if ($remaining) {
        Write-Warn "       Force-killing stubborn process(es) on port ${Port}: $($remaining -join ', ')"
        foreach ($procId in $remaining) {
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
}

function Stop-MatchingProcesses {
    param([string]$Pattern)
    # CIM gives us the full command line so we can match worker invocations
    # (python -m app.pipeline.unified_worker) the same way pgrep -f does.
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
             Where-Object { $_.CommandLine -and $_.CommandLine -match $Pattern }
    if (-not $procs) { return }
    $ids = $procs.ProcessId
    Write-Warn "       Killing stale worker(s): $($ids -join ', ')"
    foreach ($procId in $ids) {
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    $remaining = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                 Where-Object { $_.CommandLine -and $_.CommandLine -match $Pattern }
    if ($remaining) {
        Write-Warn "       Force-killing stubborn worker(s): $($remaining.ProcessId -join ', ')"
        foreach ($procId in $remaining.ProcessId) {
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
}

function Start-Child {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [hashtable]$EnvVars = @{}
    )
    # Apply env vars for this process invocation. Start-Process inherits the
    # current shell's env, so we set / restore around the call.
    $original = @{}
    foreach ($k in $EnvVars.Keys) {
        $original[$k] = [System.Environment]::GetEnvironmentVariable($k)
        [System.Environment]::SetEnvironmentVariable($k, $EnvVars[$k])
    }
    try {
        $proc = Start-Process -FilePath $FilePath `
                              -ArgumentList $ArgumentList `
                              -WorkingDirectory $WorkingDirectory `
                              -NoNewWindow `
                              -PassThru
        $script:ChildProcs += $proc
        return $proc
    } finally {
        foreach ($k in $original.Keys) {
            [System.Environment]::SetEnvironmentVariable($k, $original[$k])
        }
    }
}

function Stop-AllChildren {
    Write-Host ""
    Write-Warn "Shutting down..."
    foreach ($proc in $script:ChildProcs) {
        if ($proc -and -not $proc.HasExited) {
            try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
        }
    }
    # Also stop the worker that uvicorn / npm may have spawned as children.
    Stop-MatchingProcesses -Pattern 'temporal_worker|unified_worker'
    # Stop the docker infrastructure (matches bash 'docker compose stop')
    try {
        & docker compose -f (Join-Path $RootDir 'docker-compose.yml') stop db temporal-db temporal temporal-ui 2>$null | Out-Null
    } catch {}
    Write-OK "All stopped."
}

try {
    # ------------------------------------------------------------------
    # 0. Kill stale processes, clear caches, terminate orphan workflows
    # ------------------------------------------------------------------
    Write-Stage "[0/5] Cleaning up stale state..."

    Stop-MatchingProcesses -Pattern 'temporal_worker|unified_worker'
    Stop-PortHolders -Port 8000 -Label 'backend'
    Stop-PortHolders -Port 3000 -Label 'frontend'

    Write-Stage "       Clearing __pycache__..."
    Get-ChildItem -Path $BackendDir -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

    Write-OK "       Cleanup complete"

    # ------------------------------------------------------------------
    # 1. Start infrastructure (Postgres + Temporal) in Docker
    # ------------------------------------------------------------------
    Write-Stage "[1/5] Starting Postgres + Temporal (Docker)..."
    $composeFile = Join-Path $RootDir 'docker-compose.yml'
    & docker compose -f $composeFile up -d db temporal-db temporal temporal-ui
    if ($LASTEXITCODE -ne 0) { throw "docker compose up failed (exit $LASTEXITCODE). Is Docker Desktop running?" }

    # Wait for Postgres
    Write-Stage "       Waiting for Postgres..."
    while ($true) {
        & docker compose -f $composeFile exec -T db pg_isready -U postgres 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Seconds 1
    }
    Write-OK "       Postgres ready on localhost:5436"

    # Wait for Temporal (port 7233 reachable from host)
    Write-Stage "       Waiting for Temporal on localhost:7233..."
    $ready = $false
    for ($i = 1; $i -le 90; $i++) {
        if (Test-Port -Port 7233) {
            Start-Sleep -Seconds 3
            Write-OK "       Temporal ready on localhost:7233"
            $ready = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) {
        Write-Warn "       WARNING: Temporal may not be ready yet (timed out)"
    }

    # Terminate orphaned Temporal workflows
    Write-Stage "       Terminating stale Temporal workflows..."
    $env:PYTHONPATH = $BackendDir
    $cleanupPy = @"
import asyncio
from temporalio.client import Client

async def cleanup():
    client = await Client.connect('localhost:7233', namespace='default')
    count = 0
    async for wf in client.list_workflows(query="ExecutionStatus='Running'"):
        handle = client.get_workflow_handle(wf.id, run_id=wf.run_id)
        await handle.terminate(reason='Stale workflow terminated by start-dev-windows.ps1')
        count += 1
    if count:
        print(f'       Terminated {count} stale workflow(s)')
    else:
        print('       No stale workflows found')

asyncio.run(cleanup())
"@
    try {
        Push-Location $BackendDir
        $cleanupPy | & python - 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "       Could not check Temporal workflows (non-fatal)"
        }
    } catch {
        Write-Warn "       Could not check Temporal workflows (non-fatal)"
    } finally {
        Pop-Location
    }

    # ------------------------------------------------------------------
    # 2. Seed the database
    # ------------------------------------------------------------------
    Write-Stage "[2/5] Seeding database..."
    Push-Location $BackendDir
    try {
        $env:PYTHONPATH = $BackendDir
        & python scripts/seed.py
        if ($LASTEXITCODE -ne 0) { throw "Seed script failed (exit $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
    Write-OK "       Seed complete"

    # ------------------------------------------------------------------
    # 3. Start backend (uvicorn with hot-reload)
    # ------------------------------------------------------------------
    Write-Stage "[3/5] Starting backend on http://localhost:8000 ..."
    Start-Child -FilePath 'python' `
                -ArgumentList @('-m', 'uvicorn', 'app.main:app',
                                '--host', '0.0.0.0', '--port', '8000',
                                '--reload', '--reload-dir', 'app') `
                -WorkingDirectory $BackendDir `
                -EnvVars @{ PYTHONPATH = $BackendDir } | Out-Null

    # ------------------------------------------------------------------
    # 4. Start Temporal worker
    # ------------------------------------------------------------------
    Write-Stage "[4/5] Starting unified Temporal worker..."
    Start-Child -FilePath 'python' `
                -ArgumentList @('-m', 'app.pipeline.unified_worker') `
                -WorkingDirectory $BackendDir `
                -EnvVars @{ PYTHONPATH = $BackendDir } | Out-Null

    # ------------------------------------------------------------------
    # 5. Start frontend (Next.js dev server)
    # ------------------------------------------------------------------
    Write-Stage "[5/5] Starting frontend on http://localhost:3000 ..."
    $nextCache = Join-Path $FrontendDir '.next'
    if (Test-Path $nextCache) {
        Write-Warn "       Clearing .next cache..."
        Remove-Item -Recurse -Force $nextCache -ErrorAction SilentlyContinue
    }
    # 'npm' on Windows is npm.cmd — Start-Process resolves it via PATHEXT.
    Start-Child -FilePath 'npm.cmd' `
                -ArgumentList @('run', 'dev') `
                -WorkingDirectory $FrontendDir | Out-Null

    Write-Host ""
    Write-OK "========================================="
    Write-OK " All services running!"
    Write-OK "========================================="
    Write-Host "  UI:          " -NoNewline; Write-Host "http://localhost:3000" -ForegroundColor Cyan
    Write-Host "  API:         " -NoNewline; Write-Host "http://localhost:8000" -ForegroundColor Cyan
    Write-Host "  API Docs:    " -NoNewline; Write-Host "http://localhost:8000/docs" -ForegroundColor Cyan
    Write-Host "  Temporal UI: " -NoNewline; Write-Host "http://localhost:8085" -ForegroundColor Cyan
    Write-Host "  DB:          " -NoNewline; Write-Host "localhost:5436" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Login:       admin@logikality.com / admin123"
    Write-Host ""
    Write-Host "  Apps:"
    Write-Host "    Title Intelligence:          " -NoNewline; Write-Host "http://localhost:3000/apps/title-intelligence" -ForegroundColor Cyan
    Write-Host "    Title Search & Abstracting:  " -NoNewline; Write-Host "http://localhost:3000/apps/title-search" -ForegroundColor Cyan
    Write-Host ""
    Write-Warn "Press Ctrl+C to stop all services"

    # Wait for any child to exit (mirrors bash 'wait')
    while ($true) {
        Start-Sleep -Seconds 2
        $alive = $script:ChildProcs | Where-Object { $_ -and -not $_.HasExited }
        if (-not $alive) {
            Write-Warn "All child processes exited."
            break
        }
    }
}
finally {
    Stop-AllChildren
}
