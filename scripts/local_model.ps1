param([string]$Model = 'qwen3:1.7b')
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDirectory
$runtimeDirectory = Join-Path $projectDirectory '.runtime'
$ollamaExecutable = Join-Path $runtimeDirectory 'ollama\ollama.exe'
$env:OLLAMA_MODELS = Join-Path $runtimeDirectory 'models'
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_NOPRUNE = '1'
if (-not (Test-Path -LiteralPath $ollamaExecutable)) {
    New-Item -ItemType Directory -Force -Path $runtimeDirectory | Out-Null
    $runtimeArchive = Join-Path $runtimeDirectory 'ollama.zip'
    Write-Output 'Downloading portable Ollama (about 1.4 GB). No system installation or API key required.'
    & curl.exe -L --fail --silent --show-error 'https://github.com/ollama/ollama/releases/download/v0.40.2/ollama-windows-amd64.zip' -o $runtimeArchive
    if ($LASTEXITCODE -ne 0) { throw 'Ollama download failed' }
    $expectedDigest = 'E29AD1D5063DD4B54B2492D9B00ADAB2CFF9621BFA654B6C92AA8D6F1FDFE7FC'
    if ((Get-FileHash -LiteralPath $runtimeArchive -Algorithm SHA256).Hash -ne $expectedDigest) { throw 'Runtime checksum mismatch' }
    Expand-Archive -LiteralPath $runtimeArchive -DestinationPath (Join-Path $runtimeDirectory 'ollama') -Force
    Remove-Item -LiteralPath $runtimeArchive
}
$serviceReady = $false
try { $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags'; $serviceReady = $true } catch { }
if (-not $serviceReady) {
    $service = Start-Process -FilePath $ollamaExecutable -ArgumentList 'serve' -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDirectory 'ollama.stdout.log') -RedirectStandardError (Join-Path $runtimeDirectory 'ollama.stderr.log')
    $service.Id | Set-Content -LiteralPath (Join-Path $runtimeDirectory 'ollama.pid')
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try { $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags'; $serviceReady = $true; break } catch { Start-Sleep -Seconds 1 }
    }
}
if (-not $serviceReady) { throw 'Local model service did not start. Read .runtime/ollama.stderr.log.' }
& $ollamaExecutable pull $Model
if ($LASTEXITCODE -ne 0) { throw 'Model download failed' }
Write-Output 'Local model is ready. Keep the service running while using AgentGate.'

