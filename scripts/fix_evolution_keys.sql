-- PASSO 1: Apagar as sessions da instância escola-decia (limpa as chaves corrompidas)
DELETE FROM "Session" WHERE "sessionId" LIKE '%419d1988%';

-- PASSO 2: Verificar que foi apagado
SELECT count(*) as sessions_restantes FROM "Session" WHERE "sessionId" LIKE '%419d1988%';

-- PASSO 3: Ver o status atual da instância no banco
SELECT id, name, "connectionStatus", "ownerJid" FROM "Instance" WHERE name = 'escola-decia';
