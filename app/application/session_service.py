import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.domain.models import ConversationSessionRecord
from app.infrastructure.supabase.repositories import SupabaseRepository

logger = logging.getLogger(__name__)


class ConversationSessionService:
    def __init__(self, repository: SupabaseRepository):
        self.repository = repository

    def record_interaction(
        self,
        *,
        school_id: str,
        sender_jid: str,
        push_name: str | None = None,
        last_message_id: str | None = None,
    ) -> ConversationSessionRecord | None:
        if not settings.use_session_correlation:
            return None

        try:
            return self.repository.upsert_session(
                school_id=school_id,
                sender_jid=sender_jid,
                push_name=push_name,
                last_message_id=last_message_id,
            )
        except Exception as e:
            logger.error(f"Failed to record session interaction: {e}")
            return None

    def get_active_session(
        self,
        *,
        school_id: str,
        sender_jid: str,
    ) -> ConversationSessionRecord | None:
        if not settings.use_session_correlation:
            return None
            
        try:
            return self.repository.find_active_session(
                school_id=school_id,
                sender_jid=sender_jid,
            )
        except Exception as e:
            logger.error(f"Failed to get active session: {e}")
            return None

    def resolve_session_identity(
        self,
        *,
        school_id: str,
        sender_jid: str,
        guardian_id: str,
        student_id: str | None = None,
        campaign_id: str | None = None,
        resolution_source: str | None = None,
    ) -> ConversationSessionRecord | None:
        if not settings.use_session_correlation:
            return None
            
        try:
            return self.repository.upsert_session(
                school_id=school_id,
                sender_jid=sender_jid,
                guardian_id=guardian_id,
                student_id=student_id,
                campaign_id=campaign_id,
                resolved=True,
                resolution_source=resolution_source,
            )
        except Exception as e:
            logger.error(f"Failed to resolve session identity: {e}")
            return None
