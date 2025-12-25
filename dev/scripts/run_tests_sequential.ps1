param(
    [int]$TimeoutSeconds = 3600,
    [string]$OutputPath = "test_output_sequential.txt"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\\Scripts\\python.exe"
if (-not (Test-Path $python)) {
    throw "Python not found at: $python"
}

function Quote-Arg([string]$arg) {
    if ($arg -match "[\\s\"&|<>^]") {
        return '"' + ($arg -replace '"', '""') + '"'
    }
    return $arg
}

$args = @(
    "-m", "pytest",
    "--tb=short",
    "-p", "no:timeout",
    "-p", "no:xdist"
)

Remove-Item -Path $OutputPath -ErrorAction SilentlyContinue

$cmdLine = "$(Quote-Arg $python) $(($args | ForEach-Object { Quote-Arg $_ }) -join ' ') 1> $(Quote-Arg $OutputPath) 2>&1"
$proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $cmdLine -PassThru -NoNewWindow

$exited = $proc.WaitForExit($TimeoutSeconds * 1000)
if (-not $exited) {
    & taskkill /PID $proc.Id /T /F | Out-Null
    Write-Host "Timed out after $TimeoutSeconds seconds; see $OutputPath"
    exit 1
}

Write-Host "Test output saved to $OutputPath"
$summary = Get-Content $OutputPath | Select-String -Pattern "====.*passed.*====" | Select-Object -Last 1
if ($summary) {
    Write-Host $summary.Line
}
