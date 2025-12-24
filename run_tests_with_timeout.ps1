$job = Start-Job -ScriptBlock {
    Set-Location "C:\Users\Mateusz\source\repos\llm-interactive-proxy"
    & "./.venv/Scripts/python.exe" -m pytest -v --tb=short -m "not testmon_cache" 2>&1
}

$timeout = 300
Wait-Job $job -Timeout $timeout | Out-Null

$output = Receive-Job $job
Stop-Job $job -ErrorAction SilentlyContinue
Remove-Job $job -ErrorAction SilentlyContinue

$output | Out-File -FilePath "test_output.txt" -Encoding UTF8
Write-Host "Test output saved to test_output.txt"
