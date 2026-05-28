-- Migration 0007: Add Campaign Type and Follow-up Mapping Columns
-- Adds campaign_type and parent_campaign_id to campaigns table, and origin_message_id to messages table.

begin;

alter table busca_ativa_v2.campaigns
  add column if not exists campaign_type text default 'primary';

-- check constraint
alter table busca_ativa_v2.campaigns
  drop constraint if exists campaigns_campaign_type_check;

alter table busca_ativa_v2.campaigns
  add constraint campaigns_campaign_type_check
  check (campaign_type in ('primary', 'followup', 'reactivation', 'manual'));

comment on column busca_ativa_v2.campaigns.campaign_type is
  'Tipo de campanha para orquestracao (primary, followup, reactivation, manual).';

alter table busca_ativa_v2.campaigns
  add column if not exists parent_campaign_id uuid references busca_ativa_v2.campaigns(id) on delete set null;

alter table busca_ativa_v2.messages
  add column if not exists origin_message_id uuid references busca_ativa_v2.messages(id) on delete set null;

comment on column busca_ativa_v2.campaigns.parent_campaign_id is 'ID da campanha de origem/principal associada a este follow-up.';
comment on column busca_ativa_v2.messages.origin_message_id is 'ID da mensagem original na campanha principal que gerou este follow-up.';

notify pgrst, 'reload schema';

commit;
