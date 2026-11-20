# fix2: investigate baota panel listening + pagefile via wmic (ASCII only to avoid encoding issues)
Write-Output "--- inbound BLOCK rules (block wins over allow) ---"
Get-NetFirewallRule -Direction Inbound -Action Block -Enabled True | ForEach-Object {
    $p = $_ | Get-NetFirewallPortFilter
    Write-Output ($_.DisplayName + " | " + $p.Protocol + " " + $p.LocalPort)
}
Write-Output "--- local connect test 3389 / 27750 ---"
foreach ($port in @(3389, 27750)) {
    $t = Test-NetConnection -ComputerName 127.0.0.1 -Port $port -WarningAction SilentlyContinue
    Write-Output ("127.0.0.1:" + $port + " TcpTestSucceeded=" + $t.TcpTestSucceeded)
}
Write-Output "--- port.pl ---"
cmd /c type C:\BtSoft\panel\data\port.pl
Write-Output "--- btPanel process and its listening ports ---"
$procs = Get-Process | Where-Object { $_.Name -match "bt|Bt" }
foreach ($p in $procs) {
    Write-Output ("proc: " + $p.Name + " pid=" + $p.Id)
    Get-NetTCPConnection -State Listen -OwningProcess $p.Id -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Output ("  listen " + $_.LocalAddress + ":" + $_.LocalPort)
    }
}
Write-Output "--- all listening (any address) ---"
Get-NetTCPConnection -State Listen | ForEach-Object { Write-Output ($_.LocalAddress + ":" + $_.LocalPort) } | Sort-Object -Unique
Write-Output "--- panel error log tail ---"
if (Test-Path "C:\BtSoft\panel\logs\error.log") { Get-Content "C:\BtSoft\panel\logs\error.log" -Tail 15 }
Write-Output "--- pagefile current setting ---"
cmd /c wmic pagefileset list /format:list
Write-Output "--- pagefile set via wmic ---"
cmd /c wmic pagefileset where name="C:\\pagefile.sys" set InitialSize=2048,MaximumSize=4096
Write-Output "--- pagefile after ---"
cmd /c wmic pagefileset list /format:list
Write-Output "FIX2_DONE"