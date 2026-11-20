# Install latest VC++ 2015-2022 x64 runtime (fixes MSVCP140.dll 14.0 APPCRASH in hnswlib)
$ErrorActionPreference = 'Stop'
$url = 'https://aka.ms/vs/17/release/vc_redist.x64.exe'
$out = 'C:\Windows\Temp\vc_redist.x64.exe'
Write-Output 'DOWNLOADING'
curl.exe -L --retry 2 --connect-timeout 20 -o $out $url
if (!(Test-Path $out) -or (Get-Item $out).Length -lt 10MB) { Write-Output 'DOWNLOAD_FAIL'; exit 1 }
Write-Output ('SIZE=' + (Get-Item $out).Length)
$p = Start-Process -FilePath $out -ArgumentList '/install','/quiet','/norestart' -Wait -PassThru
Write-Output ('INSTALL_EXIT=' + $p.ExitCode)
(Get-Item C:\Windows\System32\msvcp140.dll).VersionInfo | Format-List FileVersion,ProductVersion
Write-Output 'VC_DONE'