# Codex Authentication Management Script
# This script helps you manage ChatGPT/Codex credentials

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet("status", "remove", "verify", "info")]
    [string]$Action = "status"
)

$AuthPath = Join-Path $env:USERPROFILE ".codex\auth.json"

function Show-Usage {
    Write-Host @"

Codex Authentication Manager
=============================

Usage: .\manage_codex_auth.ps1 [ACTION]

Actions:
  status   - Show current authentication status (default)
  remove   - Remove current authentication
  verify   - Verify auth.json format
  info     - Show auth file location and instructions

Examples:
  .\manage_codex_auth.ps1              # Show status
  .\manage_codex_auth.ps1 remove       # Remove current credentials
  .\manage_codex_auth.ps1 verify       # Check if auth.json is valid

"@
}

function Show-Status {
    Write-Host "`n=== Codex Authentication Status ===`n" -ForegroundColor Cyan
    
    if (Test-Path $AuthPath) {
        Write-Host "[OK] auth.json found at: $AuthPath" -ForegroundColor Green
        
        try {
            $auth = Get-Content $AuthPath -Raw | ConvertFrom-Json
            
            if ($auth.tokens -and $auth.tokens.access_token) {
                $tokenLength = $auth.tokens.access_token.Length
                $tokenPreview = $auth.tokens.access_token.Substring(0, [Math]::Min(20, $tokenLength))
                Write-Host "  Access Token: $tokenPreview... ($tokenLength chars)" -ForegroundColor Gray
                
                if ($auth.tokens.expires_at) {
                    $expiryDate = [DateTimeOffset]::FromUnixTimeSeconds($auth.tokens.expires_at).LocalDateTime
                    $now = Get-Date
                    
                    if ($expiryDate -gt $now) {
                        $timeLeft = $expiryDate - $now
                        Write-Host "  Expires: $expiryDate (in $($timeLeft.Days) days)" -ForegroundColor Green
                    } else {
                        Write-Host "  [WARN] Token EXPIRED: $expiryDate" -ForegroundColor Yellow
                    }
                }
            } else {
                Write-Host "  [ERR] No access token found in auth.json" -ForegroundColor Red
            }
            
            if ($auth.user -and $auth.user.email) {
                Write-Host "  Email: $($auth.user.email)" -ForegroundColor Gray
            }
            
        } catch {
            Write-Host "[ERR] Failed to parse auth.json: $_" -ForegroundColor Red
        }
    } else {
        Write-Host "[WARN] No auth.json found at: $AuthPath" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "To authenticate, you need to either:" -ForegroundColor Yellow
        Write-Host "  1. Run 'codex auth login' (if you have Codex CLI installed)"
        Write-Host "  2. Manually create auth.json (see: dev\docs\CODEX_AUTH_GUIDE.md)"
    }
    
    Write-Host ""
}

function Remove-Auth {
    Write-Host "`n=== Remove Codex Authentication ===`n" -ForegroundColor Cyan
    
    if (Test-Path $AuthPath) {
        Write-Host "Current auth.json: $AuthPath" -ForegroundColor Gray
        
        $confirm = Read-Host "Are you sure you want to remove this file? (yes/no)"
        
        if ($confirm -eq "yes") {
            try {
                Remove-Item $AuthPath -Force
                Write-Host "[OK] auth.json removed successfully" -ForegroundColor Green
                Write-Host ""
                Write-Host "To re-authenticate:" -ForegroundColor Yellow
                Write-Host "  1. Run 'codex auth login' (if you have Codex CLI installed)"
                Write-Host "  2. Or see: dev\docs\CODEX_AUTH_GUIDE.md for manual setup"
            } catch {
                Write-Host "[ERR] Failed to remove auth.json: $_" -ForegroundColor Red
            }
        } else {
            Write-Host "Cancelled." -ForegroundColor Yellow
        }
    } else {
        Write-Host "[INFO] No auth.json found to remove" -ForegroundColor Gray
    }
    
    Write-Host ""
}

function Verify-Auth {
    Write-Host "`n=== Verify auth.json Format ===`n" -ForegroundColor Cyan
    
    if (-not (Test-Path $AuthPath)) {
        Write-Host "[ERR] auth.json not found at: $AuthPath" -ForegroundColor Red
        Write-Host ""
        return
    }
    
    Write-Host "Checking: $AuthPath`n" -ForegroundColor Gray
    
    $errors = @()
    
    try {
        $auth = Get-Content $AuthPath -Raw | ConvertFrom-Json
        Write-Host "[OK] Valid JSON format" -ForegroundColor Green
        
        # Check structure
        if (-not $auth.tokens) {
            $errors += "Missing 'tokens' object"
        } else {
            if (-not $auth.tokens.access_token) {
                $errors += "Missing 'tokens.access_token'"
            } else {
                Write-Host "[OK] tokens.access_token present" -ForegroundColor Green
            }
            
            if ($auth.tokens.refresh_token) {
                Write-Host "[OK] tokens.refresh_token present" -ForegroundColor Green
            } else {
                Write-Host "[WARN] tokens.refresh_token missing (optional)" -ForegroundColor Yellow
            }
            
            if ($auth.tokens.expires_at) {
                Write-Host "[OK] tokens.expires_at present" -ForegroundColor Green
            } else {
                Write-Host "[WARN] tokens.expires_at missing (optional)" -ForegroundColor Yellow
            }
        }
        
        if (-not $auth.user) {
            $errors += "Missing 'user' object"
        } else {
            if ($auth.user.email) {
                Write-Host "[OK] user.email present" -ForegroundColor Green
            } else {
                Write-Host "[WARN] user.email missing (optional)" -ForegroundColor Yellow
            }
        }
        
    } catch {
        $errors += "Invalid JSON format: $_"
        Write-Host "[ERR] Invalid JSON format" -ForegroundColor Red
    }
    
    Write-Host ""
    
    if ($errors.Count -gt 0) {
        Write-Host "Errors found:" -ForegroundColor Red
        foreach ($err in $errors) {
            Write-Host "  - $err" -ForegroundColor Red
        }
    } else {
        Write-Host "[OK] auth.json format is valid!" -ForegroundColor Green
    }
    
    Write-Host ""
}

function Show-Info {
    Write-Host "`n=== Codex Authentication Info ===`n" -ForegroundColor Cyan
    
    Write-Host "Auth file location:"
    Write-Host "  $AuthPath`n" -ForegroundColor Gray
    
    if (Test-Path $AuthPath) {
        Write-Host "Status: [OK] File exists" -ForegroundColor Green
    } else {
        Write-Host "Status: [WARN] File not found" -ForegroundColor Yellow
    }
    
    Write-Host "`nQuick Commands:" -ForegroundColor Cyan
    Write-Host "  # View status"
    Write-Host "  .\manage_codex_auth.ps1 status`n"
    
    Write-Host "  # Remove current credentials"
    Write-Host "  .\manage_codex_auth.ps1 remove`n"
    
    Write-Host "  # Verify auth.json format"
    Write-Host "  .\manage_codex_auth.ps1 verify`n"
    
    Write-Host "  # Login with Codex CLI (if installed)"
    Write-Host "  codex auth login`n"
    
    Write-Host "For detailed instructions, see:" -ForegroundColor Yellow
    Write-Host "  dev\docs\CODEX_AUTH_GUIDE.md`n"
}

# Main execution
switch ($Action) {
    "status" { Show-Status }
    "remove" { Remove-Auth }
    "verify" { Verify-Auth }
    "info"   { Show-Info }
    default  { Show-Usage; Show-Status }
}
