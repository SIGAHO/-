$ErrorActionPreference = 'Stop'
$runtime = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = (Get-Command python -ErrorAction Stop).Source
$testRoot = Join-Path $runtime ("work\unit-tests\" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $testRoot 'tmp') -Force | Out-Null
$savedBreaktail = @{}
Get-ChildItem Env: | Where-Object Name -Like 'BREAKTAIL_*' | ForEach-Object {
    $savedBreaktail[$_.Name] = $_.Value
    Remove-Item -LiteralPath ("Env:" + $_.Name)
}
$savedOther = @{}
foreach ($name in @('TEMP', 'TMP', 'PYTHONPATH', 'PYTHONUTF8', 'PYTHONIOENCODING')) {
    $savedOther[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$failure = 0
try {
    $env:BREAKTAIL_DATA_ROOT = $testRoot
    $env:TEMP = Join-Path $testRoot 'tmp'
    $env:TMP = $env:TEMP
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONPATH = $runtime
    & $python -m unittest discover -s $runtime -p 'test_*.py' -v
    if ($LASTEXITCODE -ne 0) { $failure = 1 }
    & $python -m unittest discover -s (Join-Path $runtime 'tests') -v
    if ($LASTEXITCODE -ne 0) { $failure = 1 }
}
finally {
    Get-ChildItem Env: | Where-Object Name -Like 'BREAKTAIL_*' | ForEach-Object {
        Remove-Item -LiteralPath ("Env:" + $_.Name)
    }
    foreach ($name in $savedBreaktail.Keys) { [Environment]::SetEnvironmentVariable($name, $savedBreaktail[$name], 'Process') }
    foreach ($name in $savedOther.Keys) { [Environment]::SetEnvironmentVariable($name, $savedOther[$name], 'Process') }
    Write-Host "Isolated test evidence retained: $testRoot"
}
exit $failure
