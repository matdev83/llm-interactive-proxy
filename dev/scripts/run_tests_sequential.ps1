$job = Start-Job -ScriptBlock {
    Set-Location "C:\Users\Mateusz\source\repos\llm-interactive-proxy"
    & "./.venv/Scripts/python.exe" -m pytest --tb=short --timeout=60 --timeout-method=thread -p no:xdist 2>&1
}

$timeout = 3600
Wait-Job $job -Timeout $timeout | Out-Null

$output = Receive-Job $job
Stop-Job $job -ErrorAction SilentlyContinue
Remove-Job $job -ErrorAction SilentlyContinue

$output | Out-File -FilePath "test_output_sequential.txt" -Encoding UTF8
Write-Host "Test output saved to test_output_sequential.txt"

# Extract summary
$summary = $output | Select-String -Pattern "====.*passed.*====" | Select-Object -Last 1
Write-Host $summary
