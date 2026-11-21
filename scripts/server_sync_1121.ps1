# One-shot ops script (ASCII only): apply 11-21 model switch + temporarily disable login gate.
# 2026-11-21: blank TOOLBOOK_AUTH_USER / TOOLBOOK_AUTH_PASS in C:\toolbook\.env (login gate off),
# verify config.py carries the new CHAT_MODEL, then restart the ToolBookApp task and probe health.
$ErrorActionPreference = 'Stop'
$root = 'C:\toolbook'
$envPath = Join-Path $root '.env'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

# 1) backup .env so re-enabling the gate is a one-line restore
Copy-Item $envPath "$envPath.bak-$stamp" -Force
Write-Output ("backup: $envPath.bak-$stamp")

# 2) blank only the two auth values, keep every other line untouched (never print values)
$lines = Get-Content $envPath
$out = $lines | ForEach-Object { $_ -replace '^(\s*TOOLBOOK_AUTH_(USER|PASS)\s*=).*$', '$1' }
Set-Content -Path "$envPath.new" -Value $out -Encoding ascii

# self-check: key names + whether each value is empty (names only, no secrets)
$newLines = Get-Content "$envPath.new"
foreach ($l in $newLines) {
    if ($l -match '=') {
        $n = ($l -split '=', 2)[0].Trim()
        $v = ($l -split '=', 2)[1].Trim()
        Write-Output ("key=" + $n + " value_len=" + $v.Length)
    }
}
Move-Item "$envPath.new" $envPath -Force

# 3) confirm synced code has the new chat model
Write-Output "--- config.py ---"
Select-String -Path (Join-Path $root 'src\toolbook\config.py') -Pattern 'CHAT_MODEL|EMBED_MODEL' | ForEach-Object { Write-Output $_.Line.Trim() }
Write-Output ("md5=" + (Get-FileHash (Join-Path $root 'src\toolbook\config.py') -Algorithm MD5).Hash)

# 4) restart: kill the streamlit python tree and the start.ps1 powershell wrapper (NOT this script)
$killed = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq 'python.exe' -and $_.CommandLine -like '*streamlit*') -or
    ($_.Name -match 'powershell' -and $_.CommandLine -like '*start.ps1*')
}
foreach ($p in $killed) {
    Write-Output ("kill pid=" + $p.ProcessId + " name=" + $p.Name)
    taskkill /F /T /PID $p.ProcessId 2>&1 | Out-Null
}
if (-not $killed) { Write-Output "no running app process found" }

# 5) start via the scheduled task and probe local health
schtasks /run /tn ToolBookApp | Out-Null
$ok = $false
for ($i = 0; $i -lt 10; $i++) {
    Start-Sleep -Seconds 8
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8501/_stcore/health' -UseBasicParsing -TimeoutSec 10
        Write-Output ("health=" + $r.StatusCode + " " + $r.Content)
        $ok = $true
        break
    } catch {
        Write-Output ("waiting... " + $_.Exception.Message)
    }
}
Write-Output ("health_ok=" + $ok)
exit 0
