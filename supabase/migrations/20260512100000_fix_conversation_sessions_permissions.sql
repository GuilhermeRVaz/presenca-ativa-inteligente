-- Fix PostgREST access for conversation_sessions.

begin;

create table if not exists busca_ativa_v2.conversation_sessions (
  id uuid primary key default gen_random_uuid(),
  school_id uuid not null,
  sender_jid varchar(255) not null,
  push_name varchar(255),
  guardian_id uuid references busca_ativa_v2.guardians(id) on delete set null,
  student_id uuid references busca_ativa_v2.students(id) on delete set null,
  campaign_id uuid references busca_ativa_v2.campaigns(id) on delete set null,
  last_message_id uuid references busca_ativa_v2.messages(id) on delete set null,
  last_seen_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  resolved boolean not null default false,
  resolution_source varchar(100)
);

delete from busca_ativa_v2.conversation_sessions old_row
using busca_ativa_v2.conversation_sessions keep_row
where old_row.school_id = keep_row.school_id
  and old_row.sender_jid = keep_row.sender_jid
  and (
    old_row.last_seen_at < keep_row.last_seen_at
    or (
      old_row.last_seen_at = keep_row.last_seen_at
      and old_row.id::text < keep_row.id::text
    )
  );

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'conversation_sessions_school_sender_key'
      and conrelid = 'busca_ativa_v2.conversation_sessions'::regclass
  ) then
    alter table busca_ativa_v2.conversation_sessions
      add constraint conversation_sessions_school_sender_key
      unique (school_id, sender_jid);
  end if;
end $$;

create index if not exists idx_conversation_sessions_school_sender
  on busca_ativa_v2.conversation_sessions(school_id, sender_jid);

create index if not exists idx_conversation_sessions_last_seen
  on busca_ativa_v2.conversation_sessions(last_seen_at desc);

create index if not exists idx_conversation_sessions_guardian
  on busca_ativa_v2.conversation_sessions(guardian_id);

alter table busca_ativa_v2.conversation_sessions enable row level security;

drop policy if exists "conversation_sessions_service_access"
  on busca_ativa_v2.conversation_sessions;

create policy "conversation_sessions_service_access"
  on busca_ativa_v2.conversation_sessions
  for all
  to service_role
  using (true)
  with check (true);

grant usage on schema busca_ativa_v2 to service_role, authenticated, anon;
grant select, insert, update, delete on table busca_ativa_v2.conversation_sessions to service_role;
grant select on table busca_ativa_v2.conversation_sessions to authenticated, anon;

notify pgrst, 'reload schema';

commit;
