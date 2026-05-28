import json
from typing import Any
import httpx

from app.api.schemas import WebhookResponse
from app.application.identity_resolver import IdentityResolver
from app.application.session_service import ConversationSessionService
from app.core.config import settings
from app.core.logging import logger
from app.domain.models import InboundMessage
from app.domain.ports import InboundRepository
from app.infrastructure.evolution.payload_parser import EvolutionPayloadParser
from app.infrastructure.evolution.gateway import EvolutionGateway


class InboundService:
    def __init__(self, repository: InboundRepository) -> None:
        self.repository = repository
        self.parser = EvolutionPayloadParser()
        self.evolution_gateway = EvolutionGateway()
        self.session_service = ConversationSessionService(repository)
        self.identity_resolver = IdentityResolver(repository, self.session_service)

    def process(self, payload: dict[str, Any]) -> WebhookResponse:
        print("1. iniciando process")
        recorded = self.record_for_processing(payload)
        if recorded.status != "recorded_for_processing":
            return recorded
        return self.process_recorded(payload=payload, school_id=recorded.school_id)

    def record_for_processing(self, payload: dict[str, Any]) -> WebhookResponse:
        print("2. salvando raw_inbound")
        inbound = self.parser.parse(payload)
        if not inbound.message_id:
            logger.warning("webhook_missing_message_id")
            return WebhookResponse(status="ignored_missing_message_id")

        if inbound.from_me:
            school_id = inbound.school_id or settings.default_school_id
            if school_id and inbound.sender_jid:
                try:
                    self.repository.set_human_takeover(
                        school_id=school_id,
                        sender_jid=inbound.sender_jid,
                    )
                    logger.info("human_takeover_recorded_via_from_me", sender_jid=inbound.sender_jid)
                except Exception as e:
                    logger.warning("failed_to_record_human_takeover", error=str(e), sender_jid=inbound.sender_jid)
            return WebhookResponse(
                status="ignored_from_me",
                message_id=inbound.message_id,
            )

        if not inbound.has_message:
            return WebhookResponse(
                status="ignored_non_message_event",
                message_id=inbound.message_id,
            )

        school_id = inbound.school_id or settings.default_school_id
        if not school_id:
            logger.warning("webhook_missing_school_id", message_id=inbound.message_id)
            return WebhookResponse(
                status="ignored_missing_school_id",
                message_id=inbound.message_id,
            )

        try:
            inserted = self.repository.record_raw_inbound(
                school_id=school_id,
                message_id=inbound.message_id,
                sender_jid=inbound.sender_jid,
                payload=payload,
            )
            if not inserted:
                return WebhookResponse(
                    status="duplicate_ignored",
                    message_id=inbound.message_id,
                    duplicate=True,
                )
        except Exception as e:
            logger.warning("supabase_connection_failed_continuing", error=str(e), message_id=inbound.message_id)
            # Em rede restrita (SEDUC), seguimos mesmo sem persistência inicial para permitir a triagem n8n
            pass

        return WebhookResponse(
            status="recorded_for_processing",
            message_id=inbound.message_id,
            school_id=school_id,
        )

    def process_recorded(
        self,
        *,
        payload: dict[str, Any],
        school_id: str | None = None,
    ) -> WebhookResponse:
        print("3. resolvendo identidade")
        inbound = self.parser.parse(payload)
        resolved_school_id = school_id or inbound.school_id or settings.default_school_id
        if not inbound.message_id:
            return WebhookResponse(status="ignored_missing_message_id")
        if not resolved_school_id:
            return WebhookResponse(
                status="ignored_missing_school_id",
                message_id=inbound.message_id,
            )

        try:
            identity = self.identity_resolver.resolve_identity(
                sender_jid=inbound.sender_jid,
                stanza_id=inbound.stanza_id,
                school_id=resolved_school_id,
                push_name=inbound.push_name,
                message_text=inbound.text,
            )

            if identity.confidence == "UNRESOLVED":
                triggered = False
                if settings.enable_conversational_agent:
                    triggered = self._trigger_n8n_triagem(
                        school_id=resolved_school_id,
                        sender_jid=inbound.sender_jid,
                        raw_message_id=inbound.message_id,
                        text=inbound.text,
                        received_at=inbound.timestamp.isoformat()
                        if inbound.timestamp
                        else None,
                        push_name=inbound.push_name,
                    )
                if triggered:
                    # Re-resolve identity after n8n flow has (potentially) updated the database
                    identity = self.identity_resolver.resolve_identity(
                        sender_jid=inbound.sender_jid,
                        stanza_id=inbound.stanza_id,
                        school_id=resolved_school_id,
                        push_name=inbound.push_name,
                        message_text=inbound.text,
                    )

                # Mesmo se n8n não conseguiu resolver, vamos salvar a resposta com confiança baixa
                # Isso permite que mensagens sejam processadas mesmo sem identidade completa
                if identity.confidence == "UNRESOLVED":
                    logger.info(
                        "identity_still_unresolved_after_n8n",
                        sender_jid=inbound.sender_jid,
                        message_id=inbound.message_id,
                    )
                    try:
                        # Send fallback message asking for the student's name only if it's not a LID
                        if not inbound.sender_jid.endswith("@lid"):
                            self.evolution_gateway.send_text(
                                to_jid=inbound.sender_jid,
                                text="Desculpe, não consegui identificar de qual aluno você está falando. Por favor, responda informando o *nome completo do aluno* para que possamos registrar a justificativa."
                            )
                            logger.info("fallback_message_sent", sender_jid=inbound.sender_jid)
                        else:
                            logger.info("fallback_message_skipped_for_lid", sender_jid=inbound.sender_jid)
                    except Exception as exc:
                        logger.error(
                            "fallback_message_failed",
                            error=str(exc),
                            sender_jid=inbound.sender_jid,
                        )

            # Sempre tentar salvar a resposta, mesmo com identidade não resolvida
            response_id = self._save_response(
                school_id=resolved_school_id,
                inbound=inbound,
                identity=identity,
            )

            # Se a identidade foi resolvida, disparar webhook de chat
            if identity.confidence != "UNRESOLVED":
                student_id = None
                if identity.message:
                    student_id = identity.message.student_id
                elif identity.session:
                    student_id = identity.session.student_id

                if settings.enable_conversational_agent:
                    # Debounce Check: Evitar spam e loops se receber mensagem idêntica em < 30s
                    is_spam = False
                    try:
                        last_resp = self.repository.client.schema("busca_ativa_v2") \
                            .table("responses") \
                            .select("body, received_at") \
                            .eq("school_id", resolved_school_id) \
                            .eq("sender_jid", inbound.sender_jid) \
                            .order("received_at", desc=True) \
                            .limit(2) \
                            .execute()

                        if last_resp.data and len(last_resp.data) >= 2:
                            # O índice 0 é a resposta que acabamos de salvar. O índice 1 é a anterior.
                            previous = last_resp.data[1]
                            prev_body = previous.get("body")
                            prev_received = previous.get("received_at")

                            if prev_body == inbound.text and prev_received:
                                from datetime import datetime, timezone
                                prev_dt = datetime.fromisoformat(prev_received.replace('Z', '+00:00'))
                                now_dt = inbound.timestamp if inbound.timestamp else datetime.now(timezone.utc)
                                if now_dt.tzinfo is None:
                                    now_dt = now_dt.replace(tzinfo=timezone.utc)

                                delta = (now_dt - prev_dt).total_seconds()
                                if delta < 30.0:
                                    is_spam = True
                                    logger.info(
                                        "inbound_conversational_debounced",
                                        sender_jid=inbound.sender_jid,
                                        text=inbound.text,
                                        time_delta_seconds=delta
                                    )
                    except Exception as debounce_exc:
                        logger.warning("debounce_check_failed", error=str(debounce_exc))

                    # Handoff Check: Evitar responder automaticamente se houver atendimento humano ativo (< 24h)
                    is_handoff = False
                    try:
                        latest_resp = self.repository.client.schema("busca_ativa_v2") \
                            .table("responses") \
                            .select("needs_review, handoff_at") \
                            .eq("school_id", resolved_school_id) \
                            .eq("sender_jid", inbound.sender_jid) \
                            .order("received_at", desc=True) \
                            .limit(1) \
                            .execute()
                        
                        if latest_resp.data:
                            last_r = latest_resp.data[0]
                            if last_r.get("needs_review") and last_r.get("handoff_at"):
                                from datetime import datetime, timezone
                                handoff_dt = datetime.fromisoformat(last_r["handoff_at"].replace('Z', '+00:00'))
                                now_dt = datetime.now(timezone.utc)
                                diff_hours = (now_dt - handoff_dt).total_seconds() / 3600.0
                                if diff_hours < 24.0:
                                    is_handoff = True
                                    logger.info(
                                        "conversational_skipped_due_to_active_handoff",
                                        sender_jid=inbound.sender_jid,
                                        handoff_age_hours=diff_hours,
                                    )
                    except Exception as handoff_exc:
                        logger.warning("handoff_check_failed", error=str(handoff_exc))

                    if not is_spam and not is_handoff:
                        self._trigger_n8n_chat_interaction(
                            school_id=resolved_school_id,
                            sender_jid=inbound.sender_jid,
                            response_id=response_id,
                            student_id=student_id,
                            text=inbound.text,
                            received_at=inbound.timestamp.isoformat() if inbound.timestamp else None,
                            push_name=inbound.push_name,
                        )
                    elif is_handoff:
                        logger.info(
                            "conversational_skipped_due_to_handoff_active",
                            sender_jid=inbound.sender_jid,
                            message_id=inbound.message_id,
                        )
                    else:
                        logger.info(
                            "conversational_skipped_due_to_debounce",
                            sender_jid=inbound.sender_jid,
                            message_id=inbound.message_id,
                        )
                else:
                    logger.info(
                        "conversational_skipped_agent_disabled",
                        sender_jid=inbound.sender_jid,
                        message_id=inbound.message_id,
                    )

            self.repository.mark_raw_inbound_processed(
                message_id=inbound.message_id,
                processed=True,
                error=None,
            )
            return WebhookResponse(
                status="processed",
                message_id=inbound.message_id,
                identity_confidence=identity.confidence,
                response_id=response_id,
            )
        except Exception as exc:
            self.repository.mark_raw_inbound_processed(
                message_id=inbound.message_id,
                processed=False,
                error=str(exc),
            )
            logger.exception(
                "inbound_processing_failed",
                message_id=inbound.message_id,
                error=str(exc),
            )
            return WebhookResponse(
                status="error_saved_for_retry",
                message_id=inbound.message_id,
            )

    def _save_response(self, school_id: str, inbound: InboundMessage, identity: Any) -> str:
        message = getattr(identity, 'message', None)
        guardian_id = identity.guardian.id if hasattr(identity, 'guardian') and identity.guardian else None
        campaign_id = message.campaign_id if message else None

        if not campaign_id:
            campaign_id = self.repository.get_active_campaign_for_today(
                school_id=school_id,
            )

        if not message:
            message = self.repository.find_reply_message(
                school_id=school_id,
                campaign_id=campaign_id,
                sender_jid=inbound.sender_jid,
                guardian_id=guardian_id,
            )
            if message:
                campaign_id = message.campaign_id
                guardian_id = guardian_id or message.guardian_id

        self._backup_identified_response(
            school_id=school_id,
            inbound=inbound,
            identity=identity,
            message=message,
            campaign_id=campaign_id,
            guardian_id=guardian_id,
        )

        # Para identidades UNRESOLVED, usar confiança baixa
        confidence = identity.confidence if hasattr(identity, 'confidence') else "LOW"

        return self.repository.save_response(
            school_id=school_id,
            raw_message_id=inbound.message_id,
            sender_jid=inbound.sender_jid,
            body=inbound.text,
            identity_confidence=confidence,
            message_id=message.id if message else None,
            guardian_id=guardian_id,
            campaign_id=campaign_id,
            student_id=message.student_id if message else None,
            received_at=inbound.timestamp,
        )

    def _backup_identified_response(
        self,
        school_id: str,
        inbound: InboundMessage,
        identity: Any,
        message: Any,
        campaign_id: str | None,
        guardian_id: str | None,
    ) -> None:
        if school_id == "school-1":
            return
        backup_dir = settings.project_root / "data" / "local_queue"
        backup_dir.mkdir(parents=True, exist_ok=True)
        path = backup_dir / "identified_responses.jsonl"
        row = {
            "school_id": school_id,
            "raw_message_id": inbound.message_id,
            "sender_jid": inbound.sender_jid,
            "body": inbound.text,
            "identity_confidence": identity.confidence,
            "message_id": message.id if message else None,
            "guardian_id": guardian_id,
            "campaign_id": campaign_id,
            "student_id": message.student_id if message else None,
            "received_at": inbound.timestamp.isoformat() if inbound.timestamp else None,
            "source": "inbound_processing_backup",
        }
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _trigger_n8n_triagem(
        self,
        school_id: str,
        sender_jid: str,
        raw_message_id: str,
        text: str | None,
        received_at: str | None,
        push_name: str | None = None,
    ) -> bool:
        """
        Dispara webhook para o n8n quando a identidade é UNRESOLVED.
        Retorna True se o n8n resolveu a identidade com sucesso.
        """
        if not settings.n8n_webhook_url:
            return False

        payload = {
            "school_id": school_id,
            "lid_jid": sender_jid,
            "sender_jid": sender_jid,
            "raw_message_id": raw_message_id,
            "message_text": text or "",
            "received_at": received_at,
            "push_name": push_name,
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(settings.n8n_webhook_url, json=payload)
                response.raise_for_status()
                data = response.json()
                logger.info(
                    "n8n_triagem_triggered",
                    school_id=school_id,
                    sender_jid=sender_jid,
                    response=data,
                )
                return data.get("status") == "success"
        except httpx.HTTPStatusError as exc:
            response = exc.response
            logger.warning(
                "n8n_triagem_trigger_failed",
                error=str(exc),
                url=settings.n8n_webhook_url,
                school_id=school_id,
                status_code=response.status_code,
                response_body=response.text[:500],
            )
            return False
        except httpx.RequestError as exc:
            logger.warning(
                "n8n_triagem_trigger_failed",
                error=str(exc),
                url=settings.n8n_webhook_url,
                school_id=school_id,
                request_error_type=type(exc).__name__,
            )
            return False
        except Exception as exc:
            logger.warning(
                "n8n_triagem_trigger_failed",
                error=str(exc),
                url=settings.n8n_webhook_url,
                school_id=school_id,
                error_type=type(exc).__name__,
            )
            return False

    def _trigger_n8n_chat_interaction(
        self,
        school_id: str,
        sender_jid: str,
        response_id: str,
        student_id: str | None,
        text: str,
        received_at: str | None,
        push_name: str | None = None,
    ) -> bool:
        """
        Dispara webhook para o n8n para tratar a interação de chat conversacional.
        """
        if not settings.n8n_chat_webhook_url:
            logger.warning("n8n_chat_webhook_url_not_configured")
            return False

        payload = {
            "school_id": school_id,
            "sender_jid": sender_jid,
            "response_id": response_id,
            "student_id": student_id,
            "message_text": text or "",
            "received_at": received_at,
            "push_name": push_name,
        }

        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.post(settings.n8n_chat_webhook_url, json=payload)
                response.raise_for_status()
                data = response.json()
                logger.info(
                    "n8n_chat_interaction_triggered",
                    school_id=school_id,
                    sender_jid=sender_jid,
                    response=data,
                )
                return True
        except Exception as exc:
            logger.warning(
                "n8n_chat_interaction_trigger_failed",
                error=str(exc),
                url=settings.n8n_chat_webhook_url,
                school_id=school_id,
            )
            return False

