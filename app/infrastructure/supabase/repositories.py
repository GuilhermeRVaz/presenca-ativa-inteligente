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
    def __init__(self) -> None:
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if not settings.supabase_url or not settings.supabase_key:
                raise RuntimeError("SUPABASE_URL and SUPABASE_KEY are required")
            if create_client is None:
                raise RuntimeError("supabase-py is not installed")
            options = SyncClientOptions(postgrest_client_timeout=300.0)
            self._client = create_client(
                settings.supabase_url,
                settings.supabase_key,
                options=options,
            )
        return self._client

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
    ) -> tuple[str, bool]:
        """
        Grava uma resposta de responsável na tabela `responses` com suporte a `reason`.
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

    @staticmethod
    def _require_data(response: Any, operation: str) -> list[dict[str, Any]]:
        data = getattr(response, "data", None)
        if not data:
            raise RuntimeError(f"Supabase {operation} failed: empty response data")
        return data

    @staticmethod
    def _execute_with_retry(
        operation_call: Any, *, operation: str, attempts: int = 3
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return operation_call()
            except Exception as exc:
                last_error = exc
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
