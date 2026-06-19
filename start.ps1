$env:PYTHONPATH = $PSScriptRoot
Set-Location $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\uvicorn.exe" backend.main:app --reload --port 8000
