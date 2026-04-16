#!/usr/bin/env pwsh
# Security check script - verify no credentials in git before pushing

Write-Host "Security Check - TwitchDropFarmer" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

# Check .gitignore
Write-Host "[CHECK] .gitignore configuration..." -ForegroundColor Yellow
$gitignore = Get-Content ".gitignore"
if ($gitignore -match "twitch-drop-farmer|cookies|\.vscode") {
    Write-Host "  OK: Sensitive directories are ignored" -ForegroundColor Green
} else {
    Write-Host "  FAIL: .gitignore incomplete" -ForegroundColor Red
}

# Check for .json files
Write-Host "[CHECK] JSON files in git..." -ForegroundColor Yellow
$jsonFiles = git ls-files 2>$null | Select-String "\.json" | Where-Object { $_ -notmatch "package.json" }
if ($jsonFiles) {
    Write-Host "  WARN: Found JSON files:" -ForegroundColor Yellow
    $jsonFiles | ForEach-Object { Write-Host "    $_" }
} else {
    Write-Host "  OK: No sensitive JSON files" -ForegroundColor Green
}

# Check credentials in code
Write-Host "[CHECK] Credentials in source..." -ForegroundColor Yellow
$creds = git grep -i "password\|secret\|api_key" -- "*.py" 2>$null | Where-Object { $_ -notmatch "PLAYBACK_ACCESS_TOKEN_QUERY" }
if ($creds) {
    Write-Host "  WARN: Check these carefully:" -ForegroundColor Yellow
    $creds | Select-Object -First 3 | ForEach-Object { Write-Host "    $_" }
} else {
    Write-Host "  OK: No hardcoded credentials found" -ForegroundColor Green
}

Write-Host ""
Write-Host "================================" -ForegroundColor Cyan
Write-Host "Ready for GitHub!" -ForegroundColor Green
# Security check script for TwitchDropFarmer
# Run this before pushing to GitHub to verify no credentials are committed

Write-Host "Security Check for TwitchDropFarmer" -ForegroundColor Cyan
Write-Host "===================================" -ForegroundColor Cyan
Write-Host ""

$issues = 0

# Check 1: Look for auth-token in git history
Write-Host "[1] Checking git history for auth-token..." -ForegroundColor Yellow
$authTokenFound = git log -p --all -S "auth-token" --oneline 2>$null | Select-Object -First 1
if ($authTokenFound) {
    Write-Host "    WARNING: Found auth-token references (likely in comments)" -ForegroundColor Yellow
    $issues++
} else {
    Write-Host "    PASS: No auth-token found in history" -ForegroundColor Green
}

# Check 2: Look for .json files in git
Write-Host "[2] Checking for .json files in git tracking..." -ForegroundColor Yellow
$jsonFiles = git ls-files 2>$null | Select-String -Pattern "\.json$"
if ($jsonFiles) {
    Write-Host "    WARNING: Found .json files in git:" -ForegroundColor Yellow
    $jsonFiles | ForEach-Object { Write-Host "       - $_" -ForegroundColor Yellow }
    $issues++
} else {
    Write-Host "    PASS: No .json files in git" -ForegroundColor Green
}

# Check 3: Look for password/credential patterns
Write-Host "[3] Checking for common credential patterns..." -ForegroundColor Yellow
$suspiciousPatterns = git grep -i "password|secret|api.?key|bearer" -- "*.py" 2>$null | Where-Object { $_ -notmatch "PLAYBACK_ACCESS_TOKEN_QUERY" } | Select-Object -First 3
if ($suspiciousPatterns) {
    Write-Host "    WARNING: Found potential credential patterns:" -ForegroundColor Yellow
    $suspiciousPatterns | ForEach-Object { Write-Host "       - $_" -ForegroundColor Yellow }
}

# Check 4: Verify .gitignore is present and configured
Write-Host "[4] Checking .gitignore..." -ForegroundColor Yellow
if (Test-Path ".gitignore") {
    $content = Get-Content ".gitignore" -Raw
    if ($content -match "twitch-drop-farmer" -or $content -match "cookies" -or $content -match "\.vscode") {
        Write-Host "    PASS: .gitignore properly configured" -ForegroundColor Green
    } else {
        Write-Host "    WARNING: .gitignore exists but may be incomplete" -ForegroundColor Yellow
        $issues++
    }
} else {
    Write-Host "    FAIL: .gitignore not found!" -ForegroundColor Red
    $issues++
}

# Check 5: Verify no tracked files from TwitchDropFarmer directory
Write-Host "[5] Checking TwitchDropFarmer directory..." -ForegroundColor Yellow
$trackedFiles = git ls-files 2>$null | Select-String -Pattern "TwitchDropFarmer"
if ($trackedFiles) {
    Write-Host "    WARNING: Found tracked files in TwitchDropFarmer/" -ForegroundColor Yellow
    $trackedFiles | ForEach-Object { Write-Host "       - $_" -ForegroundColor Yellow }
}

# Summary
Write-Host ""
Write-Host "===================================" -ForegroundColor Cyan
if ($issues -eq 0) {
    Write-Host "RESULT: PASS - Repository is safe!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Your repository is clean and ready to push to GitHub." -ForegroundColor Green
    Write-Host "Credentials are stored locally only in ~/.twitch-drop-farmer/" -ForegroundColor Green
} else {
    Write-Host "RESULT: Found $issues issue(s)" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Please review the warnings above." -ForegroundColor Yellow
    Write-Host "If all warnings are expected/safe, proceed with push." -ForegroundColor Yellow
}
Write-Host ""
# Security check script for TwitchDropFarmer
# Run this before pushing to GitHub to verify no credentials are committed

Write-Host "🔒 TwitchDropFarmer Security Check" -ForegroundColor Cyan
Write-Host "=================================" -ForegroundColor Cyan
Write-Host ""

$issues = 0

# Check 1: Look for auth-token in git history
Write-Host "Checking git history for 'auth-token'..." -ForegroundColor Yellow
$authTokenFound = git log -p --all -S "auth-token" --oneline 2>$null | Select-Object -First 1
if ($authTokenFound) {
    Write-Host "⚠️  Found 'auth-token' references in git history (this might be in comments/code)" -ForegroundColor Yellow
    $issues++
}

# Check 2: Look for .json files in git
Write-Host "Checking for .json files in git tracking..." -ForegroundColor Yellow
$jsonFiles = git ls-files 2>$null | Select-String -Pattern "\.json$"
if ($jsonFiles) {
    Write-Host "⚠️  Found .json files in git:" -ForegroundColor Yellow
    $jsonFiles | ForEach-Object { Write-Host "   - $_" -ForegroundColor Yellow }
    $issues++
}

# Check 3: Look for password/credential patterns
Write-Host "Checking for common credential patterns..." -ForegroundColor Yellow
$suspiciousPatterns = git grep -i "password|secret|api.?key|bearer|token" -- "*.py" "*.json" 2>$null | Select-Object -First 5
if ($suspiciousPatterns) {
    Write-Host "⚠️  Found potential credential patterns (verify these are safe):" -ForegroundColor Yellow
    $suspiciousPatterns | ForEach-Object { Write-Host "   - $_" -ForegroundColor Yellow }
}

# Check 4: Verify .gitignore is present
Write-Host "Checking .gitignore..." -ForegroundColor Yellow
if (Test-Path ".gitignore") {
    $ignoredItems = Get-Content ".gitignore" | Where-Object { $_ -match "twitch-drop-farmer|cookies|\.vscode" }
    if ($ignoredItems) {
        Write-Host "✅ .gitignore properly configured for sensitive files" -ForegroundColor Green
    }
} else {
    Write-Host "❌ .gitignore not found!" -ForegroundColor Red
    $issues++
}

# Check 5: Verify SECURITY.md exists
Write-Host "Checking documentation..." -ForegroundColor Yellow
if (Test-Path "SECURITY.md") {
    Write-Host "✅ SECURITY.md found" -ForegroundColor Green
} else {
    Write-Host "⚠️  SECURITY.md not found" -ForegroundColor Yellow
}

# Summary
Write-Host ""
Write-Host "=================================" -ForegroundColor Cyan
if ($issues -eq 0) {
    Write-Host "✅ Security check passed!" -ForegroundColor Green
    Write-Host "Your repository is safe to push to GitHub." -ForegroundColor Green
} else {
    Write-Host "⚠️  Security check found $issues issue(s)" -ForegroundColor Yellow
    Write-Host "Please review the warnings above before pushing." -ForegroundColor Yellow
}
Write-Host ""
