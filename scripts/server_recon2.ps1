# 服务器体检第二轮：防火墙服务/面板服务/页文件/Python 版本（只读）
Write-Output "--- firewall & baota services ---"
Get-Service mpssvc,BFE | ForEach-Object { Write-Output ($_.Name + " " + $_.Status + " " + $_.StartType) }
Get-Service | Where-Object { $_.Name -match "bt|Bt|panel|Panel" } | ForEach-Object {
    Write-Output ($_.Name + " " + $_.Status + " " + $_.StartType)
}
Write-Output "--- netsh firewall state ---"
netsh advfirewall show allprofiles state
Write-Output "--- pagefile ---"
Get-CimInstance Win32_PageFileUsage | ForEach-Object {
    Write-Output ($_.Name + " allocated_MB=" + $_.AllocatedBaseSize + " used_MB=" + $_.CurrentUsage)
}
Write-Output "--- python version ---"
& "C:\Program Files\python\python.exe" --version
Write-Output "--- baota panel dir ---"
if (Test-Path "C:\BtSoft\panel") { Get-ChildItem "C:\BtSoft\panel" -Filter "*.exe" | ForEach-Object { Write-Output $_.Name } }
Write-Output "--- defender realtime ---"
Get-MpPreference | Select-Object -ExpandProperty DisableRealtimeMonitoring