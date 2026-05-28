-- Migration 0006: Create AI Interactions Table
-- Add auditing table for AI-driven chat responses and telemetry.

begin;

create table if not exists busca_ativa_v2.ai_interactions (
  id uuid primary key default gen_random_uuid(),
  response_id uuid references busca_ativa_v2.responses(id) on delete set null,
  student_id uuid references busca_ativa_v2.students(id) on delete set null,
  prompt_version text not null,
  model text not null,
  input_text text not null,
  output_text text not null,
  classified_reason text,
  risk_level text,
  tokens_input integer,
  tokens_output integer,
  cost numeric(10, 6),
  created_at timestamptz not null default now(),
  constraint ai_interactions_risk_level_check check (
    risk_level is null or risk_level in ('LOW', 'MEDIUM', 'HIGH')
  )
);

comment on table busca_ativa_v2.ai_interactions is 'Logs e auditoria detalhada de interações e processamento de IA.';
comment on column busca_ativa_v2.ai_interactions.prompt_version is 'Versão estruturada do prompt utilizado no processamento.';
comment on column busca_ativa_v2.ai_interactions.cost is 'Custo estimado da chamada da API da IA em USD.';

-- Indices de Performance
create index if not exists idx_ai_interactions_response
  on busca_ativa_v2.ai_interactions(response_id)
  where response_id is not null;

create index if not exists idx_ai_interactions_student
  on busca_ativa_v2.ai_interactions(student_id)
  where student_id is not null;

create index if not exists idx_ai_interactions_created
  on busca_ativa_v2.ai_interactions(created_at desc);

-- Permissões e RLS
alter table busca_ativa_v2.ai_interactions enable row level security;

drop policy if exists "ai_interactions_service_access"
  on busca_ativa_v2.ai_interactions;

create policy "ai_interactions_service_access"
  on busca_ativa_v2.ai_interactions
  for all
  to service_role
  using (true)
  with check (true);

grant usage on schema busca_ativa_v2 to service_role, authenticated, anon;
grant select, insert, update, delete on table busca_ativa_v2.ai_interactions to service_role;
grant select on table busca_ativa_v2.ai_interactions to authenticated, anon;

notify pgrst, 'reload schema';

commit;

