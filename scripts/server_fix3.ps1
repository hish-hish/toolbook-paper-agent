# fix3: private-path firewall test + panel port back to 27750 + pagefile via registry (ASCII only)
Write-Output "--- firewall profiles now ---"
Get-NetFirewallProfile | ForEach-Object { Write-Output ($_.Name + " Enabled=" + $_.Enabled) }
Write-Output "--- tb-rdp rule detail ---"
Get-NetFirewallRule -Name tb-rdp | ForEach-Object {
    Write-Output ("enabled=" + $_.Enabled + " profile=" + $_.Profile + " action=" + $_.Action)
    $_ | Get-NetFirewallPortFilter | ForEach-Object { Write-Output ("port=" + $_.LocalPort + " proto=" + $_.Protocol) }
}
Write-Output "--- private IP connect test (non-loopback OS path) ---"
foreach ($port in @(3389, 22)) {
    $t = Test-NetConnection -ComputerName 10.1.0.17 -Port $port -WarningAction SilentlyContinue
    Write-Output ("10.1.0.17:" + $port + " TcpTestSucceeded=" + $t.TcpTestSucceeded)
}
Write-Output "--- set panel port to 27750 and restart ---"
Set-Content -Path "C:\BtSoft\panel\data\port.pl" -Value "27750" -NoNewline -Encoding ASCII
Restart-Service btPanel -Force
Start-Sleep -Seconds 6
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq 27750 -or $_.LocalPort -eq 8888 } | ForEach-Object {
    Write-Output ("listen " + $_.LocalAddress + ":" + $_.LocalPort)
}
Write-Output "--- pagefile via registry ---"
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management" -Name PagingFiles -Value "C:\pagefile.sys 2048 4096"
(Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management").PagingFiles
Write-Output "FIX3_DONE"