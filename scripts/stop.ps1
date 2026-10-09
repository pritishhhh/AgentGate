$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $projectDirectory 'data\server.pid'
if (-not (Test-Path -LiteralPath $pidFile)) { throw 'No recorded background server process. Use Ctrl+C for a foreground server.' }
$gatewayProcessId = [int](Get-Content -LiteralPath $pidFile)
$gatewayProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $gatewayProcessId"
$expectedExecutable = Join-Path $projectDirectory '.venv\Scripts\python.exe'
if ($gatewayProcess -and $gatewayProcess.ExecutablePath -eq $expectedExecutable -and $gatewayProcess.CommandLine -match 'agentgate.cli.*serve') {
    Stop-Process -Id $gatewayProcessId
    Write-Output 'Stopped the recorded AgentGate background server.'
} elseif ($gatewayProcess) { throw 'Recorded PID belongs to another command; refusing to stop it.' }

