# 服务器体检脚本（只读）：内存/磁盘/防火墙/服务/进程/工具链/监听端口
$os = Get-CimInstance Win32_OperatingSystem
Write-Output ("RAM_total_MB=" + [math]::Round($os.TotalVisibleMemorySize/1024))
Write-Output ("RAM_free_MB=" + [math]::Round($os.FreePhysicalMemory/1024))
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
    Write-Output ($_.DeviceID + " free_GB=" + [math]::Round($_.FreeSpace/1GB,1))
}
Write-Output "--- firewall profiles ---"
Get-NetFirewallProfile | ForEach-Object { Write-Output ($_.Name + " Enabled=" + $_.Enabled) }
Write-Output "--- inbound allow rules ---"
Get-NetFirewallRule -Direction Inbound -Action Allow -Enabled True | ForEach-Object {
    $p = $_ | Get-NetFirewallPortFilter
    Write-Output ($_.DisplayName + " | " + $p.Protocol + " " + $p.LocalPort)
}
Write-Output "--- services ---"
Get-Service sshd,TermService | ForEach-Object { Write-Output ($_.Name + " " + $_.Status + " " + $_.StartType) }
Write-Output "--- top memory processes ---"
Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 8 | ForEach-Object {
    Write-Output ($_.Name + " MB=" + [math]::Round($_.WorkingSet64/1MB))
}
Write-Output "--- tools ---"
foreach ($t in @("python","uv","tar","git")) {
    $w = where.exe $t 2>$null
    if ($w) { Write-Output ($t + " => " + ($w -join ";")) } else { Write-Output ($t + " => MISSING") }
}
Write-Output "--- listening ports (0.0.0.0) ---"
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalAddress -eq "0.0.0.0" } |
    ForEach-Object { Write-Output $_.LocalPort } | Sort-Object -Unique
Write-Output "--- baota hint ---"
if (Test-Path "C:\BtSoft") { Write-Output "BtSoft exists" }
Get-ChildItem C:\ -Directory | ForEach-Object { Write-Output ("dir: " + $_.Name) }