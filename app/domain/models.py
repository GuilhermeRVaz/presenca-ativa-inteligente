from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class InboundMessage:
    message_id: str
    sender_jid: str
    push_name: str | None
    text: str
    timestamp: datetime | None
    stanza_id: str | None
    from_me: bool
    has_message: bool
    school_id: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class GuardianRecord:
    id: str
    name: str
    phone_e164: str | None
    wa_jid: str | None


@dataclass(frozen=True)
class StudentRecord:
    id: str
    name: str
    class_name: str
    ra: str


@dataclass(frozen=True)
class CampaignRecord:
    id: str
    name: str
    absence_days: str


@dataclass(frozen=True)
class MessageRecord:
    id: str
    school_id: str
    campaign_id: str
    student_id: str
    guardian_id: str
    wa_jid: str | None
    evolution_msg_id: str | None
    sent_at: datetime | None
    guardian: GuardianRecord | None = None


@dataclass(frozen=True)
class IdentityMapRecord:
    guardian: GuardianRecord | None
    confidence: str


@dataclass(frozen=True)
class OutboundContext:
    student: StudentRecord
    guardian: GuardianRecord
    campaign: CampaignRecord


@dataclass(frozen=True)
class SendResult:
    success: bool
    provider_message_id: str | None = None
    error: str | None = None
    mock: bool = False


@dataclass(frozen=True)
class ConversationSessionRecord:
    id: str
    school_id: str
    sender_jid: str
    push_name: str | None
    guardian_id: str | None
    student_id: str | None
    campaign_id: str | None
    last_message_id: str | None
    last_seen_at: datetime
    created_at: datetime
    resolved: bool
    resolution_source: str | None
