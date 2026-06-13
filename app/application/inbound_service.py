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

        # Determine optimal debounce sleep time:
        # If the message is just a greeting/short intro, wait longer (e.g., 20s)
        # to allow the user to type their full question or justification.
        # Otherwise, use the standard 8-second window.
        sleep_seconds = 8.0
        try:
            txt = (inbound.text or "").strip().lower()
            # Clean punctuation and check if it's a common short greeting
            clean_txt = "".join(c for c in txt if c.isalnum() or c.isspace()).strip()
            greetings = {
                "bom dia", "boa tarde", "boa noite", "oi", "ola", "olá", "tudo bem", 
                "tudo bem?", "opa", "bomdia", "boatarde", "boanoite", "obrigado", "obrigada",
                "valeu", "grato", "grata", "por favor", "porfavor"
            }
            if clean_txt in greetings or len(clean_txt) <= 8:
                sleep_seconds = 20.0
                logger.info("debounce_extended_for_greeting", sender_jid=sender_jid, sleep_seconds=sleep_seconds, text=txt)
        except Exception as e:
            logger.warning("failed_to_parse_debounce_text_defaulting_to_8s", error=str(e))

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
            # Check if this outbound message is an automated campaign message
            is_campaign = False
            try:
                if hasattr(self.repository, "client") and self.repository.client:
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
                "consulta", "internado", "cirurgia", "atestado", "tratamento", "exame", "remedio", "dentista"
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

                    # Handoff Check: Evitar responder automaticamente se houver atendimento humano ativo (< 24h)
                    is_handoff = False
                    if not is_spam:
                        try:
                            from datetime import datetime, timezone, timedelta
                            now_dt = datetime.now(timezone.utc)
                            since_dt = now_dt - timedelta(hours=24)

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
            with httpx.Client(timeout=30.0) as client:
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


