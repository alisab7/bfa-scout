# BFA-Scout Phase 3 verification script
# Run via: _run_verify_phase3.bat
# Results go to: _verify_phase3_output.txt

$base    = "D:\BFA-Scout"
$baseUrl = "http://localhost:5000"
$results = @()
$pass    = 0
$fail    = 0

function Add-Check([bool]$ok, [string]$label, [string]$detail = "") {
    $script:results += [PSCustomObject]@{ OK = $ok; Label = $label; Detail = $detail }
    if ($ok) { $script:pass++ } else { $script:fail++ }
}

function Safe-Get([string]$url, [int]$expectedStatus = 200) {
    try {
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5 `
                    -ErrorAction SilentlyContinue
        return $resp
    } catch {
        $resp = $_.Exception.Response
        if ($resp) { return $resp }
        return $null
    }
}

Write-Output "============================================="
Write-Output "  BFA-Scout Phase 3 Verification"
Write-Output "============================================="
Write-Output ""

# ---- 1. Pillow importable ------------------------------------------------
$pillow = & "$base\.venv\Scripts\python.exe" -c "import PIL; print(PIL.__version__)" 2>&1
$pillowOk = ($pillow -match "^\d+\.\d+")
Add-Check $pillowOk "Pillow importable" $pillow

# ---- 2. Required files exist -----------------------------------------------
$files = @(
    "app\players\__init__.py",
    "app\players\helpers.py",
    "app\players\photos.py",
    "app\templates\players\list.html",
    "app\templates\players\_grid.html",
    "app\templates\players\new.html",
    "app\templates\players\edit.html",
    "app\templates\players\profile.html",
    "app\static\photos\placeholder.svg"
)
foreach ($f in $files) {
    $exists = Test-Path "$base\$f"
    Add-Check $exists "File: $f"
}

# ---- 3. HTTP checks (requires Flask running) --------------------------------
$healthResp = Safe-Get "$baseUrl/health"
$flaskUp = ($healthResp -and $healthResp.StatusCode -eq 200)

if (-not $flaskUp) {
    Write-Output "WARNING: Flask not running at $baseUrl — skipping HTTP checks."
    Write-Output "Start Flask first: .venv\Scripts\flask --app wsgi run --debug"
    Write-Output ""
    Add-Check $false "Flask running at $baseUrl" "connection refused"
} else {
    Add-Check $true "Flask running at $baseUrl"

    # /players/ returns 200 when authenticated (we test redirect for unauth)
    $playersUnauth = Safe-Get "$baseUrl/players/"
    $unauthRedirect = ($playersUnauth -and ($playersUnauth.StatusCode -in 200, 302))
    Add-Check $unauthRedirect "GET /players/ responds (unauth -> redirect)" "status=$($playersUnauth.StatusCode)"

    # /players/new responds
    $newResp = Safe-Get "$baseUrl/players/new"
    $newOk = ($newResp -and ($newResp.StatusCode -in 200, 302))
    Add-Check $newOk "GET /players/new responds" "status=$($newResp.StatusCode)"

    # health check
    $healthBody = $healthResp.Content
    $healthOk = ($healthBody -match '"status"\s*:\s*"ok"')
    Add-Check $healthOk "/health returns ok" $healthBody
}

# ---- 4. DB checks ----------------------------------------------------------
$psql = "C:\Program Files\PostgreSQL\15\bin\psql.exe"
$env:PGPASSWORD = (Get-Content "$base\.env" | Where-Object { $_ -match "^DB_PASSWORD=" } | ForEach-Object { ($_ -split "=", 2)[1] })
if (-not $env:PGPASSWORD) {
    $env:PGPASSWORD = (Get-Content "$base\.env" | Where-Object { $_ -match "^DATABASE_URL=" } | ForEach-Object { [regex]::Match($_, "://[^:]+:([^@]+)@").Groups[1].Value })
}

if (Test-Path $psql) {
    $tables = & $psql -U bfa -d bfa_scout -t -c "\dt" 2>&1 | Out-String
    $hasPlayers = $tables -match "players"
    Add-Check $hasPlayers "players table exists in DB" ($tables -replace "\s+", " ").Trim().Substring(0, [math]::Min(120, ($tables -replace "\s+", " ").Trim().Length))

    $positions = & $psql -U bfa -d bfa_scout -t -c "SELECT COUNT(*) FROM positions;" 2>&1
    $posOk = ($positions -match "26")
    Add-Check $posOk "26 positions seeded" $positions.Trim()
} else {
    Add-Check $false "psql not found at expected path" $psql
}

# ---- 5. gitignore has photos pattern --------------------------------------
$gitignore = Get-Content "$base\.gitignore" -Raw
$gitignoreOk = $gitignore -match "photos.*\.jpg"
Add-Check $gitignoreOk ".gitignore has app/static/photos/*.jpg"

# ---- Results ---------------------------------------------------------------
Write-Output ""
Write-Output "RESULTS"
Write-Output "-------"
foreach ($r in $results) {
    $icon = if ($r.OK) { "OK " } else { "FAIL" }
    $line = "[$icon] $($r.Label)"
    if ($r.Detail) { $line += "  -> $($r.Detail)" }
    Write-Output $line
}
Write-Output ""
Write-Output "Passed: $pass / $($pass + $fail)"
if ($fail -gt 0) {
    Write-Output "FAILED: $fail check(s) need attention."
} else {
    Write-Output "All checks passed!"
}
