param()

Write-Host "Carregando variáveis do arquivo .env..." -ForegroundColor Cyan

# Lê o arquivo .env ignorando comentários e linhas em branco
Get-Content .env | Where-Object { $_ -match '=' -and $_ -notmatch '^#' } | ForEach-Object {
    $name, $value = $_.Split('=', 2)
    
    # Remove espaços, aspas simples e duplas
    $name = $name.Trim()
    $value = $value.Trim() -replace '^"|"$', '' -replace "^'|'$", ''
    
    [Environment]::SetEnvironmentVariable($name, $value, "Process")
}

Write-Host "Liberando acesso as variáveis de ambiente no n8n..." -ForegroundColor Cyan
[Environment]::SetEnvironmentVariable("N8N_BLOCK_ENV_ACCESS_IN_NODE", "false", "Process")

Write-Host "Iniciando o n8n..." -ForegroundColor Green
npx n8n start
