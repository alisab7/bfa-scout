# BFA-Scout Phase 0 Cleanup Verification
# Starts Flask, curls all routes, writes results to _verify_output.txt, then stops Flask.

Set-Location D:\BFA-Scout

# --- Start Flask in background (python-dotenv auto-loads .env) ---
$flaskProc = Start-Process `
    -FilePath "D:\BFA-Scout\.venv\Scripts\flask.exe" `
    -ArgumentList "--app wsgi run" `
    -WorkingDirectory "D:\BFA-Scout" `
    -PassThru `
    -WindowStyle Minimized

# --- Wait up to 30 s for Flask to respond ---
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 1000
    try {
        $null = Invoke-WebRequest "http://127.0.0.1:5000/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        $ready = $true; break
    } catch {}
}

$sb = [System.Text.StringBuilder]::new()
[void]$sb.AppendLine("BFA-Scout Phase 0 Cleanup Verification — $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
[void]$sb.AppendLine("=" * 60)
[void]$sb.AppendLine("")

if (-not $ready) {
    [void]$sb.AppendLine("FATAL: Flask did not start within 30 seconds.")
} else {
    $routes = @('/health', '/', '/auth/', '/players/', '/evaluations/', '/criteria/', '/wyscout/', '/reports/', '/ai/', '/api/')
    foreach ($path in $routes) {
        try {
            $r = Invoke-WebRequest "http://127.0.0.1:5000$path" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
            $snippet = ($r.Content -replace '\s+', ' ').Trim()
            $snippet = $snippet.Substring(0, [Math]::Min(100, $snippet.Length))
            [void]$sb.AppendLine("$($r.StatusCode)  $path")
            [void]$sb.AppendLine("    >> $snippet")
        } catch {
            [void]$sb.AppendLine("ERR  $path")
            [void]$sb.AppendLine("    >> $_")
        }
        [void]$sb.AppendLine("")
    }
}

# --- Terminate Flask ---
try { $flaskProc | Stop-Process -Force } catch {}

$output = $sb.ToString()
$output | Out-File -FilePath "D:\BFA-Scout\_verify_output.txt" -Encoding UTF8
Write-Host $output
notepad "D:\BFA-Scout\_verify_output.txt"
