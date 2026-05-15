-- Busca Ativa Escolar V2 - production correlation indexes

begin;

create unique index if not exists idx_messages_evolution_unique
  on busca_ativa_v2.messages(school_id, evolution_msg_id)
  where evolution_msg_id is not null;

comment on index busca_ativa_v2.idx_messages_evolution_unique is
  'Garante que o mesmo ID retornado pela Evolution nao gere duplicidade outbound por escola.';

create index if not exists idx_responses_sender_jid
  on busca_ativa_v2.responses(sender_jid);

comment on index busca_ativa_v2.idx_responses_sender_jid is
  'Acelera buscas e auditoria por remetente inbound, incluindo LID e JID WhatsApp.';

create index if not exists idx_raw_inbound_message_id
  on busca_ativa_v2.raw_inbound(message_id);

comment on index busca_ativa_v2.idx_raw_inbound_message_id is
  'Indice explicito para debug e rastreio por message_id, alem da constraint unique.';

commit;
