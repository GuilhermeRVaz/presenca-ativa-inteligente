-- Busca Ativa Escolar V2 - RLS scaffold
-- Policies are intentionally conservative placeholders for later Supabase auth wiring.

begin;

alter table busca_ativa_v2.schools enable row level security;
alter table busca_ativa_v2.students enable row level security;
alter table busca_ativa_v2.guardians enable row level security;
alter table busca_ativa_v2.student_guardians enable row level security;
alter table busca_ativa_v2.phone_identity_map enable row level security;
alter table busca_ativa_v2.campaigns enable row level security;
alter table busca_ativa_v2.messages enable row level security;
alter table busca_ativa_v2.responses enable row level security;
alter table busca_ativa_v2.raw_inbound enable row level security;

comment on table busca_ativa_v2.schools is
  'Escolas/tenants atendidos pelo sistema. RLS habilitado; policies finais dependem da estrategia de auth.';

comment on table busca_ativa_v2.raw_inbound is
  'Log bruto e idempotente de webhooks inbound. RLS habilitado; ingestao deve usar service role/backend controlado.';

commit;
