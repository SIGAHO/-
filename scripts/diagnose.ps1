param([switch]$ModelSmoke)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = (Get-Command python -ErrorAction Stop).Source }
$diagnostics = Join-Path $repoRoot 'work\diagnose'
New-Item -ItemType Directory -Force -Path $diagnostics | Out-Null
Write-Host ('Console input/output: {0}/{1}; pipe: {2}' -f [Console]::InputEncoding.WebName, [Console]::OutputEncoding.WebName, $OutputEncoding.WebName)
$checks = @(
    @{Name='encoding'; Args=@('-c', 'import sys,locale; print(sys.stdin.encoding,sys.stdout.encoding,sys.stderr.encoding,locale.getpreferredencoding(False)); print(''日本語😀ABC１２３'')')},
    @{Name='unit'; Args=@('-m','unittest','discover','-s','tests','-v')},
    @{Name='behavior'; Args=@('experiments/run_all.py','--no-write')},
    @{Name='demo'; Args=@('demo.py')}
)
if ($ModelSmoke) { $checks += @{Name='model'; Args=@('scripts/model_smoke.py')} }
$failed = $false
$summary = @()
foreach ($check in $checks) {
    # ProcessStartInfo avoids PowerShell wrapping normal stderr in NativeCommandError.
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $python
    $info.WorkingDirectory = $repoRoot
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = $utf8
    $info.StandardErrorEncoding = $utf8
    $info.Arguments = (($check.Args | ForEach-Object { '"' + ($_ -replace '(\\*)"', '$1$1\"' -replace '(\\+)$', '$1$1') + '"' }) -join ' ')
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $info
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $outText = $stdout.Result
    $errText = $stderr.Result
    [IO.File]::WriteAllText((Join-Path $diagnostics ($check.Name+'.stdout.log')), $outText, $utf8)
    [IO.File]::WriteAllText((Join-Path $diagnostics ($check.Name+'.stderr.log')), $errText, $utf8)
    $status = if ($process.ExitCode -eq 0) { 'PASS' } else { 'FAIL' }
    if ($process.ExitCode -ne 0) { $failed = $true }
    $summary += [pscustomobject]@{check=$check.Name;status=$status;exitCode=$process.ExitCode}
    Write-Host ('{0}: {1} (ExitCode {2})' -f $check.Name, $status, $process.ExitCode)
    if ($check.Name -eq 'demo') { Write-Host ('Demo output: '+(Join-Path $diagnostics 'demo.stdout.log')) } else { Write-Host $outText }
    if ($check.Name -eq 'unit') { Write-Host (($errText -split "`n" | Select-Object -Last 5) -join "`n") }
    if ($process.ExitCode -ne 0) { Write-Host $errText }
    $process.Dispose()
}
[IO.File]::WriteAllText((Join-Path $diagnostics 'summary.json'), (ConvertTo-Json -InputObject $summary), $utf8)
if ($failed) { Write-Host 'FINAL: FAIL'; exit 1 }
Write-Host 'FINAL: PASS'
exit 0
