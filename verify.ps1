# Run from the project folder: powershell -ExecutionPolicy Bypass -File .\verify.ps1
# Creates and retains one demonstration quest; recreates this Compose stack.
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    # Read only the published port, never print resolved Compose secrets.
    $questPort = '8080'
    foreach ($questLine in Get-Content .env) {
        if ($questLine -match '^APP_PORT=(\d+)\s*$') { $questPort = $Matches[1] }
    }
    $questBase = "http://localhost:$questPort"
    function Assert-Quest($condition, $message) {
        if (-not $condition) { throw $message }
    }
    function Assert-Status($method, $path, $body, $expected) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "$questBase$path" -Method $method -ContentType 'application/json' -Body $body
            $actual = [int]$response.StatusCode
        } catch {
            if (-not $_.Exception.Response) { throw }
            $actual = [int]$_.Exception.Response.StatusCode
        }
        Assert-Quest ($actual -eq $expected) "$method $path expected $expected, received $actual"
    }
    docker compose up -d --build --wait
    if ($LASTEXITCODE -ne 0) { throw 'Compose startup failed' }
    $questHealth = Invoke-RestMethod "$questBase/health"
    Assert-Quest ($questHealth.database -eq 'connected') 'Database health failed'
    $questPage = Invoke-WebRequest -UseBasicParsing "$questBase/"
    Assert-Quest ($questPage.Content -match 'quest-form') 'Browser page missing'
    $questInfo = Invoke-RestMethod "$questBase/api/info"
    Assert-Quest ([bool]$questInfo.app) 'Application configuration missing'

    $questTitle = "Learn Compose - verified $([DateTime]::UtcNow.ToString('s'))"
    $questBody = @{title=$questTitle; subject='Docker / PostgreSQL'} | ConvertTo-Json
    $questResponse = Invoke-WebRequest -UseBasicParsing "$questBase/api/quests" -Method Post -ContentType 'application/json' -Body $questBody
    Assert-Quest ($questResponse.StatusCode -eq 201) 'POST must return 201'
    $questCreated = $questResponse.Content | ConvertFrom-Json
    $questList = (Invoke-RestMethod "$questBase/api/quests").quests
    Assert-Quest (@($questList | Where-Object id -eq $questCreated.id).Count -eq 1) 'Created quest missing'
    $questUpdated = Invoke-RestMethod "$questBase/api/quests/$($questCreated.id)" -Method Patch -ContentType 'application/json' -Body '{"completed":true}'
    Assert-Quest ($questUpdated.completed -eq $true) 'PATCH did not update quest'

    Assert-Status Post /api/quests '{"title":" ","subject":"Docker"}' 400
    Assert-Status Post /api/quests '{"title":"Missing subject"}' 400
    Assert-Status Post /api/quests '[]' 400
    Assert-Status Post /api/quests '{invalid' 400
    Assert-Status Patch "/api/quests/$($questCreated.id)" '{"completed":"yes"}' 400
    Assert-Status Patch /api/quests/0 '{"completed":true}' 400
    Assert-Status Patch /api/quests/9223372036854775807 '{"completed":true}' 404
    Assert-Status Post /unknown '{}' 404
    Write-Output 'PASS: page, health, API write/read/update, validation and 404 responses'

    $questOldContainer = docker compose ps -q db
    docker compose down
    if ($LASTEXITCODE -ne 0) { throw 'Compose down failed' }
    docker compose up -d --wait
    if ($LASTEXITCODE -ne 0) { throw 'Compose recreation failed' }
    $questNewContainer = docker compose ps -q db
    Assert-Quest ($questOldContainer -ne $questNewContainer) 'Database container was not recreated'
    $questPersisted = @((Invoke-RestMethod "$questBase/api/quests").quests | Where-Object id -eq $questCreated.id)
    Assert-Quest ($questPersisted.Count -eq 1) 'Quest lost after recreation'
    Assert-Quest ($questPersisted[0].title -eq $questTitle -and $questPersisted[0].completed -eq $true) 'Saved fields changed after recreation'
    Write-Output 'PASS: same record and completion state survived docker compose down / up'
    docker compose ps
} finally {
    Pop-Location
}
