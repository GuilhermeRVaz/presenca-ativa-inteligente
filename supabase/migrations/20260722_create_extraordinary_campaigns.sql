-- ──────────────────────────────────────────────────────────────────────────────
-- Migração: 20260722_create_extraordinary_campaigns.sql
-- Descrição: Tabelas, colunas e constraints para suporte a Campanhas Extraordinárias e Templates Reutilizáveis
-- Schema: busca_ativa_v2 (totalmente retrocompatível)
-- ──────────────────────────────────────────────────────────────────────────────

-- 1. Tabela de Templates Reutilizáveis de Campanha
CREATE TABLE IF NOT EXISTS busca_ativa_v2.campaign_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id UUID NOT NULL REFERENCES busca_ativa_v2.schools(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'INFORMATIVA',
    base_message TEXT NOT NULL,
    target_audience_filter JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Tabela de Variações de Mensagens Geradas por IA (Anti-Spam)
CREATE TABLE IF NOT EXISTS busca_ativa_v2.campaign_ai_variants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID NOT NULL REFERENCES busca_ativa_v2.campaigns(id) ON DELETE CASCADE,
    variant_index INTEGER NOT NULL,
    message_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_campaign_variant_index UNIQUE (campaign_id, variant_index)
);

-- 3. Adicionar Colunas Opcionais na Tabela Campaigns Existente (Retrocompatíveis)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'busca_ativa_v2' 
        AND table_name = 'campaigns' 
        AND column_name = 'category'
    ) THEN
        ALTER TABLE busca_ativa_v2.campaigns ADD COLUMN category TEXT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'busca_ativa_v2' 
        AND table_name = 'campaigns' 
        AND column_name = 'base_message'
    ) THEN
        ALTER TABLE busca_ativa_v2.campaigns ADD COLUMN base_message TEXT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'busca_ativa_v2' 
        AND table_name = 'campaigns' 
        AND column_name = 'target_filter'
    ) THEN
        ALTER TABLE busca_ativa_v2.campaigns ADD COLUMN target_filter JSONB;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'busca_ativa_v2' 
        AND table_name = 'campaigns' 
        AND column_name = 'template_id'
    ) THEN
        ALTER TABLE busca_ativa_v2.campaigns ADD COLUMN template_id UUID REFERENCES busca_ativa_v2.campaign_templates(id) ON DELETE SET NULL;
    END IF;
END $$;

-- 4. Atualizar Check Constraints da tabela campaigns para aceitar 'extraordinary'
ALTER TABLE busca_ativa_v2.campaigns DROP CONSTRAINT IF EXISTS campaigns_type_check;
ALTER TABLE busca_ativa_v2.campaigns ADD CONSTRAINT campaigns_type_check CHECK (type IN ('absence', 'meeting', 'notice', 'alert', 'extraordinary'));

ALTER TABLE busca_ativa_v2.campaigns DROP CONSTRAINT IF EXISTS campaigns_campaign_type_check;
ALTER TABLE busca_ativa_v2.campaigns ADD CONSTRAINT campaigns_campaign_type_check CHECK (campaign_type IN ('primary', 'followup', 'reactivation', 'manual', 'extraordinary'));

-- Índices para melhoria de performance em relatórios
CREATE INDEX IF NOT EXISTS idx_campaign_templates_school_id ON busca_ativa_v2.campaign_templates(school_id);
CREATE INDEX IF NOT EXISTS idx_campaign_ai_variants_campaign_id ON busca_ativa_v2.campaign_ai_variants(campaign_id);
