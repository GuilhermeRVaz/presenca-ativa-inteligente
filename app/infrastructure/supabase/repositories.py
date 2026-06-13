import hashlib
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

try:
    from supabase import create_client
    from supabase.lib.client_options import SyncClientOptions
except ImportError:  # pragma: no cover
    create_client = None  # type: ignore[assignment]
    SyncClientOptions = None  # type: ignore[assignment]

# ──────────────────────────────────────────────────────────────────────────────
# MONKEY-PATCH: Retentativas globais para qualquer consulta Supabase/Postgrest
# ──────────────────────────────────────────────────────────────────────────────
try:
    from postgrest._sync.request_builder import SyncQueryRequestBuilder
    
    _original_postgrest_execute = SyncQueryRequestBuilder.execute
    
    def _robust_postgrest_execute(self, *args, **kwargs):
        import time
        last_error = None
        for attempt in range(1, 4):
            try:
                return _original_postgrest_execute(self, *args, **kwargs)
            except Exception as exc:
                last_error = exc
                err_str = str(exc).lower()
                exc_class = exc.__class__.__name__
                
                is_network_err = (
                    "connect" in err_str or 
                    "timeout" in err_str or 
                    "getaddrinfo" in err_str or 
                    "connection" in err_str or
                    "http" in exc_class.lower() or
                    "timeout" in exc_class.lower() or
                    "error" in exc_class.lower()
                )
                if "apierror" in exc_class.lower() or "postgrest" in exc.__class__.__module__:
                    is_network_err = False
                    
                if not is_network_err:
                    raise exc
                    
                if attempt >= 3:
                    break
                time.sleep(2 ** attempt)
        raise last_error

    SyncQueryRequestBuilder.execute = _robust_postgrest_execute
except Exception:
    pass
# ──────────────────────────────────────────────────────────────────────────────

from app.core.config import settings
from app.domain.models import (
    CampaignRecord,
    GuardianRecord,
    IdentityMapRecord,
    MessageRecord,
    OutboundContext,
    StudentRecord,
    ConversationSessionRecord,
)


class SupabaseRepository:
    _offline_until = 0.0
    # Cache singleton de clients por timeout: evita o custo de ~1.4s do create_client() a cada request
    _cached_clients: dict[float, Any] = {}

    @classmethod
    def mark_offline(cls, duration: float = 30.0):
        cls._offline_until = time.time() + duration

    @classmethod
    def is_offline(cls) -> bool:
        return time.time() < cls._offline_until

    def __init__(self, *, timeout: float = 15.0, attempts: int = 3) -> None:
        self.timeout = timeout
        self.attempts = attempts

    @property
    def client(self):
        if self.is_offline():
            raise RuntimeError("Supabase client is offline (marked offline temporarily).")
        # Retorna client em cache se já existir para este timeout
        if self.timeout not in SupabaseRepository._cached_clients:
            if not settings.supabase_url or not settings.supabase_key:
                raise RuntimeError("SUPABASE_URL and SUPABASE_KEY are required")
            if create_client is None:
                raise RuntimeError("supabase-py is not installed")
            options = SyncClientOptions(postgrest_client_timeout=self.timeout)
            SupabaseRepository._cached_clients[self.timeout] = create_client(
                settings.supabase_url,
                settings.supabase_key,
                options=options,
            )
        return SupabaseRepository._cached_clients[self.timeout]

    def record_raw_inbound(
        self,
        *,
        school_id: str,
        message_id: str,
        sender_jid: str,
        payload: dict[str, Any],
    ) -> bool:
        response = (
            self.client.schema("busca_ativa_v2")
            .rpc(
                "record_raw_inbound",
                {
                    "p_school_id": school_id,
                    "p_message_id": message_id,
                    "p_sender_jid": sender_jid,
                    "p_payload": payload,
                },
            )
            .execute()
        )
        return bool(response.data)

    def mark_raw_inbound_processed(
        self,
        *,
        message_id: str,
        processed: bool,
        error: str | None,
    ) -> None:
        def operation():
            return (
                self.client.schema("busca_ativa_v2")
                .table("raw_inbound")
                .update({"processed": processed, "processing_error": error})
                .eq("message_id", message_id)
                .execute()
            )

        self._execute_with_retry(operation, operation="mark_raw_inbound_processed")

    def list_unprocessed_raw_inbound(self, *, limit: int = 100) -> list[dict[str, Any]]:
        def operation():
            return (
                self.client.schema("busca_ativa_v2")
                .table("raw_inbound")
                .select(
                    "id,school_id,message_id,sender_jid,payload,received_at,processing_error"
                )
                .eq("processed", False)
                .order("received_at", desc=False)
                .limit(limit)
                .execute()
            )

        response = self._execute_with_retry(
            operation, operation="list_unprocessed_raw_inbound"
        )
        return response.data or []

    def find_identity_by_jid(
        self,
        *,
        school_id: str,
        sender_jid: str,
    ) -> IdentityMapRecord | None:
        def operation():
            query = (
                self.client.schema("busca_ativa_v2")
                .table("phone_identity_map")
                .select("confidence, guardian_id")
                .eq("school_id", school_id)
            )
            if sender_jid.endswith("@lid"):
                query = query.eq("lid_jid", sender_jid)
            else:
                query = query.eq("wa_jid", sender_jid)
            return query.limit(1).execute()

        response = self._execute_with_retry(operation, operation="find_identity_by_jid")
        rows = response.data or []
        if not rows:
            return None
        row = rows[0]
        guardian = self.get_guardian_by_id(str(row.get("guardian_id") or ""))
        return IdentityMapRecord(
            guardian=guardian,
            confidence=str(row.get("confidence") or ""),
        )

    def find_active_session(
        self,
        *,
        school_id: str,
        sender_jid: str,
    ) -> ConversationSessionRecord | None:
        def operation():
            return (
                self.client.schema("busca_ativa_v2")
                .table("conversation_sessions")
                .select("*")
                .eq("school_id", school_id)
                .eq("sender_jid", sender_jid)
                .limit(1)
                .execute()
            )

        rows = (
            self._execute_with_retry(operation, operation="find_active_session").data
            or []
        )
        return self._session(rows[0]) if rows else None

    def upsert_session(
        self,
        *,
        school_id: str,
        sender_jid: str,
        push_name: str | None = None,
        guardian_id: str | None = None,
        student_id: str | None = None,
        campaign_id: str | None = None,
        last_message_id: str | None = None,
        resolved: bool | None = None,
        resolution_source: str | None = None,
    ) -> ConversationSessionRecord:
        row: dict[str, Any] = {
            "school_id": school_id,
            "sender_jid": sender_jid,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }
        if push_name is not None:
            row["push_name"] = push_name
        if guardian_id is not None:
            row["guardian_id"] = guardian_id
        if student_id is not None:
            row["student_id"] = student_id
        if campaign_id is not None:
            row["campaign_id"] = campaign_id
        if last_message_id is not None:
            row["last_message_id"] = last_message_id
        if resolved is not None:
            row["resolved"] = resolved
        if resolution_source is not None:
            row["resolution_source"] = resolution_source

        def operation():
            return (
                self.client.schema("busca_ativa_v2")
                .table("conversation_sessions")
                .upsert(row, on_conflict="school_id,sender_jid")
                .execute()
            )

        self._execute_with_retry(operation, operation="upsert_session")

        # supabase-py upsert não retorna linhas — busca separada para obter o registro persistido
        fetched = self.find_active_session(school_id=school_id, sender_jid=sender_jid)
        if fetched is None:
            # Fallback: constrói um registro mínimo com os dados enviados
            now = datetime.now(timezone.utc)
            return ConversationSessionRecord(
                id="",
                school_id=school_id,
                sender_jid=sender_jid,
                push_name=push_name,
                guardian_id=guardian_id,
                student_id=student_id,
                campaign_id=campaign_id,
                last_message_id=last_message_id,
                last_seen_at=now,
                created_at=now,
                resolved=resolved or False,
                resolution_source=resolution_source,
            )
        return fetched

    def _session(self, row: dict[str, Any]) -> ConversationSessionRecord:
        return ConversationSessionRecord(
            id=str(row.get("id")),
            school_id=str(row.get("school_id")),
            sender_jid=str(row.get("sender_jid")),
            push_name=row.get("push_name"),
            guardian_id=row.get("guardian_id"),
            student_id=row.get("student_id"),
            campaign_id=row.get("campaign_id"),
            last_message_id=row.get("last_message_id"),
            last_seen_at=self._parse_datetime(row.get("last_seen_at")),
            created_at=self._parse_datetime(row.get("created_at")),
            resolved=bool(row.get("resolved")),
            resolution_source=row.get("resolution_source"),
        )

    def find_message_by_evolution_id(
        self,
        *,
        school_id: str,
        evolution_msg_id: str,
    ) -> MessageRecord | None:
        def operation():
            return (
                self.client.schema("busca_ativa_v2")
                .table("messages")
                .select(
                    "id,school_id,campaign_id,student_id,guardian_id,wa_jid,evolution_msg_id,sent_at"
                )
                .eq("school_id", school_id)
                .eq("evolution_msg_id", evolution_msg_id)
                .limit(1)
                .execute()
            )

        rows = (
            self._execute_with_retry(
                operation, operation="find_message_by_evolution_id"
            ).data
            or []
        )
        return self._message(rows[0]) if rows else None

    def find_message_by_protocol(
        self,
        *,
        school_id: str,
        protocol: str,
    ) -> MessageRecord | None:
        cleaned = "".join(ch for ch in str(protocol or "").upper() if ch.isalnum())
        if cleaned.startswith("P") and len(cleaned) == 7:
            cleaned = cleaned[1:]
        if len(cleaned) != 6:
            return None

        campaigns = (
            self.client.schema("busca_ativa_v2")
            .table("campaigns")
            .select("id")
            .eq("school_id", school_id)
            .in_("status", ["draft", "dispatching", "active"])
            .order("created_at", desc=True)
            .limit(5)
            .execute()
            .data
            or []
        )
        campaign_ids = [str(row["id"]) for row in campaigns if row.get("id")]
        if not campaign_ids:
            return None

        messages = (
            self.client.schema("busca_ativa_v2")
            .table("messages")
            .select(
                "id,school_id,campaign_id,student_id,guardian_id,wa_jid,evolution_msg_id,sent_at,tracking_ref"
            )
            .eq("school_id", school_id)
            .in_("campaign_id", campaign_ids)
            .order("created_at", desc=True)
            .limit(500)
            .execute()
            .data
            or []
        )
        matches = [
            row
            for row in messages
            if self._short_protocol(str(row.get("tracking_ref") or "")) == cleaned
        ]
        if len(matches) != 1:
            return None
        return self._message(matches[0])

    def get_last_outbound_message_for_guardian(
        self,
        *,
        school_id: str,
        guardian_id: str,
        guardian: GuardianRecord | None = None,
    ) -> MessageRecord | None:
        def operation():
            query = (
                self.client.schema("busca_ativa_v2")
                .table("messages")
                .select(
                    "id,school_id,campaign_id,student_id,guardian_id,wa_jid,evolution_msg_id,sent_at"
                )
                .eq("school_id", school_id)
                .eq("guardian_id", guardian_id)
                .not_.is_("sent_at", "null")
                .in_("status", ["sent", "delivered", "read", "replied"])
                .order("sent_at", desc=True)
                .limit(1)
            )
            return query.execute()

        rows = (
            self._execute_with_retry(
                operation, operation="get_last_outbound_message_for_guardian"
            ).data
            or []
        )
        return self._message(rows[0], guardian=guardian) if rows else None

    def find_recent_messages_for_identity(
        self,
        *,
        school_id: str,
        sender_jid: str,
        hours: int,
    ) -> list[MessageRecord]:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        query = (
            self.client.schema("busca_ativa_v2")
            .table("messages")
            .select(
                "id,school_id,campaign_id,student_id,guardian_id,wa_jid,evolution_msg_id,sent_at"
            )
            .eq("school_id", school_id)
            .gte("sent_at", since.isoformat())
            .in_("status", ["sent", "delivered", "read"])
            .order("sent_at", desc=True)
            .limit(20)
        )
        area_code = self._extract_area_code(sender_jid)
        if area_code:
            query = query.like("wa_jid", f"55{area_code}%")

        def operation():
            return query.execute()

        rows = (
            self._execute_with_retry(
                operation, operation="find_recent_messages_for_identity"
            ).data
            or []
        )
        return [self._message(row) for row in rows]

    def find_guardians_by_name(
        self, *, school_id: str, name: str
    ) -> list[GuardianRecord]:
        def operation():
            return (
                self.client.schema("busca_ativa_v2")
                .table("guardians")
                .select("id,name,phone_e164,wa_jid")
                .eq("school_id", school_id)
                .ilike("name", f"%{name}%")
                .limit(10)
                .execute()
            )

        rows = (
            self._execute_with_retry(
                operation, operation="find_guardians_by_name"
            ).data
            or []
        )
        return [self._guardian(row) for row in rows if row]

    def get_active_campaign_for_today(self, *, school_id: str) -> str | None:
        today = date.today()
        absence_days = f"{today.day:02d}/{today.month:02d}/{today.year}"

        def operation():
            return (
                self.client.schema("busca_ativa_v2")
                .table("campaigns")
                .select("id")
                .eq("school_id", school_id)
                .eq("absence_days", absence_days)
                .in_("status", ["draft", "dispatching", "active"])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )

        rows = (
            self._execute_with_retry(
                operation, operation="get_active_campaign_for_today"
            ).data
            or []
        )
        return str(rows[0]["id"]) if rows else None

    def find_reply_message(
        self,
        *,
        school_id: str,
        campaign_id: str | None,
        sender_jid: str,
        guardian_id: str | None = None,
    ) -> MessageRecord | None:
        """
        Tenta encontrar a mensagem original que o pai está respondendo.
        Usa o sender_jid (que pode ser um LID) e tenta traduzir para o JID original.
        """
        # Se for um @lid, tentamos resolver para o wa_jid (@s.whatsapp.net) original
        search_jids = [sender_jid]
        
        # Tenta traduzir LID -> WA JID usando o mapa de identidade
        if sender_jid.endswith("@lid"):
            map_row = self.client.schema("busca_ativa_v2").table("phone_identity_map").select("wa_jid").eq("lid_jid", sender_jid).execute()
            if map_row.data and map_row.data[0].get("wa_jid"):
                search_jids.append(map_row.data[0]["wa_jid"])
            
            # Tenta extrair o número de telefone puro se o JID for numérico
            phone_part = sender_jid.split("@")[0]
            if phone_part.isdigit() and len(phone_part) >= 10:
                wa_jid_fallback = f"{phone_part}@s.whatsapp.net"
                if wa_jid_fallback not in search_jids:
                    search_jids.append(wa_jid_fallback)

        def operation():
            query = (
                self.client.schema("busca_ativa_v2")
                .table("messages")
                .select(
                    "id,school_id,campaign_id,student_id,guardian_id,wa_jid,evolution_msg_id,sent_at"
                )
                .eq("school_id", school_id)
                .not_.is_("sent_at", "null")
                .in_("status", ["sent", "delivered", "read", "replied"])
                .order("sent_at", desc=True)
                .limit(1)
            )
            if campaign_id:
                query = query.eq("campaign_id", campaign_id)
            
            if guardian_id:
                query = query.eq("guardian_id", guardian_id)
            else:
                # Busca por qualquer um dos JIDs identificados (LID ou WA JID original)
                query = query.in_("wa_jid", search_jids)
                
            return query.execute()

        rows = (
            self._execute_with_retry(operation, operation="find_reply_message").data
            or []
        )
        return self._message(rows[0]) if rows else None

    def save_response(
        self,
        *,
        school_id: str,
        raw_message_id: str,
        sender_jid: str,
        body: str,
        identity_confidence: str,
        message_id: str | None,
        guardian_id: str | None,
        campaign_id: str | None,
        student_id: str | None,
        received_at: Any,
        reason: str | None = None,
        ai_confidence: float | None = None,
    ) -> str:
        response_id, _ = self.save_reply(
            school_id=school_id,
            raw_message_id=raw_message_id,
            sender_jid=sender_jid,
            body=body,
            identity_confidence=identity_confidence,
            message_id=message_id,
            guardian_id=guardian_id,
            campaign_id=campaign_id,
            student_id=student_id,
            reason=reason,
            ai_confidence=ai_confidence,
            received_at=received_at,
        )
        return response_id

    def save_reply(
        self,
        *,
        school_id: str,
        raw_message_id: str,
        sender_jid: str,
        body: str,
        identity_confidence: str = "HIGH",
        message_id: str | None,
        guardian_id: str | None,
        campaign_id: str | None,
        student_id: str | None,
        reason: str | None = None,
        ai_confidence: float | None = None,
        received_at: Any = None,
        needs_review: bool | None = None,
        handoff_reason: str | None = None,
        detected_intent: str | None = None,
        risk_level: str | None = None,
    ) -> tuple[str, bool]:
        """
        Grava uma resposta de responsável na tabela `responses` com suporte a `reason` e handoff.
        Retorna (response_id, message_was_marked_replied).
        """
        row: dict[str, Any] = {
            "school_id": school_id,
            "raw_message_id": raw_message_id,
            "sender_jid": sender_jid,
            "body": body,
            "identity_confidence": identity_confidence,
            "message_id": message_id,
            "guardian_id": guardian_id,
            "campaign_id": campaign_id,
            "student_id": student_id,
            "classified": reason is not None,
        }
        if reason:
            row["reason"] = reason
        if ai_confidence is not None:
            row["ai_confidence"] = ai_confidence
        if received_at:
            row["received_at"] = (
                received_at.isoformat()
                if hasattr(received_at, "isoformat")
                else received_at
            )
        if needs_review is not None:
            row["needs_review"] = needs_review
            if needs_review:
                row["handoff_at"] = datetime.now(timezone.utc).isoformat()
        if handoff_reason:
            row["handoff_reason"] = handoff_reason
        if detected_intent:
            row["detected_intent"] = detected_intent
        if risk_level:
            row["risk_level"] = risk_level

        self._execute_with_retry(
            lambda: (
                self.client.schema("busca_ativa_v2")
                .table("responses")
                .upsert(row, on_conflict="raw_message_id")
                .execute()
            ),
            operation="upsert reply",
        )
        
        _fetched = (
            self.client.schema("busca_ativa_v2")
            .table("responses")
            .select("id")
            .eq("raw_message_id", raw_message_id)
            .limit(1)
            .execute()
        )
        response_id = str((_fetched.data or [{}])[0].get("id", ""))

        marked_replied = False
        if message_id:
            self._execute_with_retry(
                lambda: (
                    self.client.schema("busca_ativa_v2")
                    .table("messages")
                    .update({
                        "status": "replied",
                        "replied_at": datetime.now(timezone.utc).isoformat(),
                    })
                    .eq("id", message_id)
                    .execute()
                ),
                operation="mark message replied (reply)",
            )
            marked_replied = True

        return response_id, marked_replied

    def set_human_takeover(self, *, school_id: str, sender_jid: str) -> None:
        """
        Marca que um atendimento humano assumiu a conversa, setando needs_review = True
        e handoff_at = agora na última resposta registrada.
        """
        # Primeiro, buscamos a resposta mais recente
        resp = self._execute_with_retry(
            lambda: (
                self.client.schema("busca_ativa_v2")
                .table("responses")
                .select("id")
                .eq("school_id", school_id)
                .eq("sender_jid", sender_jid)
                .order("received_at", desc=True)
                .limit(1)
                .execute()
            ),
            operation="get latest response for human takeover"
        )
            
        if resp.data:
            latest_id = resp.data[0]["id"]
            self._execute_with_retry(
                lambda: (
                    self.client.schema("busca_ativa_v2")
                    .table("responses")
                    .update({
                        "needs_review": True,
                        "handoff_at": datetime.now(timezone.utc).isoformat(),
                        "handoff_reason": "human_reply"
                    })
                    .eq("id", latest_id)
                    .execute()
                ),
                operation="update response for human takeover"
            )

    def get_outbound_context(
        self,
        *,
        school_id: str,
        student_id: str,
        campaign_id: str,
    ) -> OutboundContext:
        student_rows = (
            self.client.schema("busca_ativa_v2")
            .table("students")
            .select("id,name,class_name,ra")
            .eq("school_id", school_id)
            .eq("id", student_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        campaign_rows = (
            self.client.schema("busca_ativa_v2")
            .table("campaigns")
            .select("id,name,absence_days")
            .eq("school_id", school_id)
            .eq("id", campaign_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        guardian_rows = (
            self.client.schema("busca_ativa_v2")
            .table("student_guardians")
            .select("guardians(id,name,phone_e164,wa_jid)")
            .eq("student_id", student_id)
            .eq("is_primary", True)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not student_rows:
            raise ValueError("student not found")
        if not campaign_rows:
            raise ValueError("campaign not found")
        if not guardian_rows or not guardian_rows[0].get("guardians"):
            raise ValueError("primary guardian not found")
        return OutboundContext(
            student=self._student(student_rows[0]),
            guardian=self._guardian(guardian_rows[0]["guardians"]),
            campaign=self._campaign(campaign_rows[0]),
        )

    def create_outbound_message(
        self,
        *,
        school_id: str,
        campaign_id: str,
        student_id: str,
        guardian_id: str,
        tracking_ref: str,
        wa_jid: str,
        template_id: str,
        body_preview: str,
    ) -> str:
        response = (
            self.client.schema("busca_ativa_v2")
            .table("messages")
            .insert(
                {
                    "school_id": school_id,
                    "campaign_id": campaign_id,
                    "student_id": student_id,
                    "guardian_id": guardian_id,
                    "tracking_ref": tracking_ref,
                    "wa_jid": wa_jid,
                    "template_id": template_id,
                    "body_preview": body_preview,
                    "status": "pending",
                }
            )
            .execute()
        )
        return str(self._require_data(response, "create outbound message")[0]["id"])

    def update_outbound_message_status(
        self,
        *,
        message_id: str,
        status: str,
        evolution_msg_id: str | None,
        error: str | None,
    ) -> None:
        row: dict[str, Any] = {"status": status}
        if evolution_msg_id:
            row["evolution_msg_id"] = evolution_msg_id
        if status == "sent":
            row["sent_at"] = datetime.now(timezone.utc).isoformat()
        response = (
            self.client.schema("busca_ativa_v2")
            .table("messages")
            .update(row)
            .eq("id", message_id)
            .execute()
        )
        self._require_data(response, "update outbound message status")

    def upsert_phone_identity(
        self,
        *,
        school_id: str,
        lid_jid: str | None,
        wa_jid: str | None,
        phone_e164: str | None,
        guardian_id: str | None,
        confidence: str,
        source: str,
    ) -> str | None:
        response = (
            self.client.schema("busca_ativa_v2")
            .rpc(
                "upsert_phone_identity",
                {
                    "p_school_id": school_id,
                    "p_lid_jid": lid_jid,
                    "p_wa_jid": wa_jid,
                    "p_phone_e164": phone_e164,
                    "p_guardian_id": guardian_id,
                    "p_confidence": confidence,
                    "p_source": source,
                },
            )
            .execute()
        )
        if not response.data:
            raise RuntimeError("Supabase RPC upsert_phone_identity returned no data")
        return str(response.data)

    def save_ai_interaction(
        self,
        *,
        response_id: str | None,
        student_id: str | None,
        prompt_version: str,
        model: str,
        input_text: str,
        output_text: str,
        classified_reason: str | None = None,
        risk_level: str | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
        cost: float | None = None,
    ) -> str:
        row: dict[str, Any] = {
            "prompt_version": prompt_version,
            "model": model,
            "input_text": input_text,
            "output_text": output_text,
        }
        if response_id:
            row["response_id"] = response_id
        if student_id:
            row["student_id"] = student_id
        if classified_reason:
            row["classified_reason"] = classified_reason
        if risk_level:
            row["risk_level"] = risk_level
        if tokens_input is not None:
            row["tokens_input"] = tokens_input
        if tokens_output is not None:
            row["tokens_output"] = tokens_output
        if cost is not None:
            row["cost"] = cost

        def operation():
            return (
                self.client.schema("busca_ativa_v2")
                .table("ai_interactions")
                .insert(row)
                .execute()
            )

        response = self._execute_with_retry(operation, operation="save_ai_interaction")
        return str(self._require_data(response, "save_ai_interaction")[0]["id"])

    def get_conversation_context(
        self,
        *,
        school_id: str,
        sender_jid: str,
        limit: int = 5,
        student_id: str | None = None,
    ) -> dict[str, Any]:
        import concurrent.futures
        import logging
        logger = logging.getLogger(__name__)

        wa_jids = [sender_jid]
        reply_to_jid = sender_jid
        guardian_id = None
        student_id = student_id
        student_name = None
        last_reason = None
        status = "active" if not student_id else "resolved"

        # Batch 1 functions to run in parallel
        def get_map():
            query = (
                self.client.schema("busca_ativa_v2")
                .table("phone_identity_map")
                .select("wa_jid, guardian_id")
                .eq("school_id", school_id)
            )
            if sender_jid.endswith("@lid"):
                query = query.eq("lid_jid", sender_jid)
            else:
                query = query.eq("wa_jid", sender_jid)
            return query.limit(1).execute()

        def get_session():
            return (
                self.client.schema("busca_ativa_v2")
                .table("conversation_sessions")
                .select("student_id, resolved, campaign_id")
                .eq("school_id", school_id)
                .eq("sender_jid", sender_jid)
                .limit(1)
                .execute()
            )

        # Consolidate all responses queries for JID (student_id fallback, last_reason, and inbounds) into one!
        def get_all_responses_by_jid():
            return (
                self.client.schema("busca_ativa_v2")
                .table("responses")
                .select("student_id, reason, body, received_at")
                .eq("school_id", school_id)
                .eq("sender_jid", sender_jid)
                .order("received_at", desc=True)
                .execute()
            )

        def get_active_campaign():
            try:
                return self.get_active_campaign_for_today(school_id=school_id)
            except Exception:
                return None

        # Execute Batch 1 sequentially to avoid httpx.Client thread-safety socket issues
        map_res = self._execute_with_retry(get_map, operation="get_conversation_context_identity")
        session_res = self._execute_with_retry(get_session, operation="get_conversation_context_session")
        responses_res = self._execute_with_retry(get_all_responses_by_jid, operation="get_conversation_context_responses")
        active_campaign_id = get_active_campaign()

        # Parse Batch 1 results
        if map_res.data:
            mapped_wa = map_res.data[0].get("wa_jid")
            if mapped_wa and mapped_wa not in wa_jids:
                wa_jids.append(mapped_wa)
            if sender_jid.endswith("@lid") and mapped_wa:
                reply_to_jid = mapped_wa
            guardian_id = map_res.data[0].get("guardian_id")

        campaign_id = None
        if session_res.data:
            if not student_id:
                student_id = session_res.data[0].get("student_id")
            campaign_id = session_res.data[0].get("campaign_id")
            resolved = session_res.data[0].get("resolved")
            if resolved or student_id:
                status = "resolved"

        if not campaign_id:
            campaign_id = active_campaign_id

        responses_data = responses_res.data or []

        # Extract student_id from responses if not in session
        if not student_id:
            for r in responses_data:
                if r.get("student_id") is not None:
                    student_id = r.get("student_id")
                    break

        # Extract last_reason by JID (fallback)
        last_reason_by_jid = None
        for r in responses_data:
            if r.get("reason") is not None:
                last_reason_by_jid = r.get("reason")
                break

        # Process inbound messages
        inbound_msgs = []
        for r in responses_data[:limit]:
            inbound_msgs.append({
                "text": r.get("body"),
                "sender": "guardian",
                "timestamp": r.get("received_at"),
            })

        # Batch 2: Get name, campaign details, outbounds, and last reason by student_id in parallel
        campaign_name = None
        campaign_absence_days = None

        def safe_get_campaign_details():
            if not campaign_id:
                return None
            try:
                return (
                    self.client.schema("busca_ativa_v2")
                    .table("campaigns")
                    .select("name, absence_days")
                    .eq("school_id", school_id)
                    .eq("id", campaign_id)
                    .limit(1)
                    .execute()
                )
            except Exception as exc:
                logger.warning("get_campaign_details_failed", error=str(exc))
                return None

        def safe_get_student_name():
            if not student_id:
                return None
            try:
                return (
                    self.client.schema("busca_ativa_v2")
                    .table("students")
                    .select("name")
                    .eq("school_id", school_id)
                    .eq("id", student_id)
                    .limit(1)
                    .execute()
                )
            except Exception as exc:
                logger.warning("get_student_name_failed", error=str(exc))
                return None

        def safe_get_last_reason_by_student():
            if not student_id:
                return None
            try:
                return (
                    self.client.schema("busca_ativa_v2")
                    .table("responses")
                    .select("reason")
                    .eq("school_id", school_id)
                    .eq("student_id", student_id)
                    .not_.is_("reason", "null")
                    .order("received_at", desc=True)
                    .limit(1)
                    .execute()
                )
            except Exception as exc:
                logger.warning("get_last_reason_by_student_failed", error=str(exc))
                return None

        def get_outbounds():
            query = (
                self.client.schema("busca_ativa_v2")
                .table("messages")
                .select("body_preview, sent_at")
                .eq("school_id", school_id)
                .not_.is_("sent_at", "null")
            )
            if guardian_id:
                query = query.eq("guardian_id", guardian_id)
            else:
                query = query.in_("wa_jid", wa_jids)
            return query.order("sent_at", desc=True).limit(limit).execute()

        # Execute Batch 2 sequentially to avoid httpx.Client thread-safety socket issues
        camp_res = safe_get_campaign_details()
        stu_res = safe_get_student_name()
        reason_res = safe_get_last_reason_by_student()
        outbound_res = self._execute_with_retry(get_outbounds, operation="get_outbound_messages")

        # Parse Batch 2 results
        if camp_res and camp_res.data:
            campaign_name = camp_res.data[0].get("name")
            campaign_absence_days = camp_res.data[0].get("absence_days")

        if stu_res and stu_res.data:
            student_name = stu_res.data[0].get("name")

        if reason_res and reason_res.data:
            last_reason = reason_res.data[0].get("reason")

        if not last_reason:
            last_reason = last_reason_by_jid

        outbound_msgs = []
        for m in (outbound_res.data or []):
            outbound_msgs.append({
                "text": m.get("body_preview"),
                "sender": "bot",
                "timestamp": m.get("sent_at"),
            })

        # Fundir e ordenar por timestamp decrescente, pegar os últimos 'limit' e depois inverter para ficar cronológico
        all_msgs = inbound_msgs + outbound_msgs
        all_msgs = [m for m in all_msgs if m.get("timestamp")]
        all_msgs.sort(key=lambda x: str(x.get("timestamp")), reverse=True)
        
        last_msgs = all_msgs[:limit]
        last_msgs.reverse()

        return {
            "student_id": student_id,
            "student_name": student_name,
            "wa_jid": next((jid for jid in wa_jids if jid and not jid.endswith("@lid")), None),
            "reply_to_jid": reply_to_jid,
            "last_reason": last_reason,
            "status": status,
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "campaign_absence_days": campaign_absence_days,
            "messages": last_msgs,
        }



    @staticmethod
    def _guardian(row: dict[str, Any] | None) -> GuardianRecord | None:
        if not row:
            return None
        return GuardianRecord(
            id=str(row.get("id")),
            name=str(row.get("name") or ""),
            phone_e164=row.get("phone_e164"),
            wa_jid=row.get("wa_jid"),
        )

    def _message(
        self, row: dict[str, Any], guardian: GuardianRecord | None = None
    ) -> MessageRecord:
        return MessageRecord(
            id=str(row.get("id")),
            school_id=str(row.get("school_id")),
            campaign_id=str(row.get("campaign_id")),
            student_id=str(row.get("student_id")),
            guardian_id=str(row.get("guardian_id")),
            wa_jid=row.get("wa_jid"),
            evolution_msg_id=row.get("evolution_msg_id"),
            sent_at=self._parse_datetime(row.get("sent_at")),
            guardian=guardian
            or self.get_guardian_by_id(str(row.get("guardian_id") or "")),
        )

    def get_guardian_by_id(self, guardian_id: str) -> GuardianRecord | None:
        if not guardian_id:
            return None

        def operation():
            return (
                self.client.schema("busca_ativa_v2")
                .table("guardians")
                .select("id,name,phone_e164,wa_jid")
                .eq("id", guardian_id)
                .limit(1)
                .execute()
            )

        rows = (
            self._execute_with_retry(operation, operation="_get_guardian_by_id").data
            or []
        )
        return self._guardian(rows[0]) if rows else None

    @staticmethod
    def _student(row: dict[str, Any]) -> StudentRecord:
        return StudentRecord(
            id=str(row.get("id")),
            name=str(row.get("name") or ""),
            class_name=str(row.get("class_name") or ""),
            ra=str(row.get("ra") or ""),
        )

    @staticmethod
    def _campaign(row: dict[str, Any]) -> CampaignRecord:
        return CampaignRecord(
            id=str(row.get("id")),
            name=str(row.get("name") or ""),
            absence_days=str(row.get("absence_days") or ""),
        )

    @staticmethod
    def _extract_area_code(sender_jid: str) -> str | None:
        digits = "".join(ch for ch in sender_jid.split("@", 1)[0] if ch.isdigit())
        if digits.startswith("55") and len(digits) >= 4:
            return digits[2:4]
        if len(digits) >= 2 and not sender_jid.endswith("@lid"):
            return digits[:2]
        return None

    @staticmethod
    def _short_protocol(tracking_ref: str) -> str:
        return hashlib.sha256(tracking_ref.encode("utf-8")).hexdigest()[:6].upper()

    def search_school_knowledge(
        self,
        *,
        school_id: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if not query:
            return []
        
        # Clean query, split into terms
        import re
        import unicodedata

        def normalize_txt(text: str) -> str:
            nfkd = unicodedata.normalize('NFKD', text)
            return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower()

        normalized_query = normalize_txt(query)
        terms = [t.strip() for t in re.split(r'[\s,\.\?\!\-\:\/]+', normalized_query) if len(t.strip()) > 2]
        
        # If no significant terms, return empty
        if not terms:
            return []

        def execute_query():
            return (
                self.client.schema("busca_ativa_v2")
                .table("school_knowledge")
                .select("category, question, answer")
                .eq("school_id", school_id)
                .eq("is_active", True)
                .execute()
            )

        try:
            # attempts=1: falha rápida sem sleep de retry — o endpoint já retorna lista vazia como fallback
            res = self._execute_with_retry(execute_query, operation="search_school_knowledge", attempts=1)
            rows = res.data or []
            
            # Simple keyword matching and scoring
            scored_rows = []
            for row in rows:
                q_text = normalize_txt(str(row.get("question") or ""))
                a_text = normalize_txt(str(row.get("answer") or ""))
                
                # Count matching terms
                score = 0
                for term in terms:
                    if term in q_text:
                        score += 3  # Higher weight for questions
                    if term in a_text:
                        score += 1  # Lower weight for answers
                
                if score > 0:
                    scored_rows.append((score, row))
            
            # Sort by score desc, and return top 'limit'
            scored_rows.sort(key=lambda x: x[0], reverse=True)
            return [item[1] for item in scored_rows[:limit]]
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"search_school_knowledge_failed: {exc}", exc_info=True)
            return []

    @staticmethod
    def _require_data(response: Any, operation: str) -> list[dict[str, Any]]:
        data = getattr(response, "data", None)
        if not data:
            raise RuntimeError(f"Supabase {operation} failed: empty response data")
        return data

    def _execute_with_retry(
        self, operation_call: Any, *, operation: str, attempts: int | None = None
    ) -> Any:
        if attempts is None:
            attempts = self.attempts

        if SupabaseRepository.is_offline():
            raise RuntimeError(
                f"Supabase {operation} failed: Supabase is marked offline due to previous connection issues."
            )

        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return operation_call()
            except Exception as exc:
                last_error = exc
                err_str = str(exc).lower()
                if "connect" in err_str or "timeout" in err_str or "getaddrinfo" in err_str or "connection" in err_str:
                    if attempts == 1:
                        SupabaseRepository.mark_offline(30.0)
                if attempt >= attempts:
                    break
                time.sleep(2**attempt)
        raise RuntimeError(
            f"Supabase {operation} failed after {attempts} attempts: {last_error!r}"
        ) from last_error

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
