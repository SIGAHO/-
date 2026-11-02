$ErrorActionPreference = 'Stop'
$runtime = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $runtime
$env:BREAKTAIL_DATA_ROOT = Join-Path $root 'data'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$python = (Get-Command python -ErrorAction Stop).Source
Write-Host "Breaktail runtime: $runtime"
Write-Host "Breaktail DATA_ROOT: $env:BREAKTAIL_DATA_ROOT"
& $python (Join-Path $runtime 'breaktail_orchestrator.py') chat
exit $LASTEXITCODE
