param([string]$ConversationId='atashi',[string]$DataRoot)
$ErrorActionPreference='Stop'
$runtime=Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $DataRoot) { $DataRoot=Join-Path (Split-Path -Parent $runtime) 'data' }
$savedUtf8=$env:PYTHONUTF8
$savedEncoding=$env:PYTHONIOENCODING
try {
    $env:PYTHONUTF8='1'
    $env:PYTHONIOENCODING='utf-8'
    & python (Join-Path $runtime 'breaktail_orchestrator.py') --data-root $DataRoot chat --conversation-id $ConversationId --text '/persona atashi'
    if ($LASTEXITCODE -ne 0) { throw '人格の切替に失敗しました。' }
    Write-Host 'Breaktail あたし版。終了は /exit、人格解除は /persona off。'
    & python (Join-Path $runtime 'breaktail_orchestrator.py') --data-root $DataRoot chat --conversation-id $ConversationId
    $exitStatus=$LASTEXITCODE
}
finally {
    $env:PYTHONUTF8=$savedUtf8
    $env:PYTHONIOENCODING=$savedEncoding
}
exit $exitStatus
