[CmdletBinding()]
param(
    [ValidateSet('install', 'update', 'uninstall', 'status')]
    [string]$Action = 'install'
)
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    [Console]::Error.WriteLine('Administrator privileges required. Open PowerShell using Run as administrator and run this command again.')
    exit 77
}
$InstallDir = Join-Path $env:ProgramFiles 'MirrorMate'
$Marker = Join-Path $InstallDir '.managed'
$Scripts = Join-Path $InstallDir 'venv\Scripts'
$Python = Join-Path $Scripts 'python.exe'
$Command = Join-Path $Scripts 'mirrormate.exe'
function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Executable" }
}
function Set-ManagerPath([bool]$Add) {
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $parts = @($machinePath -split ';' | Where-Object { $_ -and $_.TrimEnd('\') -ine $Scripts.TrimEnd('\') })
    if ($Add) { $parts += $Scripts }
    [Environment]::SetEnvironmentVariable('Path', ($parts -join ';'), 'Machine')
    if ($Add -and ($env:Path -split ';') -notcontains $Scripts) { $env:Path += ";$Scripts" }
}
try {
    switch ($Action) {
        'status' {
            if (-not (Test-Path -LiteralPath $Marker)) { throw 'MirrorMate is not installed by this manager.' }
            Invoke-Checked $Command @('--version')
            exit 0
        }
        'uninstall' {
            if (-not (Test-Path -LiteralPath $Marker)) { throw 'No managed installation found; nothing removed.' }
            Set-ManagerPath $false
            Remove-Item -LiteralPath $InstallDir -Recurse -Force
            Write-Host 'MirrorMate uninstalled. User configuration and backups were preserved.'
            exit 0
        }
    }
    if ((Test-Path -LiteralPath $InstallDir) -and -not (Test-Path -LiteralPath $Marker)) {
        throw "Refusing to overwrite an unmanaged directory: $InstallDir"
    }
    $Launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    $PythonArgs = @()
    if ($Launcher) { $PythonArgs = @('-3') }
    else { $Launcher = Get-Command python.exe -ErrorAction SilentlyContinue }
    if (-not $Launcher) { throw 'Python 3.10+ with venv and pip is required. Install Python first.' }
    Invoke-Checked $Launcher.Source ($PythonArgs + @('-c', 'import sys; raise SystemExit(sys.version_info < (3, 10))'))
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    New-Item -ItemType File -Path $Marker -Force | Out-Null
    Invoke-Checked $Launcher.Source ($PythonArgs + @('-m', 'venv', (Join-Path $InstallDir 'venv')))
    $Repository = if ($env:MIRRORMATE_REPOSITORY) { $env:MIRRORMATE_REPOSITORY } else { 'free-programmers/MirrorMate' }
    Invoke-Checked $Python @('-m', 'pip', 'install', '--upgrade', '--force-reinstall', '--no-cache-dir', "https://github.com/$Repository/archive/refs/heads/main.zip")
    Set-ManagerPath $true
    Invoke-Checked $Command @('--version')
    Write-Host 'MirrorMate installed. Open a new terminal and run mirrormate as your normal user.'
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
