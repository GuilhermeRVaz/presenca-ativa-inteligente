-- Migration: 004_add_handoff_fields_to_responses
-- Description: Adiciona colunas para detalhar o desvio para atendimento humano na tabela de respostas.

ALTER TABLE busca_ativa_v2.responses 
ADD COLUMN IF NOT EXISTS handoff_reason TEXT,
ADD COLUMN IF NOT EXISTS detected_intent TEXT,
ADD COLUMN IF NOT EXISTS risk_level TEXT,
ADD COLUMN IF NOT EXISTS handoff_at TIMESTAMPTZ;

-- Adiciona restrição opcional de validação de valores de risco
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM pg_constraint 
        WHERE conname = 'responses_risk_level_check'
          AND conrelid = 'busca_ativa_v2.responses'::regclass
    ) THEN
        ALTER TABLE busca_ativa_v2.responses
        ADD CONSTRAINT responses_risk_level_check 
        CHECK (risk_level IS NULL OR risk_level IN ('LOW', 'MEDIUM', 'HIGH'));
    END IF;
END $$;

-- Comentários das novas colunas para documentação do esquema
COMMENT ON COLUMN busca_ativa_v2.responses.handoff_reason IS 'Motivo detectado que disparou o handoff humano (ex: agressividade, bullying, juridico).';
COMMENT ON COLUMN busca_ativa_v2.responses.detected_intent IS 'Intenção detectada pela IA 1 (Classificador).';
COMMENT ON COLUMN busca_ativa_v2.responses.risk_level IS 'Nível de risco estimado para o atendimento humano (LOW, MEDIUM, HIGH).';
COMMENT ON COLUMN busca_ativa_v2.responses.handoff_at IS 'Timestamp exato de quando o handoff para atendimento humano foi acionado.';

-- Força a recarga do esquema no PostgREST
NOTIFY pgrst, 'reload schema';
