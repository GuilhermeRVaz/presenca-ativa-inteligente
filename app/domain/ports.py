from typing import Any, Protocol

from app.domain.models import (
    IdentityMapRecord,
    MessageRecord,
    OutboundContext,
    SendResult,
    GuardianRecord,
)


class IdentityRepository(Protocol):
    def find_identity_by_jid(self, *, school_id: str, sender_jid: str) -> IdentityMapRecord | None: ...
    def get_guardian_by_id(self, guardian_id: str) -> GuardianRecord | None: ...
    def find_message_by_evolution_id(self, *, school_id: str, evolution_msg_id: str) -> MessageRecord | None: ...
    def find_message_by_protocol(self, *, school_id: str, protocol: str) -> MessageRecord | None: ...
    def get_last_outbound_message_for_guardian(
        self,
        *,
        school_id: str,
        guardian_id: str,
        guardian: Any | None = None,
    ) -> MessageRecord | None: ...
    def find_recent_messages_for_identity(self, *, school_id: str, sender_jid: str, hours: int) -> list[MessageRecord]: ...
    def find_guardians_by_name(self, *, school_id: str, name: str) -> list[GuardianRecord]: ...
    def get_active_campaign_for_today(self, *, school_id: str) -> str | None: ...
    def find_reply_message(
        self,
        *,
        school_id: str,
        campaign_id: str | None,
        sender_jid: str,
        guardian_id: str | None = None,
    ) -> MessageRecord | None: ...
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
    ) -> str | None: ...


class InboundRepository(IdentityRepository, Protocol):
    def record_raw_inbound(self, *, school_id: str, message_id: str, sender_jid: str, payload: dict[str, Any]) -> bool: ...
    def mark_raw_inbound_processed(self, *, message_id: str, processed: bool, error: str | None) -> None: ...
    def list_unprocessed_raw_inbound(self, *, limit: int = 100) -> list[dict[str, Any]]: ...
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
    ) -> str: ...


class OutboundRepository(Protocol):
    def get_outbound_context(self, *, school_id: str, student_id: str, campaign_id: str) -> OutboundContext: ...
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
    ) -> str: ...
    def update_outbound_message_status(
        self,
        *,
        message_id: str,
        status: str,
        evolution_msg_id: str | None,
        error: str | None,
    ) -> None: ...
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
    ) -> str | None: ...


class WhatsAppGateway(Protocol):
    def send_text(self, *, to_jid: str, text: str, dry_run: bool = False) -> SendResult: ...
