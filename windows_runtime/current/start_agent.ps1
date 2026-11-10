param(
    [string]$Workspace,
    [string]$Task,
    [switch]$AllowExecution,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$runtime = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $runtime
if (-not $Workspace) {
    $Workspace = Join-Path $projectRoot 'projects\agent-work'
    if (-not $DryRun) { New-Item -ItemType Directory -Path $Workspace -Force | Out-Null }
}
if (-not $Task) { $Task = Read-Host 'Breaktailに頼む作業' }
if ([string]::IsNullOrWhiteSpace($Task)) { throw '作業内容を入力してください。' }
if (-not $DryRun -and -not (Test-Path -LiteralPath $Workspace -PathType Container)) {
    throw '作業フォルダーが見つかりません。既存のフォルダーを指定してください。'
}
$arguments = @((Join-Path $runtime 'breaktail_orchestrator.py'))
if ($DryRun) { $arguments += '--dry-run' }
$arguments += @('agent', '--workspace', $Workspace, '--text', $Task)
if ($AllowExecution) { $arguments += '--allow-execution' }
$savedUtf8 = $env:PYTHONUTF8
$savedEncoding = $env:PYTHONIOENCODING
try {
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    Write-Host ('作業フォルダー: ' + $Workspace)
    Write-Host 'Breaktailが作業しています。結果はこの画面と作業記録に残ります。'
    $resultText = & python @arguments
    $exitStatus = $LASTEXITCODE
    if ($exitStatus -ne 0) {
        $resultText | Write-Output
        throw '作業は完了していません。表示された結果と作業記録を確認してください。'
    }
    $result = $resultText | ConvertFrom-Json
    if ($DryRun) { $resultText | Write-Output }
    else {
        Write-Host $result.summary
        Write-Host ('状態: ' + $result.status)
        foreach ($change in $result.changes) { Write-Host ('変更: ' + $change.path) }
        if ($result.syntax_verified) { Write-Host 'コードの構文: 確認済み' }
        if ($result.tests_passed) { Write-Host 'テスト: 成功' }
        elseif (-not $result.execution_enabled) { Write-Host 'コード実行: 今回は無効' }
        Write-Host ('作業記録: ' + $result.journal)
    }
}
finally {
    $env:PYTHONUTF8 = $savedUtf8
    $env:PYTHONIOENCODING = $savedEncoding
}
