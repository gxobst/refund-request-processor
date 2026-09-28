<#
.SYNOPSIS
    Launcher script for the AI Refund Request Processor (Backend + Frontend).

.DESCRIPTION
    Starts the FastAPI multi-agent backend and Vite React frontend using pure PowerShell.
    Supports running all services, individual services, tests, seeding, and setup.

.PARAMETER Mode
    Execution mode: 'all' (default), 'backend', 'frontend', 'setup', 'seed', 'test', 'test-backend', 'test-frontend', 'build', 'help'.

.PARAMETER HostAddress
    Host IP address to bind services to. Default: 127.0.0.1.

.PARAMETER BackendPort
    Port for the FastAPI backend server. Default: 8000.

.PARAMETER FrontendPort
    Port for the Vite frontend server. Default: 5173.

.PARAMETER NewWindows
    Launch backend and frontend in separate dedicated PowerShell windows.

.PARAMETER NoBrowser
    Do not automatically open the browser when launching services.

.EXAMPLE
    .\start.ps1
    Starts both backend and frontend in the current terminal.

.EXAMPLE
    .\start.ps1 -Mode backend
    Runs only the FastAPI backend server.

.EXAMPLE
    .\start.ps1 -Mode setup
    Installs backend/frontend dependencies and seeds mock DynamoDB orders.

.EXAMPLE
    .\start.ps1 -NewWindows
    Launches backend and frontend in separate PowerShell windows.
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("all", "backend", "frontend", "setup", "seed", "test", "test-backend", "test-frontend", "build", "help")]
    [string]$Mode = "all",

    [Parameter()]
    [string]$HostAddress = "127.0.0.1",

    [Parameter()]
    [int]$BackendPort = 8000,

    [Parameter()]
    [int]$FrontendPort = 5173,

    [Parameter()]
    [switch]$NewWindows,

    [Parameter()]
    [switch]$NoBrowser
)

# Root directory of repository
$RootDir = $PSScriptRoot
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"

# Ensure environment Path includes machine and user paths + local tool directories
$localBin = Join-Path $env:USERPROFILE ".local\bin"
$localNode = Join-Path $env:LOCALAPPDATA "node"
$pathsToAdd = @($localBin, $localNode)

foreach ($p in $pathsToAdd) {
    if ((Test-Path $p) -and ($env:Path -notlike "*$p*")) {
        $env:Path = "$p;$env:Path"
    }
}

# Recursively terminate a process and all its children
function Stop-ProcessTree([int]$ParentId) {
    try {
        Get-CimInstance Win32_Process -Filter "ParentProcessId = $ParentId" -ErrorAction SilentlyContinue | ForEach-Object {
            Stop-ProcessTree -ParentId $_.ProcessId
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Stop-Process -Id $ParentId -Force -ErrorAction SilentlyContinue
    } catch {
        # Process may have already exited
    }
}

# Verify required executables
function Assert-CommandAvailable([string]$CommandName, [string]$InstallHint) {
    $cmd = Get-Command $CommandName -ErrorAction SilentlyContinue
    if (-not $cmd) {
        Write-Host " [ERROR] Required command '$CommandName' was not found in PATH." -ForegroundColor Red
        Write-Host "         $InstallHint" -ForegroundColor Yellow
        exit 1
    }
}

# Display Help
if ($Mode -eq "help") {
    Write-Host ""
    Write-Host "=================================================================" -ForegroundColor Cyan
    Write-Host "            AI REFUND REQUEST PROCESSOR - START SCRIPT           " -ForegroundColor Cyan
    Write-Host "=================================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Usage:" -ForegroundColor Yellow
    Write-Host "  .\start.ps1 [-Mode <mode>] [-HostAddress <ip>] [-BackendPort <port>] [-FrontendPort <port>] [-NewWindows] [-NoBrowser]"
    Write-Host ""
    Write-Host "Available Modes:" -ForegroundColor Yellow
    Write-Host "  all            (Default) Launch both FastAPI backend and Vite frontend" -ForegroundColor Green
    Write-Host "  backend        Run only the FastAPI backend server (port 8000)" -ForegroundColor Green
    Write-Host "  frontend       Run only the Vite frontend dev server (port 5173)" -ForegroundColor Green
    Write-Host "  setup          Install uv/python deps, npm packages, and seed DynamoDB" -ForegroundColor Green
    Write-Host "  seed           Seed mock order records into DynamoDB" -ForegroundColor Green
    Write-Host "  test           Run all backend (pytest) and frontend (vitest) tests" -ForegroundColor Green
    Write-Host "  test-backend   Run backend test suite only" -ForegroundColor Green
    Write-Host "  test-frontend  Run frontend test suite only" -ForegroundColor Green
    Write-Host "  build          Build production frontend bundle into frontend/dist" -ForegroundColor Green
    Write-Host "  help           Display this help screen" -ForegroundColor Green
    Write-Host ""
    Write-Host "Examples:" -ForegroundColor Yellow
    Write-Host "  .\start.ps1                         # Start backend + frontend"
    Write-Host "  .\start.ps1 -NewWindows             # Start backend + frontend in separate windows"
    Write-Host "  .\start.ps1 -Mode backend           # Start only backend"
    Write-Host "  .\start.ps1 -Mode setup             # Install dependencies and seed mock DB"
    Write-Host "  .\start.ps1 -Mode test              # Run full test suite"
    Write-Host ""
    exit 0
}

# Mode: Setup
if ($Mode -eq "setup") {
    Write-Host "--- [SETUP] Installing Backend Dependencies via uv ---" -ForegroundColor Cyan
    Assert-CommandAvailable "uv" "Install uv via: powershell -ExecutionPolicy ByPass -c 'irm https://astral.sh/uv/install.ps1 | iex'"
    Push-Location $BackendDir
    try {
        uv sync
    } finally {
        Pop-Location
    }

    Write-Host "`n--- [SETUP] Installing Frontend Dependencies via npm ---" -ForegroundColor Cyan
    Assert-CommandAvailable "npm" "Install Node.js from https://nodejs.org"
    Push-Location $FrontendDir
    try {
        npm install
    } finally {
        Pop-Location
    }

    Write-Host "`n--- [SETUP] Seeding DynamoDB Mock Orders ---" -ForegroundColor Cyan
    Push-Location $BackendDir
    try {
        uv run python -m app.db.seed
    } finally {
        Pop-Location
    }

    Write-Host "`n[SUCCESS] Setup complete! You can now run .\start.ps1 to start the application." -ForegroundColor Green
    exit 0
}

# Mode: Seed
if ($Mode -eq "seed") {
    Write-Host "--- Seeding DynamoDB Mock Orders ---" -ForegroundColor Cyan
    Assert-CommandAvailable "uv" "Install uv"
    Push-Location $BackendDir
    try {
        uv run python -m app.db.seed
    } finally {
        Pop-Location
    }
    Write-Host "[SUCCESS] Seeding complete." -ForegroundColor Green
    exit 0
}

# Mode: Test
if ($Mode -eq "test" -or $Mode -eq "test-backend" -or $Mode -eq "test-frontend") {
    if ($Mode -eq "test" -or $Mode -eq "test-backend") {
        Write-Host "--- Running Backend Tests (pytest) ---" -ForegroundColor Cyan
        Assert-CommandAvailable "uv" "Install uv"
        Push-Location $BackendDir
        try {
            uv run pytest
            if ($LASTEXITCODE -ne 0) {
                Write-Host "[FAIL] Backend tests failed." -ForegroundColor Red
                if ($Mode -eq "test-backend") { exit $LASTEXITCODE }
            } else {
                Write-Host "[PASS] Backend tests passed." -ForegroundColor Green
            }
        } finally {
            Pop-Location
        }
    }

    if ($Mode -eq "test" -or $Mode -eq "test-frontend") {
        Write-Host "`n--- Running Frontend Tests (vitest) ---" -ForegroundColor Cyan
        Assert-CommandAvailable "npm" "Install npm"
        Push-Location $FrontendDir
        try {
            npm run test -- --run
            if ($LASTEXITCODE -ne 0) {
                Write-Host "[FAIL] Frontend tests failed." -ForegroundColor Red
                exit $LASTEXITCODE
            } else {
                Write-Host "[PASS] Frontend tests passed." -ForegroundColor Green
            }
        } finally {
            Pop-Location
        }
    }
    exit 0
}

# Mode: Build
if ($Mode -eq "build") {
    Write-Host "--- Building Frontend Production Assets ---" -ForegroundColor Cyan
    Assert-CommandAvailable "npm" "Install npm"
    Push-Location $FrontendDir
    try {
        npm run build
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[SUCCESS] Frontend build completed in frontend/dist." -ForegroundColor Green
        }
    } finally {
        Pop-Location
    }
    exit 0
}

# Mode: Backend Only
if ($Mode -eq "backend") {
    Write-Host "=================================================================" -ForegroundColor Cyan
    Write-Host "             STARTING FASTAPI BACKEND SERVER                     " -ForegroundColor Cyan
    Write-Host "=================================================================" -ForegroundColor Cyan
    Write-Host "  URL:     http://$HostAddress`:$BackendPort" -ForegroundColor Green
    Write-Host "  Docs:    http://$HostAddress`:$BackendPort/docs" -ForegroundColor Green
    Write-Host "  Health:  http://$HostAddress`:$BackendPort/health" -ForegroundColor Green
    Write-Host "=================================================================" -ForegroundColor Cyan
    Write-Host "Press Ctrl+C to terminate backend server.`n" -ForegroundColor Yellow

    Assert-CommandAvailable "uv" "Install uv"
    Push-Location $BackendDir
    try {
        uv run uvicorn app.main:app --host $HostAddress --port $BackendPort --reload
    } finally {
        Pop-Location
    }
    exit 0
}

# Mode: Frontend Only
if ($Mode -eq "frontend") {
    Write-Host "=================================================================" -ForegroundColor Cyan
    Write-Host "               STARTING VITE FRONTEND SERVER                     " -ForegroundColor Cyan
    Write-Host "=================================================================" -ForegroundColor Cyan
    Write-Host "  URL:     http://$HostAddress`:$FrontendPort" -ForegroundColor Green
    Write-Host "=================================================================" -ForegroundColor Cyan
    Write-Host "Press Ctrl+C to terminate frontend server.`n" -ForegroundColor Yellow

    Assert-CommandAvailable "npm" "Install npm"
    Push-Location $FrontendDir
    try {
        npm run dev -- --host $HostAddress --port $FrontendPort
    } finally {
        Pop-Location
    }
    exit 0
}

# Mode: All (Backend + Frontend)
if ($Mode -eq "all") {
    Assert-CommandAvailable "uv" "Install uv via: powershell -ExecutionPolicy ByPass -c 'irm https://astral.sh/uv/install.ps1 | iex'"
    Assert-CommandAvailable "npm" "Install Node.js from https://nodejs.org"

    # Pre-flight check: ensure dependencies are installed
    if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
        Write-Host "Frontend node_modules not detected. Installing..." -ForegroundColor Yellow
        Push-Location $FrontendDir
        try { npm install } finally { Pop-Location }
    }

    Write-Host "=================================================================" -ForegroundColor Cyan
    Write-Host "      STARTING AI REFUND REQUEST PROCESSOR (FULL STACK)         " -ForegroundColor Cyan
    Write-Host "=================================================================" -ForegroundColor Cyan
    Write-Host "  Backend API:   http://$HostAddress`:$BackendPort" -ForegroundColor Green
    Write-Host "  API Docs:      http://$HostAddress`:$BackendPort/docs" -ForegroundColor Green
    Write-Host "  Frontend UI:   http://$HostAddress`:$FrontendPort" -ForegroundColor Green
    Write-Host "=================================================================" -ForegroundColor Cyan

    if ($NewWindows) {
        # Launch each in a separate PowerShell window
        Write-Host "Launching Backend and Frontend in separate PowerShell windows..." -ForegroundColor Yellow
        
        $backendCmd = "Set-Location '$BackendDir'; uv run uvicorn app.main:app --host $HostAddress --port $BackendPort --reload"
        Start-Process pwsh -ArgumentList "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = 'Refund Processor - Backend'; $backendCmd"

        $frontendCmd = "Set-Location '$FrontendDir'; npm run dev -- --host $HostAddress --port $FrontendPort"
        Start-Process pwsh -ArgumentList "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = 'Refund Processor - Frontend'; $frontendCmd"

        if (-not $NoBrowser) {
            Start-Sleep -Seconds 2
            Start-Process "http://$HostAddress`:$FrontendPort"
        }
        Write-Host "`nBoth processes launched. Close their respective windows to stop." -ForegroundColor Green
        exit 0
    }

    # Single-terminal execution with background backend and foreground frontend
    Write-Host "Starting Backend as background process..." -ForegroundColor Yellow
    $backendProcess = Start-Process `
        -FilePath "uv" `
        -ArgumentList "run", "uvicorn", "app.main:app", "--host", $HostAddress, "--port", $BackendPort, "--reload" `
        -WorkingDirectory $BackendDir `
        -PassThru `
        -NoNewWindow

    if (-not $backendProcess -or $backendProcess.HasExited) {
        Write-Host "[ERROR] Failed to start backend server." -ForegroundColor Red
        exit 1
    }
    Write-Host "  Backend running with PID: $($backendProcess.Id)" -ForegroundColor DarkGray

    # Wait 2 seconds for backend initialization
    Start-Sleep -Seconds 2

    if (-not $NoBrowser) {
        Write-Host "Opening browser at http://$HostAddress`:$FrontendPort..." -ForegroundColor Yellow
        Start-Process "http://$HostAddress`:$FrontendPort" -ErrorAction SilentlyContinue
    }

    Write-Host "`nStarting Frontend server in foreground. Press Ctrl+C to terminate both servers.`n" -ForegroundColor Cyan

    Push-Location $FrontendDir
    try {
        # Run frontend in current process; on Ctrl+C, PowerShell triggers finally block
        npm run dev -- --host $HostAddress --port $FrontendPort
    } finally {
        Write-Host "`nShutting down backend and frontend processes..." -ForegroundColor Yellow
        if ($backendProcess -and -not $backendProcess.HasExited) {
            Stop-ProcessTree -ParentId $backendProcess.Id
            Write-Host "  Backend process (PID $($backendProcess.Id)) and child processes stopped." -ForegroundColor DarkGray
        }
        Pop-Location
        Write-Host "All services stopped cleanly." -ForegroundColor Green
    }
}
