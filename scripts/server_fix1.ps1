# 修复脚本：启动防火墙服务并放行必需端口 + 重启宝塔面板 + 扩页文件（脱离 SSH 会话运行，防中途锁死）
Start-Transcript -Path C:\Windows\Temp\fix1.log -Force | Out-Null

# 1. 防火墙服务设为自启并启动（此前被禁用导致重启后默认全拦）
Set-Service -Name mpssvc -StartupType Automatic
Start-Service mpssvc
Write-Output "mpssvc started"

# 2. 三个 profile 开启防火墙（公网服务器保持默认拦截+白名单，比裸奔安全）
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled True

# 3. 白名单入站规则（幂等：同名先删再建）：22 SSH / 3389 远程桌面 / 27750 宝塔 / 8501 应用
$rules = @(
    @{ Name = "tb-ssh";  Port = 22;    Desc = "ToolBook deploy SSH" },
    @{ Name = "tb-rdp";  Port = 3389;  Desc = "Remote Desktop" },
    @{ Name = "tb-bt";   Port = 27750; Desc = "Baota panel" },
    @{ Name = "tb-app";  Port = 8501;  Desc = "ToolBook app" }
)
foreach ($r in $rules) {
    Get-NetFirewallRule -Name $r.Name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -Name $r.Name -DisplayName $r.Desc -Direction Inbound -Action Allow -Protocol TCP -LocalPort $r.Port -Profile Any | Out-Null
    Write-Output ("rule added: " + $r.Name + " " + $r.Port)
}

# 4. 宝塔面板：读面板端口配置，若没在监听则重启面板服务
$portFile = "C:\BtSoft\panel\data\port.pl"
if (Test-Path $portFile) { Write-Output ("panel port file: " + (Get-Content $portFile -Raw)) }
$listen = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq 27750 }
if (-not $listen) {
    Restart-Service btPanel -Force
    Start-Sleep -Seconds 5
    $listen = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq 27750 }
}
Write-Output ("panel 27750 listening: " + [bool]$listen)

# 5. 页文件扩到 2G–4G（2G 内存机器的缓冲垫；重启后生效，部署末尾统一重启验证）
Get-CimInstance Win32_PageFileSetting | Remove-CimInstance
New-CimInstance -ClassName Win32_PageFileSetting -Property @{ Name = "C:\pagefile.sys"; InitialSize = 2048; MaximumSize = 4096 } | Out-Null
Write-Output "pagefile set 2048-4096 (effective after reboot)"

Write-Output "FIX1_DONE"
Stop-Transcript | Out-Null