param([switch]$SafeMode, [switch]$DryRun)
$ErrorActionPreference = 'Stop'
$runtime = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$python = (Get-Command python -ErrorAction Stop).Source
$options = @('--config', (Join-Path $runtime 'orchestrator.json'))
if ($SafeMode) { $options += '--safe-mode' }
if ($DryRun) { $options += '--dry-run' }
& $python (Join-Path $runtime 'breaktail_orchestrator.py') @options daemon
exit $LASTEXITCODE
