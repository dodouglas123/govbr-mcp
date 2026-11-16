$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot '../..')
try {
    $name = 'govbr-' + [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssfff'Z'") + '.dump'
    $out = Join-Path (Get-Location) 'backups'
    New-Item -ItemType Directory -Path $out -Force | Out-Null
    $wal = '/tmp/' + $name
    try {
        docker compose exec -T postgres pg_dump -Fc -U govbr -d govbr -f $wal
        if ($LASTEXITCODE -ne 0) { throw 'Falha no pg_dump.' }
        docker compose exec -T postgres pg_restore --list $wal | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'O arquivo de backup nao passou na verificacao.' }
        $dest = Join-Path $out $name
        docker compose cp "postgres:${wal}" $dest
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao copiar o backup.' }
        Write-Output $dest
    } finally {
        docker compose exec -T postgres rm -f $wal | Out-Null
    }
} finally {
    Pop-Location
}
