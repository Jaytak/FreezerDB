$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$systemPython = Get-Command python -ErrorAction SilentlyContinue

if ($systemPython) {
    & $systemPython.Source (Join-Path $projectRoot "server.py")
} elseif (Test-Path $bundledPython) {
    & $bundledPython (Join-Path $projectRoot "server.py")
} else {
    Write-Error "Python 3.10 or newer is required. Install Python or run this inside Codex with the bundled runtime available."
}
