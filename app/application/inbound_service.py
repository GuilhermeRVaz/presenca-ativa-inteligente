import json
from typing import Any
import httpx
import threading
import time

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

    def enqueue_debounced_processing(
        self,
        *,
        payload: dict[str, Any],
        school_id: str,
        background_tasks: Any,
    ) -> None:
        inbound = self.parser.parse(payload)
        sender_jid = inbound.sender_jid
        message_id = inbound.message_id
        if not sender_jid or not message_id:
            logger.warning("debounce_skipped_missing_fields", message_id=message_id, sender_jid=sender_jid)
            
            async def _direct_task():
                from anyio.to_thread import run_sync
                await run_sync(
                    self._execute_consolidated_processing,
                    sender_jid,
                    school_id,
                    message_id,
                    payload
                )
            background_tasks.add_task(_direct_task)
            return

        # Determine optimal debounce sleep time (acumulador de mensagens picadas):
        # Janela base de 18 segundos. Se for saudação ou frase muito curta (<= 12 caracteres),
        # aguarda 25 segundos para dar tempo do responsável digitar os detalhes da falta/dúvida.
        sleep_seconds = 18.0
        try:
            txt = (inbound.text or "").strip().lower()
            clean_txt = "".join(c for c in txt if c.isalnum() or c.isspace()).strip()
            greetings = {
                "bom dia", "boa tarde", "boa noite", "oi", "ola", "olá", "tudo bem", 
                "tudo bem?", "opa", "bomdia", "boatarde", "boanoite", "obrigado", "obrigada",
                "valeu", "grato", "grata", "por favor", "porfavor"
            }
            if clean_txt in greetings or len(clean_txt) <= 12:
                sleep_seconds = 25.0
                logger.info("debounce_extended_for_short_message", sender_jid=sender_jid, sleep_seconds=sleep_seconds, text=txt)
        except Exception as e:
            logger.warning("failed_to_parse_debounce_text_defaulting_to_18s", error=str(e))


        async def _delayed_task():
            import asyncio
            from anyio.to_thread import run_sync
            logger.info("debounce_task_scheduled_waiting", sender_jid=sender_jid, message_id=message_id, sleep_seconds=sleep_seconds)
            await asyncio.sleep(sleep_seconds)
            await run_sync(
                self._execute_consolidated_processing,
                sender_jid,
                school_id,
                message_id,
                payload
            )

        background_tasks.add_task(_delayed_task)
        logger.info("debounce_task_queued", sender_jid=sender_jid, message_id=message_id, sleep_seconds=sleep_seconds)

    def _execute_consolidated_processing(
        self,
        sender_jid: str | None,
        school_id: str,
        trigger_message_id: str | None,
        fallback_payload: dict[str, Any]
    ) -> None:
        logger.info("debounce_task_fired", sender_jid=sender_jid, trigger_message_id=trigger_message_id)

        if not sender_jid or not trigger_message_id:
            self.process_recorded_consolidated(
                payload=fallback_payload,
                school_id=school_id,
                combined_text=self.parser.parse(fallback_payload).text or "",
                message_ids=[trigger_message_id] if trigger_message_id else []
            )
            return

        try:
            latest_res = self.repository.client.schema("busca_ativa_v2") \
                .table("raw_inbound") \
                .select("message_id") \
                .eq("school_id", school_id) \
                .eq("sender_jid", sender_jid) \
                .eq("processed", False) \
                .order("received_at", desc=True) \
                .limit(1) \
                .execute()
            latest_rows = latest_res.data or []
        except Exception as db_exc:
            logger.exception("debounce_db_latest_query_failed", error=str(db_exc), sender_jid=sender_jid)
            latest_rows = []

        if latest_rows:
            latest_msg_id = latest_rows[0].get("message_id")
            if latest_msg_id and latest_msg_id != trigger_message_id:
                logger.info(
                    "debounce_task_discarded_newer_exists",
                    sender_jid=sender_jid,
                    trigger_message_id=trigger_message_id,
                    latest_msg_id=latest_msg_id
                )
                return

        try:
            unprocessed_res = self.repository.client.schema("busca_ativa_v2") \
                .table("raw_inbound") \
                .select("id, message_id, payload") \
                .eq("school_id", school_id) \
                .eq("sender_jid", sender_jid) \
                .eq("processed", False) \
                .order("received_at", desc=False) \
                .execute()
            unprocessed_rows = unprocessed_res.data or []
        except Exception as db_exc:
            logger.exception("debounce_db_query_failed", error=str(db_exc), sender_jid=sender_jid)
            unprocessed_rows = []

        combined_text = ""
        message_ids = []
        latest_payload = fallback_payload
        
        if unprocessed_rows:
            texts = []
            for row in unprocessed_rows:
                row_payload = row.get("payload") or {}
                latest_payload = row_payload
                try:
                    parsed_row = self.parser.parse(row_payload)
                    if parsed_row.text and parsed_row.text.strip():
                        texts.append(parsed_row.text.strip())
                except Exception:
                    pass
                msg_id = row.get("message_id")
                if msg_id:
                    message_ids.append(msg_id)
            
            combined_text = "\n".join(texts)
        
        if not combined_text:
            parsed_fallback = self.parser.parse(fallback_payload)
            combined_text = parsed_fallback.text or ""
            if parsed_fallback.message_id:
                message_ids.append(parsed_fallback.message_id)

        logger.info(
            "debounce_consolidating_and_processing",
            sender_jid=sender_jid,
            messages_count=len(message_ids),
            combined_text=combined_text
        )

        try:
            self.process_recorded_consolidated(
                payload=latest_payload,
                school_id=school_id,
                combined_text=combined_text,
                message_ids=message_ids
            )
        except Exception as exc:
            logger.exception("debounce_processing_failed", sender_jid=sender_jid, error=str(exc))

    def record_for_processing(self, payload: dict[str, Any]) -> WebhookResponse:
        print("2. salvando raw_inbound")
        inbound = self.parser.parse(payload)
        if not inbound.message_id:
            logger.warning("webhook_missing_message_id")
            return WebhookResponse(status="ignored_missing_message_id")

        if inbound.sender_jid and ("@g.us" in inbound.sender_jid or inbound.sender_jid.endswith("@g.us")):
            logger.info("webhook_ignored_group_chat", sender_jid=inbound.sender_jid, message_id=inbound.message_id)
            return WebhookResponse(status="ignored_group_chat", message_id=inbound.message_id)

        if inbound.from_me:
            is_campaign = False
            # Check if this outbound message is recorded in messages table
            try:
                if hasattr(self.repository, "client") and self.repository.client and inbound.message_id:
                    msg_check = self.repository.client.schema("busca_ativa_v2") \
                        .table("messages") \
                        .select("id") \
                        .eq("evolution_msg_id", inbound.message_id) \
                        .limit(1) \
                        .execute()
                    if msg_check.data:
                        is_campaign = True
            except Exception as msg_exc:
                logger.warning("failed_to_check_campaign_message", error=str(msg_exc))

            # Check if text contains initial campaign template markers
            if not is_campaign and inbound.text:
                txt_lower = inbound.text.lower()
                template_markers = [
                    "aqui e da", "aqui é da", "para justificar, responda",
                    "esteve ausente", "faltou nos dias", "ausencia de", "ausência de",
                    "poderia nos informar o motivo", "codigo do aluno:", "código do aluno:",
                    "pedimos que nos informe", "pode nos dizer se esta tudo certo"
                ]
                if any(marker in txt_lower for marker in template_markers):
                    is_campaign = True

            # Check if this matches a recent AI response
            is_ai = False
            if not is_campaign and inbound.text:
                try:
                    if hasattr(self.repository, "client") and self.repository.client:
                        from datetime import datetime, timezone, timedelta
                        since_dt = datetime.now(timezone.utc) - timedelta(seconds=60)
                        ai_match = self.repository.client.schema("busca_ativa_v2") \
                            .table("ai_interactions") \
                            .select("id") \
                            .eq("output_text", inbound.text.strip()) \
                            .gte("created_at", since_dt.isoformat()) \
                            .limit(1) \
                            .execute()
                        if ai_match.data:
                            is_ai = True
                except Exception as ai_exc:
                    logger.warning("failed_to_check_recent_ai_interaction", error=str(ai_exc))
            
            if is_campaign or is_ai:
                logger.info(
                    "outbound_automated_message_ignored_for_takeover",
                    sender_jid=inbound.sender_jid,
                    is_campaign=is_campaign,
                    is_ai=is_ai
                )
            else:
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
                
                # Process manual outbound justification if it contains a protocol
                protocol = self.identity_resolver._extract_protocol(inbound.text)
                if protocol:
                    logger.info("outbound_message_contains_protocol", protocol=protocol, text=inbound.text)
                    try:
                        message = self.repository.find_message_by_protocol(
                            school_id=school_id,
                            protocol=protocol,
                        )
                        if message:
                            reason = self._classify_reason_from_text(inbound.text)
                            from datetime import datetime, timezone
                            if hasattr(self.repository, "save_reply"):
                                self.repository.save_reply(
                                    school_id=school_id,
                                    raw_message_id=f"outbound-{inbound.message_id}",
                                    sender_jid=inbound.sender_jid,
                                    body=inbound.text,
                                    identity_confidence="HIGH",
                                    message_id=message.id,
                                    guardian_id=message.guardian_id,
                                    campaign_id=message.campaign_id,
                                    student_id=message.student_id,
                                    reason=reason,
                                    ai_confidence=1.0,
                                    received_at=inbound.timestamp or datetime.now(timezone.utc),
                                    needs_review=False,
                                    handoff_reason="human_outbound_justification",
                                    detected_intent="JUSTIFICATIVA_FALTA",
                                    risk_level="LOW",
                                )
                            else:
                                self.repository.save_response(
                                    school_id=school_id,
                                    raw_message_id=f"outbound-{inbound.message_id}",
                                    sender_jid=inbound.sender_jid,
                                    body=inbound.text,
                                    identity_confidence="HIGH",
                                    message_id=message.id,
                                    guardian_id=message.guardian_id,
                                    campaign_id=message.campaign_id,
                                    student_id=message.student_id,
                                    received_at=inbound.timestamp or datetime.now(timezone.utc),
                                    reason=reason,
                                    ai_confidence=1.0,
                                )
                            logger.info(
                                "outbound_justification_saved_successfully",
                                student_id=message.student_id,
                                reason=reason,
                            )
                    except Exception as e:
                        logger.warning("failed_to_process_outbound_justification", error=str(e), protocol=protocol)
            
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

    def _classify_reason_from_text(self, text: str) -> str:
        if not text:
            return "OTHER"
        import unicodedata
        
        def normalize_txt(t: str) -> str:
            nfkd = unicodedata.normalize('NFKD', t)
            return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower()
            
        norm = normalize_txt(text)
        
        # Keyword mapping for classification
        keywords = {
            "ILLNESS": [
                "doenca", "doente", "febre", "gripe", "gripo", "dor", "dores", "medico", "hospital", 
                "consulta", "internado", "cirurgia", "atestado", "tratamento", "exame", "remedio", "dentista",
                "oftalmologista", "oftalmo", "oculista", "posto", "upa", "pronto socorro", "ps"
            ],
            "WORK": [
                "trabalho", "trabalhar", "emprego", "servico", "bico", "entrevista"
            ],
            "TRAVEL": [
                "viagem", "viajar", "viajou", "viajando", "mudanca"
            ],
            "FAMILY": [
                "familia", "familiar", "luto", "falecimento", "morte", "funeral", "parente", "acompanhar"
            ],
            "SCHOOL_ISSUE": [
                "transporte", "onibus", "perua", "van", "chuva", "enchente", "estrada"
            ]
        }
        
        for reason, words in keywords.items():
            for word in words:
                if word in norm:
                    return reason
        return "OTHER"

    def process_recorded(
        self,
        *,
        payload: dict[str, Any],
        school_id: str | None = None,
    ) -> WebhookResponse:
        inbound = self.parser.parse(payload)
        resolved_school_id = school_id or inbound.school_id or settings.default_school_id
        if not inbound.message_id:
            return WebhookResponse(status="ignored_missing_message_id")
        return self.process_recorded_consolidated(
            payload=payload,
            school_id=resolved_school_id,
            combined_text=inbound.text or "",
            message_ids=[inbound.message_id]
        )

    def process_recorded_consolidated(
        self,
        *,
        payload: dict[str, Any],
        school_id: str,
        combined_text: str,
        message_ids: list[str],
    ) -> WebhookResponse:
        print("3. resolvendo identidade consolidada")
        inbound = self.parser.parse(payload)
        resolved_school_id = school_id
        
        try:
            identity = self._safe_resolve_identity(inbound, resolved_school_id, combined_text)

            if identity.confidence == "UNRESOLVED":
                triggered = False
                if settings.enable_conversational_agent:
                    triggered = self._trigger_n8n_triagem(
                        school_id=resolved_school_id,
                        sender_jid=inbound.sender_jid,
                        raw_message_id=inbound.message_id,
                        text=combined_text,
                        received_at=inbound.timestamp.isoformat()
                        if inbound.timestamp
                        else None,
                        push_name=inbound.push_name,
                    )
                if triggered:
                    identity = self._safe_resolve_identity(inbound, resolved_school_id, combined_text)

                if identity.confidence == "UNRESOLVED":
                    logger.info(
                        "identity_still_unresolved_after_n8n",
                        sender_jid=inbound.sender_jid,
                        message_id=inbound.message_id,
                    )
                    if not settings.allow_unresolved_conversational_agent:
                        try:
                            self.evolution_gateway.send_text(
                                to_jid=inbound.sender_jid,
                                text="Desculpe, não consegui identificar de qual aluno você está falando. Por favor, responda informando o *nome completo do aluno* e a *turma* para que possamos registrar a justificativa."
                            )
                            logger.info("fallback_message_sent", sender_jid=inbound.sender_jid)
                        except Exception as exc:
                            logger.error(
                                "fallback_message_failed",
                                error=str(exc),
                                sender_jid=inbound.sender_jid,
                            )


            import uuid
            response_id = str(uuid.uuid4())
            try:
                db_response_id = self._save_response(
                    school_id=resolved_school_id,
                    inbound=inbound,
                    identity=identity,
                    text=combined_text,
                )
                if db_response_id:
                    response_id = db_response_id
            except Exception as db_exc:
                logger.warning(
                    "supabase_save_response_failed_continuing",
                    error=str(db_exc),
                    school_id=resolved_school_id,
                    sender_jid=inbound.sender_jid,
                )

            if identity.confidence != "UNRESOLVED" or settings.allow_unresolved_conversational_agent:
                student_id = None
                if identity.message:
                    student_id = identity.message.student_id
                elif identity.session:
                    student_id = identity.session.student_id

                if not combined_text.strip():
                    logger.info("conversational_skipped_empty_text", sender_jid=inbound.sender_jid, message_id=inbound.message_id)
                elif settings.enable_conversational_agent:
                    is_spam = False

                    # Handoff Check: Evitar responder automaticamente se houver atendimento humano ativo (< handoff_lock_hours)
                    is_handoff = False
                    if not is_spam and settings.handoff_lock_hours > 0:
                        try:
                            from datetime import datetime, timezone, timedelta
                            now_dt = datetime.now(timezone.utc)
                            since_dt = now_dt - timedelta(hours=settings.handoff_lock_hours)

                            active_handoff = self.repository.client.schema("busca_ativa_v2") \
                                .table("responses") \
                                .select("handoff_at") \
                                .eq("school_id", resolved_school_id) \
                                .eq("sender_jid", inbound.sender_jid) \
                                .eq("needs_review", True) \
                                .not_.is_("handoff_at", "null") \
                                .gte("handoff_at", since_dt.isoformat()) \
                                .limit(1) \
                                .execute()

                            if active_handoff.data:
                                is_handoff = True
                                handoff_at_str = active_handoff.data[0]["handoff_at"]
                                handoff_dt = datetime.fromisoformat(handoff_at_str.replace('Z', '+00:00'))
                                diff_hours = (now_dt - handoff_dt).total_seconds() / 3600.0
                                logger.info(
                                    "conversational_skipped_due_to_active_handoff",
                                    sender_jid=inbound.sender_jid,
                                    handoff_age_hours=diff_hours,
                                    lock_hours_limit=settings.handoff_lock_hours,
                                )
                        except Exception as handoff_exc:
                            logger.warning("handoff_check_failed", error=str(handoff_exc))

                    if not is_spam and not is_handoff:
                        self._trigger_n8n_chat_interaction(
                            school_id=resolved_school_id,
                            sender_jid=inbound.sender_jid,
                            response_id=response_id,
                            student_id=student_id,
                            text=combined_text,
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

            for m_id in message_ids:
                try:
                    self.repository.mark_raw_inbound_processed(
                        message_id=m_id,
                        processed=True,
                        error=None,
                    )
                except Exception as mark_exc:
                    logger.warning(f"Failed to mark raw inbound processed in db: {mark_exc}")

            return WebhookResponse(
                status="processed",
                message_id=inbound.message_id,
                identity_confidence=identity.confidence,
                response_id=response_id,
            )
        except Exception as exc:
            try:
                self.repository.mark_raw_inbound_processed(
                    message_id=inbound.message_id,
                    processed=False,
                    error=str(exc),
                )
            except Exception as mark_exc:
                logger.warning(f"Failed to mark raw inbound failed in db: {mark_exc}")
            logger.exception(
                "inbound_processing_failed",
                message_id=inbound.message_id,
                error=str(exc),
            )
            return WebhookResponse(
                status="error_saved_for_retry",
                message_id=inbound.message_id,
            )

    def _save_response(self, school_id: str, inbound: InboundMessage, identity: Any, text: str | None = None) -> str:
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

        body_text = text if text is not None else inbound.text

        self._backup_identified_response(
            school_id=school_id,
            inbound=inbound,
            identity=identity,
            message=message,
            campaign_id=campaign_id,
            guardian_id=guardian_id,
            text=body_text,
        )

        # Para identidades UNRESOLVED, usar confiança baixa
        confidence = identity.confidence if hasattr(identity, 'confidence') else "LOW"

        return self.repository.save_response(
            school_id=school_id,
            raw_message_id=inbound.message_id,
            sender_jid=inbound.sender_jid,
            body=body_text,
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
        text: str | None = None,
    ) -> None:
        if school_id == "school-1":
            return
        backup_dir = settings.project_root / "data" / "local_queue"
        backup_dir.mkdir(parents=True, exist_ok=True)
        path = backup_dir / "identified_responses.jsonl"
        body_text = text if text is not None else inbound.text
        row = {
            "school_id": school_id,
            "raw_message_id": inbound.message_id,
            "sender_jid": inbound.sender_jid,
            "body": body_text,
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
                f"n8n_triagem_trigger_failed: HTTPStatusError {exc}",
                url=settings.n8n_webhook_url,
                school_id=school_id,
                status_code=response.status_code,
                response_body=response.text[:500],
            )
            return False
        except httpx.RequestError as exc:
            logger.warning(
                f"n8n_triagem_trigger_failed: RequestError {exc}",
                url=settings.n8n_webhook_url,
                school_id=school_id,
                request_error_type=type(exc).__name__,
            )
            return False
        except Exception as exc:
            logger.warning(
                f"n8n_triagem_trigger_failed: {exc}",
                url=settings.n8n_webhook_url,
                school_id=school_id,
                error_type=type(exc).__name__,
            )
            return False

    def _classify_intent(self, text: str) -> str:
        if not text:
            return "OUTRO"
        import unicodedata
        def norm(t: str) -> str:
            nfkd = unicodedata.normalize('NFKD', t)
            return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower()
        
        txt = norm(text)
        
        # 1. Confirmação de Presença
        confirma_kw = [
            "confirmar", "confirmo", "estarei la", "estarei la", "vou sim", "com certeza",
            "estarei presente", "estaremos la", "estaremos la", "confirmado"
        ]
        if txt.strip() == "1" or any(kw in txt for kw in confirma_kw):
            return "CONFIRMA_PRESENCA"

        # 2. Informar Ausência ou Envio de Representante
        ausencia_kw = [
            "nao vou", "nao vou", "nao posso", "nao posso", "nao consigo", "nao consigo",
            "trabalho esse horario", "estou trabalhando", "estarei viajando", "viagem", "viajar",
            "doente", "padrasto", "marido", "avo", "avo", "representante", "vai a mae", "vai o pai",
            "mandar o", "mandar a"
        ]
        if txt.strip() == "2" or any(kw in txt for kw in ausencia_kw):
            return "INFORMA_AUSENCIA"

        # 3. Dúvidas Logísticas sobre a Reunião
        logistica_kw = [
            "quarta", "horario", "horario", "horas", "local", "onde",
            "endereco", "bairro", "refeitorio", "tolerancia", "tolerancia",
            "filhos", "estacionamento", "atestado", "declaracao", "declaracao",
            "pauta", "assunto", "boletim", "que vem", "quer vem", "data da reuniao"
        ]
        if "?" in text or any(kw in txt for kw in logistica_kw):
            return "LOGISTICA"

        # 4. Saudação simples
        saudacao_kw = ["bom dia", "boa tarde", "boa noite", "oi", "ola", "tudo bem"]
        if any(kw in txt for kw in saudacao_kw):
            return "SAUDACAO"

        return "OUTRO"

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
        Enriquece o payload com contexto completo da campanha (FAQ, base message), intenção classificada
        e aplica trava de deduplicação de 40 segundos para mensagens consecutivas.
        """
        if not settings.n8n_chat_webhook_url:
            logger.warning("n8n_chat_webhook_url_not_configured")
            return False

        detected_intent = self._classify_intent(text)

        # Trava de Cooldown / Deduplicação Inteligente (40 segundos por remetente individual)
        try:
            from datetime import datetime, timezone, timedelta
            since_dt = datetime.now(timezone.utc) - timedelta(seconds=40)
            recent_resp = (
                self.repository.client.schema("busca_ativa_v2")
                .table("responses")
                .select("id, created_at")
                .eq("school_id", school_id)
                .eq("sender_jid", sender_jid)
                .gte("created_at", since_dt.isoformat())
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if recent_resp.data and detected_intent in ["INFORMA_AUSENCIA", "CONFIRMA_PRESENCA", "SAUDACAO"]:
                logger.info(
                    "conversational_suppressed_duplicate_ai_reply_within_cooldown",
                    sender_jid=sender_jid,
                    intent=detected_intent,
                )
                return True
        except Exception as cd_exc:
            logger.warning("cooldown_check_failed", error=str(cd_exc))


        last_outbound_text = None
        campaign_name = None
        campaign_base_message = None
        campaign_faq = None
        campaign_type = None
        campaign_obj = None

        try:
            res_msg = (
                self.repository.client.schema("busca_ativa_v2")
                .table("messages")
                .select("body_preview, metadata, campaigns(id, name, base_message, category, campaign_type, type, target_filter)")
                .eq("wa_jid", sender_jid)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if res_msg.data:
                row = res_msg.data[0]
                last_outbound_text = row.get("body_preview") or (row.get("metadata") or {}).get("formatted_body")
                camp_data = row.get("campaigns") or {}
                campaign_name = camp_data.get("name")
                campaign_base_message = camp_data.get("base_message")
                campaign_type = camp_data.get("campaign_type") or camp_data.get("type") or "extraordinary"
                tf = camp_data.get("target_filter") or {}
                campaign_faq = tf.get("faq")
                campaign_obj = {
                    "id": camp_data.get("id"),
                    "name": campaign_name,
                    "type": campaign_type,
                    "category": camp_data.get("category"),
                    "base_message": campaign_base_message,
                    "faq": campaign_faq,
                }
        except Exception as exc:
            logger.warning("failed_to_fetch_last_outbound_context", error=str(exc))

        payload = {
            "school_id": school_id,
            "sender_jid": sender_jid,
            "response_id": response_id,
            "student_id": student_id,
            "message_text": text or "",
            "received_at": received_at,
            "push_name": push_name,
            "last_outbound_text": last_outbound_text,
            "campaign_name": campaign_name,
            "campaign_base_message": campaign_base_message,
            "campaign_type": campaign_type,
            "campaign_faq": campaign_faq,
            "campaign": campaign_obj,
            "detected_intent": detected_intent,
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(settings.n8n_chat_webhook_url, json=payload)
                response.raise_for_status()
                data = response.json()
                logger.info(
                    "n8n_chat_interaction_triggered",
                    school_id=school_id,
                    sender_jid=sender_jid,
                    intent=detected_intent,
                    response=data,
                )
                return True
        except Exception as exc:
            logger.warning(
                f"n8n_chat_interaction_trigger_failed: {exc}",
                url=settings.n8n_chat_webhook_url,
                school_id=school_id,
            )
            return False

    def _safe_resolve_identity(
        self,
        inbound: InboundMessage,
        school_id: str,
        text: str | None = None,
    ) -> Any:
        try:
            return self.identity_resolver.resolve_identity(
                sender_jid=inbound.sender_jid,
                stanza_id=inbound.stanza_id,
                school_id=school_id,
                push_name=inbound.push_name,
                message_text=text if text is not None else inbound.text,
            )
        except Exception as res_exc:
            logger.warning(
                "identity_resolution_failed_continuing_unresolved",
                error=str(res_exc),
                sender_jid=inbound.sender_jid,
            )
            from app.application.identity_resolver import IdentityResult
            return IdentityResult(
                confidence="UNRESOLVED",
                guardian=None,
                message=None,
                source="unresolved",
                session=None,
            )

    def classify_inbound_message(
        self,
        *,
        school_id: str | None = None,
        sender_jid: str | None = None,
        message_text: str,
        student_name: str | None = None,
        last_reason: str | None = None,
        campaign_name: str | None = None,
        messages_history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Classifica a intenção e o risco da mensagem recebida utilizando OpenAI (ou fallback local).
        Garante retornos estruturados sem falhas de conexão ou timeouts na rede n8n.
        """
        if not message_text or not message_text.strip():
            return {
                "intent": "DESCONHECIDO",
                "category": None,
                "risk_level": "LOW",
                "needs_human": False,
                "confidence": 0.0,
                "needs_review": False,
                "handoff_reason": None,
            }

        if settings.openai_api_key:
            try:
                system_prompt = (
                    "Você é a IA 1 (Classificador) da escola Décia. Seu único objetivo é classificar a intenção e o risco das mensagens recebidas e retornar estritamente um JSON.\n\n"
                    "Campos no JSON:\n"
                    "- intent: 'JUSTIFICATIVA_FALTA' (se o responsável justifica faltas ou atrasos), 'DUVIDA_SECRETARIA' (dúvidas sobre horários, secretaria, documentos, matrículas), 'SAUDACAO' (cumprimentos como olá, bom dia, tudo bem), 'AGRADECIMENTO_DESPEDIDA' (agradecimentos como obrigado, valeu, ou despedidas como tchau, até mais), 'HUMANO' (solicitação explícita de falar com humano), ou 'DESCONHECIDO' (outros assuntos).\n"
                    "- category: 'DOENCA', 'TRABALHO', 'TRAVEL', 'TRANSPORTE', 'FAMILIA', 'OUTRO' (se intent for JUSTIFICATIVA_FALTA), ou null caso contrário.\n"
                    "- risk_level: 'LOW' (baixo risco), 'MEDIUM' (desânimo, recorrência moderada), 'HIGH' (bullying, conflitos graves, problemas jurídicos, ameaças, agressividade, saúde mental grave).\n"
                    "- needs_human: true (se risk_level for HIGH, se houver agressividade/bullying, solicitação explícita ou tom conflituoso), ou false caso contrário.\n"
                    "- confidence: float entre 0.0 e 1.0 (grau de certeza na classificação).\n\n"
                    "Regra de Ouro: Retorne APENAS o JSON. Não adicione texto explicativo ou markdown."
                )

                user_prompt = (
                    f"Contexto:\n"
                    f"- Aluno: {student_name or 'não identificado'}\n"
                    f"- Último Motivo: {last_reason or 'não informado'}\n"
                    f"- Campanha: {campaign_name or 'não informado'}\n\n"
                    f"Histórico Recente:\n{json.dumps(messages_history or [], ensure_ascii=False)}\n\n"
                    f"Mensagem Atual: {message_text}\n\n"
                    f"Retorne agora a classificação JSON estrita."
                )

                with httpx.Client(timeout=12.0) as client:
                    resp = client.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {settings.openai_api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "gpt-4o-mini",
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            "response_format": {"type": "json_object"},
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"].strip()
                    parsed = json.loads(content)

                    intent = parsed.get("intent", "DESCONHECIDO")
                    category = parsed.get("category")
                    risk_level = parsed.get("risk_level", "LOW")
                    needs_human = bool(parsed.get("needs_human", False))
                    confidence = float(parsed.get("confidence", 1.0))
                    needs_review = needs_human

                    if confidence < 0.55:
                        needs_human = True
                        needs_review = True
                        handoff_reason = "baixa_confianca"
                    elif needs_human:
                        handoff_reason = category or "detectado_ia"
                    else:
                        handoff_reason = None

                    return {
                        "intent": intent,
                        "category": category,
                        "risk_level": risk_level,
                        "needs_human": needs_human,
                        "confidence": confidence,
                        "needs_review": needs_review,
                        "handoff_reason": handoff_reason,
                    }
            except Exception as llm_exc:
                logger.warning("openai_classification_failed_using_local_rules", error=str(llm_exc))

        category = self._classify_reason_from_text(message_text)
        intent = self._classify_intent(message_text)
        if intent == "OUTRO":
            intent = "JUSTIFICATIVA_FALTA" if category != "OTHER" else "DESCONHECIDO"

        return {
            "intent": intent,
            "category": category if intent == "JUSTIFICATIVA_FALTA" else None,
            "risk_level": "LOW",
            "needs_human": False,
            "confidence": 0.85,
            "needs_review": False,
            "handoff_reason": None,
        }

    def send_staff_alert(

        self,
        *,
        target_role: str,
        student_name: str | None = None,
        student_class: str | None = None,
        guardian_name: str | None = None,
        guardian_phone: str | None = None,
        alert_reason: str,
        message_summary: str,
        unanswered_question: str | None = None,
        school_id: str | None = None,
    ) -> dict[str, Any]:
        role_upper = (target_role or "").strip().upper()
        if role_upper in ("DIRETOR", "DIRECAO"):
            phone = settings.phone_diretor
            role_name = "Direção (Junior)"
        elif role_upper in ("SECRETARIA", "GERENTE", "ADMINISTRATIVO"):
            phone = settings.phone_secretaria
            role_name = "Secretaria (Paula)"
        elif role_upper in ("VICE_DIRETOR", "VICE", "DISCIPLINA"):
            phone = settings.phone_vice_diretor
            role_name = "Vice-Direção (Anderson)"
        elif role_upper in ("COORDENACAO", "PEDAGOGICO", "COORDENADOR"):
            phone = settings.phone_coordenacao
            role_name = "Coordenação Pedagógica (Lucimara)"
        else:
            phone = settings.phone_diretor
            role_name = f"Equipe ({target_role})"

        student_info = student_name or "Não identificado"
        if student_class:
            student_info += f" ({student_class})"

        guardian_info = guardian_name or "Responsável"
        phone_info = guardian_phone or "Não informado"
        question_block = f"\n❓ *Questão Pendente:* {unanswered_question}" if unanswered_question else ""

        alert_text = (
            f"⚠️ *ALERTA DE ATENDIMENTO ESCOLAR — BUSCA ATIVA* ⚠️\n\n"
            f"Destino: {role_name}\n"
            f"🎓 *Aluno:* {student_info}\n"
            f"👤 *Responsável:* {guardian_info}\n"
            f"📞 *Telefone do Responsável:* {phone_info}\n"
            f"📌 *Motivo do Alerta:* {alert_reason}\n\n"
            f"💬 *Resumo / Mensagem do Responsável:*\n"
            f'"{message_summary}"'
            f"{question_block}\n\n"
            f"_Ação necessária: Por favor, entre em contato ou verifique a ocorrência no sistema._"
        )

        res = self.evolution_gateway.send_text(to_jid=phone, text=alert_text)
        logger.info(
            "staff_alert_dispatched",
            role=target_role,
            phone=phone,
            success=res.success,
            provider_message_id=res.provider_message_id,
            error=res.error,
        )
        return {
            "sent": res.success,
            "recipient_role": role_name,
            "recipient_phone": phone,
            "provider_message_id": res.provider_message_id,
            "error": res.error,
        }

    def generate_emphetic_reply(
        self,
        *,
        student_name: str | None = None,
        category: str | None = None,
        push_name: str | None = None,
        message_text: str = "",
    ) -> str:
        name_display = student_name if student_name and str(student_name).strip().lower() not in ("aluno", "none", "null", "") else None

        if not name_display:
            return (
                "Olá! Agradecemos o envio das informações. "
                "Para que possamos justificar e formalizar no sistema da Escola Décia, "
                "por favor nos informe o *nome completo do aluno* e a *turma* dele."
            )

        cat_upper = (category or "").upper()
        msg_lower = message_text.lower()
        feeling_better = "melhor" in msg_lower or "remedio" in msg_lower or "remédio" in msg_lower or "alta" in msg_lower

        if cat_upper in ("DOENCA", "ILLNESS"):
            better_phrase = " Ficamos felizes em saber que já está se sentindo melhor!" if feeling_better else ""
            return (
                f"Olá! Agradecemos por avisar e confirmar a ausência do(a) estudante *{name_display}*. "
                f"Registramos a justificativa por motivo de saúde no sistema da Escola Décia.{better_phrase} "
                f"Estimamos uma rápida recuperação e melhoras!"
            )
        elif cat_upper in ("TRABALHO", "WORK"):
            return (
                f"Olá! Agradecemos por comunicar a situação do(a) estudante *{name_display}*. "
                f"O registro por motivo de trabalho foi formalizado junto à equipe escolar. Conte conosco!"
            )
        elif cat_upper in ("VIAGEM", "TRAVEL"):
            return (
                f"Olá! Agradecemos por informar a viagem do(a) aluno(a) *{name_display}*. "
                f"Registramos a justificativa no sistema da escola. Uma excelente viagem!"
            )
        elif cat_upper in ("TRANSPORTE", "SCHOOL_ISSUE"):
            return (
                f"Olá! Registramos a justificativa referente às questões de transporte para o(a) estudante *{name_display}*. "
                f"Agradecemos o aviso e estamos à disposição."
            )
        else:
            return (
                f"Olá! Agradecemos o contato e por justificar a falta do(a) aluno(a) *{name_display}*. "
                f"Registramos as informações com cuidado no sistema da Escola Décia."
            )

    def generate_sac_reply(
        self,
        *,
        message_text: str,
        rag_context: list[dict[str, Any]] | None = None,
    ) -> str:
        if rag_context and len(rag_context) > 0:
            info = rag_context[0].get("content") or rag_context[0].get("text") or str(rag_context[0])
            return (
                f"Olá! Agradecemos a sua mensagem para a Escola Décia.\n\n"
                f"Sobre a sua dúvida: {info}\n\n"
                f"Caso precise de mais informações, nossa equipe da secretaria está à disposição!"
            )
        return (
            "Olá! Agradecemos a sua mensagem. Sua dúvida foi registrada com atenção "
            "e nossa equipe da secretaria da Escola Décia entrará em contato em breve para ajudá-lo(a)."
        )




