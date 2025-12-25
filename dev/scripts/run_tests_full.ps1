param(
    [int]$Workers = 4,
    [int]$BatchSize = 40,
    [int]$BatchTimeoutSeconds = 900,
    [int]$MaxBatches = 0,
    [string]$OutputPath = "test_output_full.txt"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python not found at: $python"
}

function Quote-Arg([string]$arg) {
    if ($arg -match '[\s"&|<>^]') {
        return '"' + ($arg -replace '"', '""') + '"'
    }
    return $arg
}

function Invoke-CmdWithTimeout([string]$cmdLine, [int]$timeoutSeconds) {
    $proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $cmdLine -PassThru -NoNewWindow
    try {
        Wait-Process -Id $proc.Id -Timeout $timeoutSeconds -ErrorAction Stop
    } catch {
        & taskkill /PID $proc.Id /T /F | Out-Null
        return @{
            TimedOut = $true
            ExitCode = 124
        }
    }

    $proc.Refresh()
    $exitCode = $null
    try {
        $exitCode = [int]$proc.ExitCode
    } catch {
        $exitCode = $null
    }
    return @{
        TimedOut = $false
        ExitCode = $exitCode
    }
}

function Get-TestFiles {
    $testsRoot = Join-Path $repoRoot "tests"
    $files = Get-ChildItem -Path $testsRoot -Recurse -File | Where-Object {
        ($_.Name -like "test_*.py" -or $_.Name -like "*_test.py") -and ($_.FullName -notmatch "\\__pycache__\\")
    }
    return $files | Sort-Object FullName | ForEach-Object { $_.FullName.Substring($repoRoot.Length + 1) }
}

function Write-Log([string]$text) {
    $text | Out-File -FilePath $OutputPath -Append -Encoding UTF8
}

function Run-Pytest([string[]]$paths, [string]$label) {
    $args = @(
        "-m", "pytest",
        "--tb=short",
        "-p", "no:timeout",
        "--max-worker-restart=50",
        "-n", $Workers,
        "--dist=loadfile"
    ) + $paths

    $quoted = ($args | ForEach-Object { Quote-Arg $_ }) -join " "
    $cmdLine = "$(Quote-Arg $python) $quoted 1>> $(Quote-Arg $OutputPath) 2>&1"

    Write-Log ""
    Write-Log ("=" * 100)
    Write-Log ("[runner] {0}" -f $label)
    Write-Log ("[runner] cmd: {0}" -f $cmdLine)
    Write-Log ("=" * 100)

    return Invoke-CmdWithTimeout -cmdLine $cmdLine -timeoutSeconds $BatchTimeoutSeconds
}

function Run-BatchRecursive([string[]]$paths, [int]$depth) {
    $label = "batch depth=$depth files=$($paths.Count)"
    $indent = "  " * $depth
    Write-Host ("{0}[runner] start: {1}" -f $indent, $label)
    $result = Run-Pytest -paths $paths -label $label

    if (-not $result.TimedOut) {
        $script:AnyFailure = $script:AnyFailure -or ($result.ExitCode -ne 0)
        $exitText = if ($null -eq $result.ExitCode) { "unknown" } else { $result.ExitCode }
        Write-Host ("{0}[runner] done:  {1} (exit={2})" -f $indent, $label, $exitText)
        return
    }

    if ($paths.Count -le 1) {
        Write-Log ("[runner] TIMEOUT: {0}" -f $paths[0])
        $script:TimedOutFiles.Add($paths[0]) | Out-Null
        $script:AnyFailure = $true
        Write-Host ("{0}[runner] TIMEOUT: {1}" -f $indent, $paths[0])
        return
    }

    Write-Host ("{0}[runner] TIMEOUT -> split: {1} files" -f $indent, $paths.Count)
    $mid = [int][Math]::Floor($paths.Count / 2)
    Run-BatchRecursive -paths $paths[0..($mid - 1)] -depth ($depth + 1)
    Run-BatchRecursive -paths $paths[$mid..($paths.Count - 1)] -depth ($depth + 1)
}

Remove-Item -Path $OutputPath -ErrorAction SilentlyContinue
Write-Host ("[runner] output: {0}" -f $OutputPath)
Write-Log ("[runner] repoRoot: {0}" -f $repoRoot)
Write-Log ("[runner] python: {0}" -f $python)
Write-Log ("[runner] workers: {0}, batchSize: {1}, batchTimeoutSeconds: {2}, maxBatches: {3}" -f $Workers, $BatchSize, $BatchTimeoutSeconds, $MaxBatches)

$collectArgs = @(
    "-m", "pytest",
    "--collect-only",
    "-n", "0",
    "-p", "no:timeout"
)
$collectCmd = "$(Quote-Arg $python) $(($collectArgs | ForEach-Object { Quote-Arg $_ }) -join ' ') 2>&1"
Write-Log ""
Write-Log ("=" * 100)
Write-Log "[runner] collecting test count"
Write-Log ("[runner] cmd: {0}" -f $collectCmd)
Write-Log ("=" * 100)

$collectOutput = & $python -m pytest --collect-only -n 0 -p no:timeout 2>&1
$collectOutput | Out-File -FilePath $OutputPath -Append -Encoding UTF8
$collectLine = $collectOutput | Select-String -Pattern "collected\s+\d+\s+items" | Select-Object -Last 1
if ($collectLine) {
    Write-Host $collectLine.Line
} else {
    Write-Host "Could not parse collected items line; see $OutputPath"
}

$testFiles = @(Get-TestFiles)
$totalBatches = if ($testFiles.Count -gt 0) { [int][Math]::Ceiling($testFiles.Count / [double]$BatchSize) } else { 0 }
Write-Host ("Discovered {0} test files (batchSize={1}, batches={2})." -f $testFiles.Count, $BatchSize, $totalBatches)

$script:TimedOutFiles = New-Object System.Collections.Generic.List[string]
$script:AnyFailure = $false

if ($testFiles.Count -eq 0) {
    Write-Host "No test files discovered under ./tests; nothing to run."
    exit 1
}

$batchIndex = 0
for ($i = 0; $i -lt $testFiles.Count; $i += $BatchSize) {
    $batchIndex++
    if ($MaxBatches -gt 0 -and $batchIndex -gt $MaxBatches) {
        Write-Host ("[runner] stopping after maxBatches={0}" -f $MaxBatches)
        break
    }
    $end = [Math]::Min($i + $BatchSize - 1, $testFiles.Count - 1)
    $batch = $testFiles[$i..$end]
    Write-Host ("[runner] batch {0}/{1}: files {2}-{3}" -f $batchIndex, $totalBatches, ($i + 1), ($end + 1))
    Run-BatchRecursive -paths $batch -depth 0
}

if ($script:TimedOutFiles.Count -gt 0) {
    Write-Log ""
    Write-Log ("=" * 100)
    Write-Log "[runner] timed out files"
    Write-Log ("=" * 100)
    $script:TimedOutFiles | ForEach-Object { Write-Log $_ }
    Write-Host ("Timed out files: {0}" -f $script:TimedOutFiles.Count)
}

if ($script:AnyFailure) {
    Write-Host "One or more batches failed or timed out; see $OutputPath"
    exit 1
}

Write-Host "All batches completed without timeouts; see $OutputPath"
