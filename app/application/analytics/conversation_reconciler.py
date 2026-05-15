import datetime
from typing import Dict, Any

from app.core.logging import logger
from app.infrastructure.supabase.repositories import SupabaseRepository

class ConversationReconciler:
    """
    O Conversation Reconciler é o motor responsável por fechar o loop conversacional.
    Ele atua retrospectivamente: quando o sistema recebe uma resposta que a IA 
    não consegue vincular (ex: sem nome do aluno ou sem protocolo), ele cruza
    o número do remetente (sender_jid) com o histórico recente de mensagens de 
    saída (outbound). 
    
    Se houver correspondência, ele consolida a identidade com alta confiança (HIGH)
    e atualiza a base, garantindo relatórios precisos baseados na sessão de comunicação.
    """

    def __init__(self, repository: SupabaseRepository):
        self.repository = repository
        self.client = repository.client

    def reconcile_unresolved_responses(self, window_hours: int = 48) -> Dict[str, Any]:
        """
        Busca respostas com identity_confidence = 'UNRESOLVED' (ou student_id nulo)
        e tenta reconciliar cruzando com a tabela messages (outbound).
        
        Args:
            window_hours (int): Janela de tempo em horas para buscar o último outbound.
            
        Returns:
            Dict: Métricas operacionais da reconciliação.
        """
        metrics = {
            "unresolved_found": 0,
            "reconciled_success": 0,
            "reconciled_failed": 0,
            "skipped_ambiguous": 0
        }

        try:
            # 1. Buscar respostas não resolvidas
            logger.info("reconciler_start", window_hours=window_hours)
            responses_query = self.client.schema("busca_ativa_v2").table("responses") \
                .select("*") \
                .or_("identity_confidence.eq.UNRESOLVED,student_id.is.null") \
                .execute()

            unresolved = responses_query.data
            metrics["unresolved_found"] = len(unresolved)

            if not unresolved:
                logger.info("reconciler_no_pending_responses")
                return metrics

            # Usar timezone-aware datetime para o filtro de tempo
            now = datetime.datetime.now(datetime.timezone.utc)
            window_start = (now - datetime.timedelta(hours=window_hours)).isoformat()

            # Cache em memória para evitar buscas redundantes por sender_jid
            outbound_cache = {}

            for resp in unresolved:
                sender_jid = resp.get("sender_jid")
                if not sender_jid:
                    continue

                if sender_jid not in outbound_cache:
                    # Buscar histórico de outbound para esse número na janela estipulada
                    outbound_query = self.client.schema("busca_ativa_v2").table("messages") \
                        .select("id, school_id, campaign_id, student_id, guardian_id, wa_jid, created_at") \
                        .eq("wa_jid", sender_jid) \
                        .gte("created_at", window_start) \
                        .order("created_at", desc=True) \
                        .limit(2) \
                        .execute()

                    outbounds = outbound_query.data
                    if not outbounds:
                        outbound_cache[sender_jid] = None
                    else:
                        # Evitar reconciliação ambígua
                        # (ex: se na mesma janela o sistema disparou para 2 alunos diferentes para o mesmo número)
                        if len(outbounds) > 1 and (outbounds[0].get("student_id") != outbounds[1].get("student_id")):
                            outbound_cache[sender_jid] = "AMBIGUOUS"
                        else:
                            outbound_cache[sender_jid] = outbounds[0]

                last_outbound = outbound_cache.get(sender_jid)

                if last_outbound == "AMBIGUOUS":
                    metrics["skipped_ambiguous"] += 1
                    logger.warning("reconciler_ambiguous_outbound_skipped", sender_jid=sender_jid)
                    continue

                if not last_outbound:
                    metrics["reconciled_failed"] += 1
                    logger.info("reconciler_no_outbound_match", sender_jid=sender_jid)
                    continue

                # 2. Reconciliação bem-sucedida: Recuperar IDs
                student_id = last_outbound.get("student_id")
                guardian_id = last_outbound.get("guardian_id")
                campaign_id = last_outbound.get("campaign_id")
                school_id = last_outbound.get("school_id")
                message_id = last_outbound.get("id")

                if not student_id:
                    continue

                # 3. Atualizar a tabela de respostas com os dados consolidados
                update_data = {
                    "student_id": student_id,
                    "guardian_id": guardian_id,
                    "campaign_id": campaign_id,
                    "message_id": message_id,
                    "identity_confidence": "HIGH"
                }

                self.client.schema("busca_ativa_v2").table("responses") \
                    .update(update_data) \
                    .eq("id", resp["id"]) \
                    .execute()

                # 4. Enriquecer/Atualizar o Phone Identity Map (Aprendizado do Motor)
                try:
                    phone_e164 = sender_jid.replace("@s.whatsapp.net", "")
                    self.repository.upsert_phone_identity(
                        school_id=school_id,
                        lid_jid=None,  # Preservamos o comportamento caso n8n não envie
                        wa_jid=sender_jid,
                        phone_e164=phone_e164,
                        guardian_id=guardian_id,
                        confidence="HIGH",
                        source="reconciler"
                    )
                except Exception as e:
                    logger.error("reconciler_phone_identity_update_error", error=str(e), wa_jid=sender_jid)

                metrics["reconciled_success"] += 1
                logger.info(
                    "reconciled_response",
                    response_id=resp["id"],
                    wa_jid=sender_jid,
                    student_id=student_id,
                    campaign_id=campaign_id
                )

            logger.info("reconciler_finished", metrics=metrics)
            return metrics

        except Exception as e:
            logger.error("reconciliation_pipeline_failed", error=str(e))
            raise e
