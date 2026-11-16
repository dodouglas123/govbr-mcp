$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot '../..')
try {
    if (!(Test-Path -LiteralPath '.env')) {
        $buffer = New-Object byte[] 24
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
        $secret = [BitConverter]::ToString($buffer).Replace('-', '').ToLowerInvariant()
        $config = (Get-Content -Raw -Encoding UTF8 .env.example) -replace '(?m)^GOVBR_DB_PASSWORD=\r?$', "GOVBR_DB_PASSWORD=$secret"
        [IO.File]::WriteAllText((Join-Path (Get-Location) '.env'), $config, [Text.UTF8Encoding]::new($false))
    }
    docker compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Configuração do Docker Compose inválida.' }
    docker compose up -d --build --wait --remove-orphans
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao iniciar o GovBR MCP.' }
} finally {
    Pop-Location
}
