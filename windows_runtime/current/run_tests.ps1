$ErrorActionPreference = 'Stop'
$runtime = Split-Path -Parent $MyInvocation.MyCommand.Path
$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("breaktail-phase77-tests-" + [guid]::NewGuid().ToString('N'))
$env:BREAKTAIL_DATA_ROOT = $testRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$python = (Get-Command python -ErrorAction Stop).Source
try {
    & $python -m unittest discover -s $runtime -p 'test_*.py' -v
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
}
