-- Busca Ativa Escolar V2 - migration bookkeeping and helper functions

begin;

create or replace function busca_ativa_v2.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

comment on function busca_ativa_v2.touch_updated_at() is
  'Trigger helper para manter updated_at atualizado em alteracoes.';

drop trigger if exists trg_schools_touch_updated_at on busca_ativa_v2.schools;
create trigger trg_schools_touch_updated_at
before update on busca_ativa_v2.schools
for each row execute function busca_ativa_v2.touch_updated_at();

drop trigger if exists trg_students_touch_updated_at on busca_ativa_v2.students;
create trigger trg_students_touch_updated_at
before update on busca_ativa_v2.students
for each row execute function busca_ativa_v2.touch_updated_at();

drop trigger if exists trg_guardians_touch_updated_at on busca_ativa_v2.guardians;
create trigger trg_guardians_touch_updated_at
before update on busca_ativa_v2.guardians
for each row execute function busca_ativa_v2.touch_updated_at();

drop trigger if exists trg_campaigns_touch_updated_at on busca_ativa_v2.campaigns;
create trigger trg_campaigns_touch_updated_at
before update on busca_ativa_v2.campaigns
for each row execute function busca_ativa_v2.touch_updated_at();

drop trigger if exists trg_messages_touch_updated_at on busca_ativa_v2.messages;
create trigger trg_messages_touch_updated_at
before update on busca_ativa_v2.messages
for each row execute function busca_ativa_v2.touch_updated_at();

create or replace function busca_ativa_v2.upsert_phone_identity(
  p_school_id uuid,
  p_lid_jid text,
  p_wa_jid text,
  p_phone_e164 text,
  p_guardian_id uuid,
  p_confidence text,
  p_source text
)
returns uuid
language plpgsql
as $$
declare
  v_id uuid;
begin
  if p_confidence not in ('HIGH', 'MEDIUM', 'LOW') then
    raise exception 'invalid confidence: %', p_confidence;
  end if;

  if p_source not in ('outbound', 'inbound', 'manual', 'backfill') then
    raise exception 'invalid source: %', p_source;
  end if;

  insert into busca_ativa_v2.phone_identity_map (
    school_id,
    lid_jid,
    wa_jid,
    phone_e164,
    guardian_id,
    confidence,
    source,
    updated_at
  )
  values (
    p_school_id,
    nullif(trim(p_lid_jid), ''),
    nullif(trim(p_wa_jid), ''),
    nullif(trim(p_phone_e164), ''),
    p_guardian_id,
    p_confidence,
    p_source,
    now()
  )
  on conflict (school_id, wa_jid) do update set
    lid_jid = coalesce(excluded.lid_jid, busca_ativa_v2.phone_identity_map.lid_jid),
    phone_e164 = coalesce(excluded.phone_e164, busca_ativa_v2.phone_identity_map.phone_e164),
    guardian_id = coalesce(excluded.guardian_id, busca_ativa_v2.phone_identity_map.guardian_id),
    confidence = excluded.confidence,
    source = excluded.source,
    updated_at = now()
  returning id into v_id;

  return v_id;
exception
  when unique_violation then
    update busca_ativa_v2.phone_identity_map
    set
      wa_jid = coalesce(nullif(trim(p_wa_jid), ''), wa_jid),
      phone_e164 = coalesce(nullif(trim(p_phone_e164), ''), phone_e164),
      guardian_id = coalesce(p_guardian_id, guardian_id),
      confidence = p_confidence,
      source = p_source,
      updated_at = now()
    where school_id = p_school_id
      and lid_jid = nullif(trim(p_lid_jid), '')
    returning id into v_id;

    return v_id;
end;
$$;

comment on function busca_ativa_v2.upsert_phone_identity(uuid, text, text, text, uuid, text, text) is
  'Upsert atomico do mapa de identidade WhatsApp. Usado por outbound, inbound, manual e backfill.';

create or replace function busca_ativa_v2.record_raw_inbound(
  p_school_id uuid,
  p_message_id text,
  p_sender_jid text,
  p_payload jsonb
)
returns boolean
language plpgsql
as $$
begin
  insert into busca_ativa_v2.raw_inbound (
    school_id,
    message_id,
    sender_jid,
    payload
  )
  values (
    p_school_id,
    p_message_id,
    p_sender_jid,
    p_payload
  )
  on conflict (message_id) do nothing;

  return found;
end;
$$;

comment on function busca_ativa_v2.record_raw_inbound(uuid, text, text, jsonb) is
  'Primeira operacao do webhook: grava inbound bruto com deduplicacao atomica.';

commit;
