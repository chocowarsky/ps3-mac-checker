param(
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$RawBase = 'https://raw.githubusercontent.com/chocowarsky/ps3-mac-manager/main'
$DefaultInstallDir = Join-Path $env:LOCALAPPDATA 'Programs\ps3-mac-manager'

function Find-WorkingPython {
    $candidates = @(
        @{ Exe = 'py'; Args = @('-3') },
        @{ Exe = 'python'; Args = @() },
        @{ Exe = 'python3'; Args = @() }
    )

    $searchRoots = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*\python.exe'),
        (Join-Path $env:ProgramFiles 'Python3*\python.exe')
    )
    foreach ($pattern in $searchRoots) {
        Get-Item -Path $pattern -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | ForEach-Object {
            $candidates += @{ Exe = $_.FullName; Args = @() }
        }
    }

    foreach ($cand in $candidates) {
        try {
            $checkArgs = $cand.Args + @('-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)')
            & $cand.Exe @checkArgs *> $null
            if ($LASTEXITCODE -eq 0) {
                return $cand
            }
        } catch {
            continue
        }
    }
    return $null
}

Write-Host '=== Installing PS3 Controller MAC Manager (Windows) ===' -ForegroundColor Cyan

# 1. Locate or auto-install Python 3.8+
$python = Find-WorkingPython
if (-not $python) {
    Write-Host '[*] Python 3.8+ not found. Checking winget...' -ForegroundColor Yellow
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host '[*] Installing Python 3.12 via winget...' -ForegroundColor Yellow
        & winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
        $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
        $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
        $env:Path = "$machinePath;$userPath"
        $python = Find-WorkingPython
    }
}

if (-not $python) {
    Write-Host '[!] Could not find or auto-install Python 3.8+.' -ForegroundColor Red
    Write-Host '    Download Python 3.10+ from https://www.python.org/downloads/ and check "Add Python to PATH".'
    exit 1
}

Write-Host "[+] Using Python: $($python.Exe) $($python.Args -join ' ')" -ForegroundColor Green

# 2. Install files locally or from GitHub
$LocalScriptRoot = $PSScriptRoot
if ($LocalScriptRoot -and (Test-Path (Join-Path $LocalScriptRoot 'ps3_mac_manager.py'))) {
    $InstallDir = $LocalScriptRoot
    Write-Host "[*] Using local repository at $InstallDir"
} else {
    $InstallDir = $DefaultInstallDir
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    Write-Host "[*] Downloading PS3 MAC Manager to $InstallDir..."
    foreach ($file in @('ps3_mac_manager.py', 'ps3_mac_manager.bat', 'LICENSE', 'README.md')) {
        $dest = Join-Path $InstallDir $file
        Invoke-WebRequest -Uri "$RawBase/$file" -OutFile $dest -UseBasicParsing
    }
}

# 3. Create ps3-mac-manager.cmd shim so beginners can run `ps3-mac-manager` anywhere
$CmdShim = Join-Path $InstallDir 'ps3-mac-manager.cmd'
Set-Content -Path $CmdShim -Encoding ASCII -Value "@echo off`r`ncall `"%~dp0ps3_mac_manager.bat`" %*`r`n"

# 4. Add InstallDir to User PATH idempotently
$CurrentUserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $CurrentUserPath) { $CurrentUserPath = '' }
$PathParts = $CurrentUserPath -split ';' | Where-Object { $_ -and $_.Trim() -ne '' }
if ($PathParts -notcontains $InstallDir) {
    $NewUserPath = ($PathParts + $InstallDir) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $NewUserPath, 'User')
    $env:Path = "$env:Path;$InstallDir"
    Write-Host "[+] Added $InstallDir to User PATH." -ForegroundColor Green
}

# 5. Create Desktop & Start Menu shortcuts
try {
    $WshShell = New-Object -ComObject WScript.Shell
    $BatchPath = Join-Path $InstallDir 'ps3_mac_manager.bat'
    $IconPath = "$env:SystemRoot\System32\joy.cpl,0"

    $DesktopDir = [Environment]::GetFolderPath('Desktop')
    if ($DesktopDir -and (Test-Path $DesktopDir)) {
        $DesktopShortcut = $WshShell.CreateShortcut((Join-Path $DesktopDir 'PS3 MAC Manager.lnk'))
        $DesktopShortcut.TargetPath = $BatchPath
        $DesktopShortcut.WorkingDirectory = $InstallDir
        $DesktopShortcut.Description = 'Read, Change, Pair & Manage PS3 Controller MAC Addresses'
        $DesktopShortcut.IconLocation = $IconPath
        $DesktopShortcut.Save()
    }

    $StartMenuDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    if (Test-Path $StartMenuDir) {
        $StartShortcut = $WshShell.CreateShortcut((Join-Path $StartMenuDir 'PS3 MAC Manager.lnk'))
        $StartShortcut.TargetPath = $BatchPath
        $StartShortcut.WorkingDirectory = $InstallDir
        $StartShortcut.Description = 'Read, Change, Pair & Manage PS3 Controller MAC Addresses'
        $StartShortcut.IconLocation = $IconPath
        $StartShortcut.Save()
    }
    Write-Host '[+] Created Desktop and Start Menu shortcuts ("PS3 MAC Manager").' -ForegroundColor Green
} catch {
    Write-Host "[!] Could not create shortcuts: $_" -ForegroundColor Yellow
}

Write-Host ''
Write-Host '=== Installation Complete! ===' -ForegroundColor Cyan
Write-Host 'Run "ps3-mac-manager" in Command Prompt / PowerShell, or double-click "PS3 MAC Manager" on your Desktop.'

if (-not $NoLaunch -and [Environment]::UserInteractive) {
    Write-Host ''
    Write-Host '[*] Launching PS3 MAC Manager...' -ForegroundColor Cyan
    $RunArgs = $python.Args + @((Join-Path $InstallDir 'ps3_mac_manager.py'))
    & $python.Exe @RunArgs
}
