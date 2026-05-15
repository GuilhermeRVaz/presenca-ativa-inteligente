-- Busca Ativa Escolar V2 - foundational schema
-- Safe for Supabase/PostgreSQL. Does not touch public legacy tables.

begin;

create extension if not exists pgcrypto;

create schema if not exists busca_ativa_v2;

comment on schema busca_ativa_v2 is
  'Schema isolado da reconstrucao Busca Ativa Escolar V2. Mantem as tabelas novas separadas do legado.';

create table if not exists busca_ativa_v2.schema_migrations (
  version text primary key,
  filename text not null,
  checksum_sha256 text not null,
  applied_at timestamptz not null default now()
);

comment on table busca_ativa_v2.schema_migrations is
  'Controle de migrations aplicadas pelo runner local/controlado.';

create table if not exists busca_ativa_v2.schools (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text not null unique,
  api_key_hash text,
  evolution_instance text,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table busca_ativa_v2.schools is
  'Escolas/tenants atendidos pelo sistema. Centraliza isolamento logico por school_id.';
comment on column busca_ativa_v2.schools.api_key_hash is
  'Hash da chave de API da escola. Nao armazenar segredo em texto puro.';

create table if not exists busca_ativa_v2.students (
  id uuid primary key default gen_random_uuid(),
  school_id uuid not null references busca_ativa_v2.schools(id) on delete restrict,
  ra text not null,
  name text not null,
  class_name text not null,
  grade text,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint students_school_ra_unique unique (school_id, ra)
);

comment on table busca_ativa_v2.students is
  'Alunos importados por escola. O RA e unico dentro de cada escola.';

create index if not exists idx_students_school
  on busca_ativa_v2.students(school_id);
create index if not exists idx_students_school_ra
  on busca_ativa_v2.students(school_id, ra);
create index if not exists idx_students_school_class
  on busca_ativa_v2.students(school_id, class_name)
  where active = true;

create table if not exists busca_ativa_v2.guardians (
  id uuid primary key default gen_random_uuid(),
  school_id uuid not null references busca_ativa_v2.schools(id) on delete restrict,
  name text not null,
  phone_e164 text not null,
  wa_jid text,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint guardians_school_phone_unique unique (school_id, phone_e164),
  constraint guardians_phone_digits_check check (phone_e164 ~ '^[0-9]{10,15}$'),
  constraint guardians_wa_jid_check check (
    wa_jid is null or wa_jid ~ '^[0-9]+@s\.whatsapp\.net$'
  )
);

comment on table busca_ativa_v2.guardians is
  'Responsaveis por alunos, normalizados por telefone E.164 sem sinal de +.';
comment on column busca_ativa_v2.guardians.wa_jid is
  'JID WhatsApp numerico usado em envios outbound, ex: 5511999999999@s.whatsapp.net.';

create index if not exists idx_guardians_school_phone
  on busca_ativa_v2.guardians(school_id, phone_e164);
create index if not exists idx_guardians_wa_jid
  on busca_ativa_v2.guardians(wa_jid)
  where wa_jid is not null;

create table if not exists busca_ativa_v2.student_guardians (
  student_id uuid not null references busca_ativa_v2.students(id) on delete cascade,
  guardian_id uuid not null references busca_ativa_v2.guardians(id) on delete cascade,
  relationship text not null default 'responsible',
  is_primary boolean not null default true,
  created_at timestamptz not null default now(),
  primary key (student_id, guardian_id)
);

comment on table busca_ativa_v2.student_guardians is
  'Relacionamento N:N entre alunos e responsaveis, incluindo vinculo principal.';

create index if not exists idx_student_guardians_guardian
  on busca_ativa_v2.student_guardians(guardian_id);

create table if not exists busca_ativa_v2.phone_identity_map (
  id uuid primary key default gen_random_uuid(),
  school_id uuid not null references busca_ativa_v2.schools(id) on delete restrict,
  lid_jid text,
  wa_jid text,
  phone_e164 text,
  guardian_id uuid references busca_ativa_v2.guardians(id) on delete set null,
  confidence text not null,
  source text not null,
  first_seen_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint phone_identity_confidence_check check (confidence in ('HIGH', 'MEDIUM', 'LOW')),
  constraint phone_identity_source_check check (source in ('outbound', 'inbound', 'manual', 'backfill')),
  constraint phone_identity_has_identifier_check check (
    lid_jid is not null or wa_jid is not null or phone_e164 is not null
  ),
  constraint phone_identity_lid_format_check check (
    lid_jid is null or lid_jid like '%@lid'
  ),
  constraint phone_identity_wa_format_check check (
    wa_jid is null or wa_jid ~ '^[0-9]+@s\.whatsapp\.net$'
  ),
  constraint phone_identity_phone_format_check check (
    phone_e164 is null or phone_e164 ~ '^[0-9]{10,15}$'
  ),
  constraint phone_identity_school_lid_unique unique (school_id, lid_jid),
  constraint phone_identity_school_wa_unique unique (school_id, wa_jid)
);

comment on table busca_ativa_v2.phone_identity_map is
  'Ponte de identidade entre LID inbound, JID WhatsApp outbound, telefone real e responsavel.';

create index if not exists idx_pim_lid
  on busca_ativa_v2.phone_identity_map(lid_jid)
  where lid_jid is not null;
create index if not exists idx_pim_wa
  on busca_ativa_v2.phone_identity_map(wa_jid)
  where wa_jid is not null;
create index if not exists idx_pim_phone
  on busca_ativa_v2.phone_identity_map(phone_e164)
  where phone_e164 is not null;
create index if not exists idx_pim_guardian
  on busca_ativa_v2.phone_identity_map(guardian_id)
  where guardian_id is not null;

create table if not exists busca_ativa_v2.campaigns (
  id uuid primary key default gen_random_uuid(),
  school_id uuid not null references busca_ativa_v2.schools(id) on delete restrict,
  name text not null,
  type text not null default 'absence',
  class_filter text[],
  absence_days text not null,
  status text not null default 'draft',
  total_sent integer not null default 0,
  total_replied integer not null default 0,
  dispatched_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint campaigns_type_check check (type in ('absence', 'meeting', 'notice', 'alert')),
  constraint campaigns_status_check check (status in ('draft', 'dispatching', 'active', 'completed', 'cancelled')),
  constraint campaigns_totals_check check (total_sent >= 0 and total_replied >= 0)
);

comment on table busca_ativa_v2.campaigns is
  'Campanhas de comunicacao escolar, como faltas, reunioes, avisos e alertas.';

create index if not exists idx_campaigns_school_created
  on busca_ativa_v2.campaigns(school_id, created_at desc);
create index if not exists idx_campaigns_school_status
  on busca_ativa_v2.campaigns(school_id, status);

create table if not exists busca_ativa_v2.messages (
  id uuid primary key default gen_random_uuid(),
  school_id uuid not null references busca_ativa_v2.schools(id) on delete restrict,
  campaign_id uuid not null references busca_ativa_v2.campaigns(id) on delete cascade,
  student_id uuid not null references busca_ativa_v2.students(id) on delete restrict,
  guardian_id uuid not null references busca_ativa_v2.guardians(id) on delete restrict,
  tracking_ref text not null unique,
  evolution_msg_id text,
  wa_jid text,
  template_id text not null,
  body_preview text,
  status text not null default 'pending',
  sent_at timestamptz,
  delivered_at timestamptz,
  read_at timestamptz,
  replied_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint messages_status_check check (status in ('pending', 'sent', 'delivered', 'read', 'replied', 'failed')),
  constraint messages_wa_jid_check check (
    wa_jid is null or wa_jid ~ '^[0-9]+@s\.whatsapp\.net$'
  )
);

comment on table busca_ativa_v2.messages is
  'Mensagens outbound planejadas/enviadas, sempre ligadas a campanha, aluno e responsavel.';
comment on column busca_ativa_v2.messages.tracking_ref is
  'Referencia injetada no corpo da mensagem para rastreabilidade: CMP...-STU...';
comment on column busca_ativa_v2.messages.evolution_msg_id is
  'ID retornado pela Evolution API para correlacionar respostas por stanza/quoted id.';

create index if not exists idx_messages_campaign
  on busca_ativa_v2.messages(campaign_id);
create index if not exists idx_messages_student
  on busca_ativa_v2.messages(student_id);
create index if not exists idx_messages_guardian
  on busca_ativa_v2.messages(guardian_id);
create index if not exists idx_messages_tracking
  on busca_ativa_v2.messages(tracking_ref);
create index if not exists idx_messages_evolution_id
  on busca_ativa_v2.messages(school_id, evolution_msg_id)
  where evolution_msg_id is not null;
create index if not exists idx_messages_recent_identity
  on busca_ativa_v2.messages(school_id, wa_jid, sent_at desc)
  where sent_at is not null;

create table if not exists busca_ativa_v2.raw_inbound (
  id uuid primary key default gen_random_uuid(),
  school_id uuid references busca_ativa_v2.schools(id) on delete restrict,
  message_id text not null unique,
  sender_jid text,
  payload jsonb not null,
  processed boolean not null default false,
  processing_error text,
  received_at timestamptz not null default now()
);

comment on table busca_ativa_v2.raw_inbound is
  'Log bruto e idempotente de webhooks inbound. Todo inbound deve ser inserido aqui antes do processamento de negocio.';
comment on column busca_ativa_v2.raw_inbound.message_id is
  'ID do evento/mensagem Evolution usado para deduplicacao atomica.';

create index if not exists idx_raw_inbound_school_received
  on busca_ativa_v2.raw_inbound(school_id, received_at desc);
create index if not exists idx_raw_inbound_processed
  on busca_ativa_v2.raw_inbound(processed, received_at);
create index if not exists idx_raw_inbound_payload_gin
  on busca_ativa_v2.raw_inbound using gin(payload);

create table if not exists busca_ativa_v2.responses (
  id uuid primary key default gen_random_uuid(),
  message_id uuid references busca_ativa_v2.messages(id) on delete set null,
  school_id uuid not null references busca_ativa_v2.schools(id) on delete restrict,
  guardian_id uuid references busca_ativa_v2.guardians(id) on delete set null,
  campaign_id uuid references busca_ativa_v2.campaigns(id) on delete set null,
  student_id uuid references busca_ativa_v2.students(id) on delete set null,
  raw_message_id text not null unique,
  sender_jid text not null,
  body text not null,
  identity_confidence text not null,
  classified boolean not null default false,
  reason text,
  ai_confidence double precision,
  is_ack boolean not null default false,
  needs_review boolean not null default false,
  received_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  constraint responses_identity_confidence_check check (
    identity_confidence in ('HIGH', 'MEDIUM', 'LOW', 'UNRESOLVED')
  ),
  constraint responses_reason_check check (
    reason is null or reason in ('ILLNESS', 'WORK', 'TRAVEL', 'FAMILY', 'SCHOOL_ISSUE', 'OTHER')
  ),
  constraint responses_ai_confidence_check check (
    ai_confidence is null or (ai_confidence >= 0 and ai_confidence <= 1)
  )
);

comment on table busca_ativa_v2.responses is
  'Respostas inbound processadas, com correlacao opcional para mensagem, campanha, aluno e responsavel.';
comment on column busca_ativa_v2.responses.raw_message_id is
  'ID bruto Evolution; tambem e a segunda barreira de deduplicacao.';
comment on column busca_ativa_v2.responses.identity_confidence is
  'Confianca da resolucao de identidade: HIGH, MEDIUM, LOW ou UNRESOLVED.';

create index if not exists idx_responses_message
  on busca_ativa_v2.responses(message_id)
  where message_id is not null;
create index if not exists idx_responses_campaign
  on busca_ativa_v2.responses(campaign_id)
  where campaign_id is not null;
create index if not exists idx_responses_student
  on busca_ativa_v2.responses(student_id)
  where student_id is not null;
create index if not exists idx_responses_school_received
  on busca_ativa_v2.responses(school_id, received_at desc);
create index if not exists idx_responses_unresolved
  on busca_ativa_v2.responses(school_id, received_at desc)
  where identity_confidence = 'UNRESOLVED';

commit;
