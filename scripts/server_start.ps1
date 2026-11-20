# start.ps1: read .env into process env then launch Streamlit headless on 0.0.0.0:8501 (ASCII only)
$root = 'C:\toolbook'
# parse .env key=value lines (skip comments/blanks) into environment variables
Get-Content "$root\.env" | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
        $k, $v = $line.Split('=', 2)
        Set-Item -Path ("Env:" + $k.Trim()) -Value $v.Trim()
    }
}
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUNBUFFERED = '1'
$env:STREAMLIT_SERVER_HEADLESS = 'true'
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = 'false'
# dump Python stack on native crash; propagate real exit code so task restart-on-failure works
$env:PYTHONFAULTHANDLER = '1'
Set-Location $root
& "$root\.venv\Scripts\python.exe" -m streamlit run app.py --server.port=8501 --server.address=0.0.0.0
exit $LASTEXITCODE