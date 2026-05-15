# Migrations - Busca Ativa V2

Este diretorio contem migrations SQL versionadas para o schema isolado
`busca_ativa_v2`.

Por padrao, nenhuma migration e aplicada automaticamente. Use o runner em modo
dry-run para validar a ordem e visualizar o SQL consolidado:

```powershell
python scripts/migrate.py dry-run
```

Para validar sintaxe contra um PostgreSQL local de teste, configure
`DATABASE_URL` apontando para um banco local e rode:

```powershell
python scripts/migrate.py apply-local
```

O runner bloqueia URLs com aparencia de Supabase remoto para evitar aplicacao
acidental em producao nesta etapa.
