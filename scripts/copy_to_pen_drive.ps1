$src = "c:\Users\user\presenca-ativa-inteligente"
$dst = "D:\PAI-Presenca-Ativa_Inteligente"

if (-not (Test-Path $dst)) {
    New-Item -ItemType Directory -Path $dst -Force | Out-Null
}

$filesToCopy = @(
    "TUTORIAL_REPLICACAO_NOVA_ESCOLA.md",
    "Manual_Replicacao_Presenca_Ativa_Inteligente.docx",
    "README.md",
    ".env.example",
    "docker-compose.yml",
    "Dockerfile",
    "requirements.txt",
    "painel.py",
    "workflow_triagem_final.json",
    "workflow_triagem_rag.json",
    "workflow_rag_teste_validado.json"
)

foreach ($f in $filesToCopy) {
    $srcFile = Join-Path $src $f
    if (Test-Path $srcFile) {
        Copy-Item -Path $srcFile -Destination (Join-Path $dst $f) -Force
        Write-Host "COPIADO: $f"
    }
}

$dirsToCopy = @("app", "pages", "migrations", "scripts", ".agent")

foreach ($d in $dirsToCopy) {
    $srcDir = Join-Path $src $d
    $dstDir = Join-Path $dst $d
    if (Test-Path $srcDir) {
        robocopy $srcDir $dstDir /E /XD __pycache__ .pytest_cache /XF *.pyc ~$* /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
        Write-Host "PASTA COPIADA: $d"
    }
}

Write-Host "`n=== ESTRUTURA COPIADA EM D:\PAI-Presenca-Ativa_Inteligente ==="
Get-ChildItem -Path $dst | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize
