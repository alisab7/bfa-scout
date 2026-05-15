# BFA-Scout Phase 1 verification (ASCII only - no Unicode)
# Output redirected by bat wrapper to _verify_phase1_output.txt

$base = "http://127.0.0.1:5000"
$results = [System.Collections.ArrayList]@()
$p = 0; $f = 0

function Add-Check([bool]$ok, [string]$label, [string]$detail = "") {
    $icon = if ($ok) { "[PASS]" } else { "[FAIL]" }
    $line = "$icon  $label"
    if ($detail) { $line = "$line  >> $detail" }
    $null = $script:results.Add($line)
    if ($ok) { $script:p++ } else { $script:f++ }
}

function Safe-Get([string]$url, [int]$maxR = 5, $sess = $null) {
    try {
        $args2 = @{ Uri=$url; UseBasicParsing=$true; TimeoutSec=6; MaximumRedirection=$maxR }
        if ($sess) { $args2.WebSession = $sess }
        $r = Invoke-WebRequest @args2
        return @{ status=[int]$r.StatusCode; body=$r.Content; location="" }
    } catch {
        $resp = $_.Exception.Response
        if ($resp) {
            $loc = ""
            try { $loc = $resp.GetResponseHeader("Location") } catch {}
            return @{ status=[int]$resp.StatusCode; body=""; location=$loc; err=$_.Exception.Message }
        }
        return @{ status=0; body=""; location=""; err=$_.Exception.Message }
    }
}

function Safe-Post([string]$url, [hashtable]$body, $sess = $null, [int]$maxR = 5) {
    try {
        $args2 = @{ Uri=$url; Method="POST"; Body=$body; UseBasicParsing=$true; TimeoutSec=6; MaximumRedirection=$maxR }
        if ($sess) { $args2.WebSession = $sess }
        $r = Invoke-WebRequest @args2
        return @{ status=[int]$r.StatusCode; body=$r.Content }
    } catch {
        $resp = $_.Exception.Response
        if ($resp) { return @{ status=[int]$resp.StatusCode; body=""; err=$_.Exception.Message } }
        return @{ status=0; body=""; err=$_.Exception.Message }
    }
}

# 1. Health check
$r = Safe-Get "$base/health"
Add-Check ($r.status -eq 200 -and $r.body -match '"status":"ok"') "GET /health -> 200 {status:ok}" "status=$($r.status)"

# 2. GET / unauth -> redirect to /auth/login
$r = Safe-Get "$base/" -maxR 0
Add-Check ($r.status -eq 302) "GET / (unauth) -> 302 to /auth/login" "status=$($r.status) loc=$($r.location)"

# 3. GET /auth/login -> 200 with form
$sess = $null
$csrfToken = ""
try {
    $pg = Invoke-WebRequest "$base/auth/login" -UseBasicParsing -SessionVariable sess -TimeoutSec 6
    Add-Check ($pg.StatusCode -eq 200 -and $pg.Content -match "<form") "GET /auth/login -> 200 with form" "status=$($pg.StatusCode)"
    $pat = 'name="csrf_token"\s+value="([^"]+)"'
    if ($pg.Content -match $pat) { $csrfToken = $Matches[1] }
} catch {
    Add-Check $false "GET /auth/login -> 200 with form" $_.Exception.Message
}

# 4. CSRF token extracted
Add-Check ($csrfToken -ne "") "CSRF token extracted" $(if ($csrfToken) { "len=$($csrfToken.Length)" } else { "MISSING" })

# 5. POST /auth/login bad creds -> 200 + error message
$r = Safe-Post "$base/auth/login" @{ email="nobody@bfa.bh"; password="wrong"; csrf_token=$csrfToken } -sess $sess -maxR 0
Add-Check ($r.status -eq 200 -and $r.body -match "Invalid email or password") "POST bad creds -> 200 + error msg" "status=$($r.status)"

# Refresh CSRF
try {
    $pg2 = Invoke-WebRequest "$base/auth/login" -UseBasicParsing -WebSession $sess -TimeoutSec 6
    $pat2 = 'name="csrf_token"\s+value="([^"]+)"'
    if ($pg2.Content -match $pat2) { $csrfToken = $Matches[1] }
} catch {}

# 6. POST /auth/login good creds -> authenticated
$r = Safe-Post "$base/auth/login" @{ email="admin@bfa.bh"; password="bfa@2025"; csrf_token=$csrfToken } -sess $sess -maxR 5
Add-Check ($r.status -eq 200) "POST good creds -> 200 (authenticated)" "status=$($r.status)"

# 7. GET / (authenticated) -> 200 + "BFA Scouting"
$r = Safe-Get "$base/" -sess $sess
Add-Check ($r.status -eq 200 -and $r.body -match "BFA Scouting") "GET / (auth) -> 200 + BFA Scouting" "status=$($r.status)"

# 8. GET /admin/users (admin) -> 200
$r = Safe-Get "$base/admin/users" -sess $sess
Add-Check ($r.status -eq 200) "GET /admin/users (admin) -> 200" "status=$($r.status)"

# 9. GET /admin/users/new (admin) -> 200
$r = Safe-Get "$base/admin/users/new" -sess $sess
Add-Check ($r.status -eq 200) "GET /admin/users/new (admin) -> 200" "status=$($r.status)"

# 10. GET /players/ (unauth) -> 302
$r = Safe-Get "$base/players/" -maxR 0
Add-Check ($r.status -eq 302) "GET /players/ (unauth) -> 302" "status=$($r.status) loc=$($r.location)"

# 11. GET /admin/users (unauth) -> 302
$r = Safe-Get "$base/admin/users" -maxR 0
Add-Check ($r.status -eq 302) "GET /admin/users (unauth) -> 302" "status=$($r.status)"

# 12. audit_log has rows
try {
    $env:PGPASSWORD = "bfa2025"
    $pgOut = (& psql -U bfa -d bfa_scout -c "SELECT COUNT(*) AS n FROM audit_log;" 2>&1) | Out-String
    Add-Check ($pgOut -match "\s+[1-9]") "audit_log has rows" $pgOut.Trim()
} catch { Add-Check $false "audit_log has rows" $_.Exception.Message }

# 13. Only 1 admin in DB (seed is idempotent)
try {
    $env:PGPASSWORD = "bfa2025"
    $pgOut = (& psql -U bfa -d bfa_scout -c "SELECT COUNT(*) AS n FROM users WHERE role='admin';" 2>&1) | Out-String
    Add-Check ($pgOut -match "\s+1\s") "Exactly 1 admin in DB (seed idempotent)" $pgOut.Trim()
} catch { Add-Check $false "Exactly 1 admin in DB" $_.Exception.Message }

# Summary
Write-Output ""
Write-Output ("=" * 60)
Write-Output "Phase 1 -- $p / $($p + $f) checks passed"
Write-Output ("=" * 60)
Write-Output ""
$results | ForEach-Object { Write-Output $_ }
