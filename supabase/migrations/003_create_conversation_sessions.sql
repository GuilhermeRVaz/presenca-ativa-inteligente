-- Migration: 003_create_conversation_sessions
-- Description: Criacao da tabela de sessoes para correlacao contextual de mensagens inbound/outbound.

CREATE TABLE IF NOT EXISTS busca_ativa_v2.conversation_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id UUID NOT NULL,
    sender_jid VARCHAR(255) NOT NULL,
    push_name VARCHAR(255),
    guardian_id UUID REFERENCES busca_ativa_v2.guardians(id) ON DELETE SET NULL,
    student_id UUID REFERENCES busca_ativa_v2.students(id) ON DELETE SET NULL,
    campaign_id UUID REFERENCES busca_ativa_v2.campaigns(id) ON DELETE SET NULL,
    last_message_id UUID REFERENCES busca_ativa_v2.messages(id) ON DELETE SET NULL,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved BOOLEAN NOT NULL DEFAULT FALSE,
    resolution_source VARCHAR(100)
);

-- Necessario para .upsert(..., on_conflict="school_id,sender_jid") via PostgREST.
DELETE FROM busca_ativa_v2.conversation_sessions old_row
USING busca_ativa_v2.conversation_sessions keep_row
WHERE old_row.school_id = keep_row.school_id
  AND old_row.sender_jid = keep_row.sender_jid
  AND (
    old_row.last_seen_at < keep_row.last_seen_at
    OR (
      old_row.last_seen_at = keep_row.last_seen_at
      AND old_row.id::text < keep_row.id::text
    )
  );

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'conversation_sessions_school_sender_key'
          AND conrelid = 'busca_ativa_v2.conversation_sessions'::regclass
    ) THEN
        ALTER TABLE busca_ativa_v2.conversation_sessions
            ADD CONSTRAINT conversation_sessions_school_sender_key
            UNIQUE (school_id, sender_jid);
    END IF;
END $$;

-- Indices para melhorar a performance nas buscas contextuais.
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_school_sender
    ON busca_ativa_v2.conversation_sessions(school_id, sender_jid);

CREATE INDEX IF NOT EXISTS idx_conversation_sessions_last_seen
    ON busca_ativa_v2.conversation_sessions(last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_conversation_sessions_guardian
    ON busca_ativa_v2.conversation_sessions(guardian_id);

-- Comentarios da tabela e colunas.
COMMENT ON TABLE busca_ativa_v2.conversation_sessions IS 'Armazena janelas de contexto conversacional para mapear contatos (incluindo @lid) para guardioes e alunos de forma persistente.';
COMMENT ON COLUMN busca_ativa_v2.conversation_sessions.resolved IS 'Verdadeiro se a sessao ja foi vinculada a um responsavel/aluno com confianca.';
COMMENT ON COLUMN busca_ativa_v2.conversation_sessions.resolution_source IS 'Origem da resolucao da identidade (ex: outbound_context, manual, push_name, phone_map).';

ALTER TABLE busca_ativa_v2.conversation_sessions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "conversation_sessions_service_access" ON busca_ativa_v2.conversation_sessions;
CREATE POLICY "conversation_sessions_service_access"
    ON busca_ativa_v2.conversation_sessions
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

GRANT USAGE ON SCHEMA busca_ativa_v2 TO service_role, authenticated, anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE busca_ativa_v2.conversation_sessions TO service_role;
GRANT SELECT ON TABLE busca_ativa_v2.conversation_sessions TO authenticated, anon;

NOTIFY pgrst, 'reload schema';
