# register_task: create ONSTART scheduled task ToolBookApp (SYSTEM, no time limit, restart on failure)
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File C:\toolbook\start.ps1'
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Get-ScheduledTask -TaskName 'ToolBookApp' -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false
Register-ScheduledTask -TaskName 'ToolBookApp' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'ToolBook-Paper Agent Streamlit on 8501'
Write-Output 'TASK_REGISTERED'