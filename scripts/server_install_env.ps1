# install_env: Python 3.13 (npmmirror binary) + venv + cloud deps (tsinghua pip mirror), ASCII only
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Write-Output "downloading python installer..."
Invoke-WebRequest -Uri 'https://registry.npmmirror.com/-/binary/python/3.13.9/python-3.13.9-amd64.exe' -OutFile C:\Windows\Temp\py313.exe -UseBasicParsing
Write-Output "installing python silently..."
Start-Process -FilePath C:\Windows\Temp\py313.exe -ArgumentList '/quiet','InstallAllUsers=1','TargetDir=C:\Python313','Include_launcher=0','Include_test=0','SimpleInstall=1' -Wait
& C:\Python313\python.exe --version
Write-Output "creating venv..."
& C:\Python313\python.exe -m venv C:\toolbook\.venv
Write-Output "upgrading pip..."
& C:\toolbook\.venv\Scripts\python.exe -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
Write-Output "installing cloud requirements..."
& C:\toolbook\.venv\Scripts\python.exe -m pip install -r C:\toolbook\requirements-cloud.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
Write-Output "INSTALL_DONE"