from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

from app.core.logging import logger
from app.core.config import settings
from app.domain.models import GuardianRecord, MessageRecord, ConversationSessionRecord
from app.domain.ports import IdentityRepository
from app.application.session_service import ConversationSessionService


@dataclass(frozen=True)
class IdentityResult:
    confidence: str
    guardian: GuardianRecord | None = None
    message: MessageRecord | None = None
    source: str = "unresolved"
    session: ConversationSessionRecord | None = None


class IdentityResolver:
    def __init__(
        self,
        repository: IdentityRepository,
        session_service: ConversationSessionService | None = None,
    ) -> None:
        self.repository = repository
        self.session_service = session_service

    def resolve_identity(
        self,
        *,
        sender_jid: str,
        stanza_id: str | None,
        school_id: str,
        push_name: str | None = None,
        message_text: str | None = None,
    ) -> IdentityResult:
        # Step 0: Record Interaction in Session
        session = None
        if self.session_service and settings.use_session_correlation:
            session = self.session_service.record_interaction(
                school_id=school_id,
                sender_jid=sender_jid,
                push_name=push_name,
            )

        # 1. Prioridade 1: Outbound recente (Stanza / evolution_msg_id)
        if stanza_id:
            message = self.repository.find_message_by_evolution_id(
                school_id=school_id,
                evolution_msg_id=stanza_id,
            )
            if message:
                if message.guardian:
                    if sender_jid.endswith("@lid"):
                        self.repository.upsert_phone_identity(
                            school_id=school_id,
                            lid_jid=sender_jid,
                            wa_jid=message.wa_jid,
                            phone_e164=message.guardian.phone_e164,
                            guardian_id=message.guardian.id,
                            confidence="HIGH",
                            source="inbound",
                        )
                    elif sender_jid.endswith("@s.whatsapp.net"):
                        self.repository.upsert_phone_identity(
                            school_id=school_id,
                            lid_jid=None,
                            wa_jid=sender_jid,
                            phone_e164=message.guardian.phone_e164,
                            guardian_id=message.guardian.id,
                            confidence="HIGH",
                            source="inbound",
                        )
                if session and message.guardian:
                    self.session_service.resolve_session_identity(
                        school_id=school_id,
                        sender_jid=sender_jid,
                        guardian_id=message.guardian.id,
                        student_id=message.student_id,
                        campaign_id=message.campaign_id,
                        resolution_source="stanza_id"
                    )
                return IdentityResult(
                    confidence="HIGH",
                    guardian=message.guardian,
                    message=message,
                    source="stanza_id",
                    session=session,
                )

        # 2. Prioridade 2: Sessão Ativa já vinculada
        protocol = self._extract_protocol(message_text)
        if protocol:
            message = self.repository.find_message_by_protocol(
                school_id=school_id,
                protocol=protocol,
            )
            if message:
                guardian = message.guardian or self.repository.get_guardian_by_id(
                    message.guardian_id
                )
                if guardian:
                    if sender_jid.endswith("@lid"):
                        self.repository.upsert_phone_identity(
                            school_id=school_id,
                            lid_jid=sender_jid,
                            wa_jid=message.wa_jid,
                            phone_e164=guardian.phone_e164,
                            guardian_id=guardian.id,
                            confidence="HIGH",
                            source="inbound",
                        )
                    elif sender_jid.endswith("@s.whatsapp.net"):
                        self.repository.upsert_phone_identity(
                            school_id=school_id,
                            lid_jid=None,
                            wa_jid=sender_jid,
                            phone_e164=guardian.phone_e164,
                            guardian_id=guardian.id,
                            confidence="HIGH",
                            source="inbound",
                        )
                    if session:
                        self.session_service.resolve_session_identity(
                            school_id=school_id,
                            sender_jid=sender_jid,
                            guardian_id=guardian.id,
                            student_id=message.student_id,
                            campaign_id=message.campaign_id,
                            resolution_source="protocol_match",
                        )
                    logger.info(
                        "identity_resolution",
                        strategy="protocol_match",
                        confidence="HIGH",
                        school_id=school_id,
                        sender_jid=sender_jid,
                        guardian_id=guardian.id,
                        message_id=message.id,
                        protocol=protocol,
                    )
                    return IdentityResult(
                        confidence="HIGH",
                        guardian=guardian,
                        message=message,
                        source="protocol_match",
                        session=session,
                    )

        if session and session.resolved and session.guardian_id:
            guardian = self.repository.get_guardian_by_id(session.guardian_id)
            if guardian:
                # Recuperar a ultima mensagem enviada para associar
                message = self._recent_last_message_for_guardian(
                    school_id=school_id,
                    guardian=guardian,
                    sender_jid=sender_jid,
                )
                return IdentityResult(
                    confidence="HIGH",
                    guardian=guardian,
                    message=message,
                    source="conversation_session",
                    session=session,
                )

        # 3. Prioridade 3: Mapas legados (phone_identity_map)
        direct = self.repository.find_identity_by_jid(
            school_id=school_id,
            sender_jid=sender_jid,
        )
        if direct and direct.guardian:
            recent_message = self._recent_last_message_for_guardian(
                school_id=school_id,
                guardian=direct.guardian,
                sender_jid=sender_jid,
            )
            if recent_message:
                if session:
                    self.session_service.resolve_session_identity(
                        school_id=school_id,
                        sender_jid=sender_jid,
                        guardian_id=direct.guardian.id,
                        student_id=recent_message.student_id,
                        campaign_id=recent_message.campaign_id,
                        resolution_source="phone_identity_map_temporal"
                    )
                return IdentityResult(
                    confidence="HIGH",
                    guardian=direct.guardian,
                    message=recent_message,
                    source="temporal_last_message",
                    session=session,
                )
            
            # Se não tem mensagem recente, mas o mapa existe, resolve para Identity sem mensagem
            if session:
                self.session_service.resolve_session_identity(
                    school_id=school_id,
                    sender_jid=sender_jid,
                    guardian_id=direct.guardian.id,
                    resolution_source="phone_identity_map"
                )
            logger.info(
                "identity_resolution",
                strategy="phone_identity_map",
                confidence="HIGH",
                school_id=school_id,
                sender_jid=sender_jid,
                guardian_id=direct.guardian.id,
                reason="guardian_without_recent_message",
            )
            return IdentityResult(
                confidence="HIGH",
                guardian=direct.guardian,
                source="phone_identity_map",
                session=session,
            )

        # 3b. Fallback conservador: se ha um unico outbound recente plausivel,
        # guardar como MEDIUM para nao perder o contexto, sem virar resolucao definitiva.
        recent_messages = self.repository.find_recent_messages_for_identity(
            school_id=school_id,
            sender_jid=sender_jid,
            hours=24,
        )
        if len(recent_messages) == 1:
            message = recent_messages[0]
            if message.guardian and self._is_recent(message.sent_at, hours=24):
                if sender_jid.endswith("@lid"):
                    self.repository.upsert_phone_identity(
                        school_id=school_id,
                        lid_jid=sender_jid,
                        wa_jid=message.wa_jid,
                        phone_e164=message.guardian.phone_e164,
                        guardian_id=message.guardian.id,
                        confidence="MEDIUM",
                        source="inbound",
                    )
                elif sender_jid.endswith("@s.whatsapp.net"):
                    self.repository.upsert_phone_identity(
                        school_id=school_id,
                        lid_jid=None,
                        wa_jid=sender_jid,
                        phone_e164=message.guardian.phone_e164,
                        guardian_id=message.guardian.id,
                        confidence="MEDIUM",
                        source="inbound",
                    )
                logger.info(
                    "identity_resolution",
                    strategy="single_recent_outbound",
                    confidence="MEDIUM",
                    school_id=school_id,
                    sender_jid=sender_jid,
                    guardian_id=message.guardian.id,
                    message_id=message.id,
                )
                return IdentityResult(
                    confidence="MEDIUM",
                    guardian=message.guardian,
                    message=message,
                    source="single_recent_outbound",
                    session=session,
                )

        # 4. Prioridade 4: PushName fuzzy match
        if sender_jid.endswith("@lid") and push_name:
            first_name = push_name.split(" ")[0].strip()
            if first_name and len(first_name) >= 3:
                guardians = self.repository.find_guardians_by_name(
                    school_id=school_id, name=first_name
                )
                if len(guardians) == 1:
                    matched_guardian = guardians[0]
                    message = self._recent_last_message_for_guardian(
                        school_id=school_id,
                        guardian=matched_guardian,
                        sender_jid=sender_jid,
                    )
                    if message:
                        if session:
                            self.session_service.resolve_session_identity(
                                school_id=school_id,
                                sender_jid=sender_jid,
                                guardian_id=matched_guardian.id,
                                student_id=message.student_id,
                                campaign_id=message.campaign_id,
                                resolution_source="push_name_fuzzy"
                            )
                        logger.info(
                            "identity_resolution",
                            strategy="push_name_fuzzy",
                            confidence="HIGH",
                            school_id=school_id,
                            sender_jid=sender_jid,
                            push_name=push_name,
                            guardian_id=matched_guardian.id,
                        )
                        return IdentityResult(
                            confidence="HIGH",
                            guardian=matched_guardian,
                            message=message,
                            source="push_name_fuzzy",
                            session=session,
                        )

        # Se tudo falhar, passará para fallback (Fallback IA). 
        # A sessão continua UNRESOLVED.
        return IdentityResult(confidence="UNRESOLVED", session=session)

    @staticmethod
    def _extract_protocol(message_text: str | None) -> str | None:
        text = str(message_text or "").upper()
        if not text:
            return None

        marker_patterns = [
            r"\bP[-\s]*([0-9A-F]{6})\b",
            r"\b(?:CODIGO|CÓDIGO|PROTOCOLO|COD)\s*(?:DO\s+ALUNO)?\s*[:#-]?\s*P?[-\s]*([0-9A-F]{6})\b",
        ]
        for pattern in marker_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).upper()

        for match in re.finditer(r"\b([0-9A-F]{6})\b", text, flags=re.IGNORECASE):
            token = match.group(1).upper()
            if any(ch in "ABCDEF" for ch in token):
                return token
        return None

    @staticmethod
    def _is_recent(sent_at: datetime | None, *, hours: int) -> bool:
        if sent_at is None:
            return False
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - sent_at <= timedelta(hours=hours)

    def _recent_last_message_for_guardian(
        self,
        *,
        school_id: str,
        guardian: GuardianRecord,
        sender_jid: str,
    ) -> MessageRecord | None:
        message = self.repository.get_last_outbound_message_for_guardian(
            school_id=school_id,
            guardian_id=guardian.id,
            guardian=guardian,
        )
        if not message or message.sent_at is None:
            logger.info(
                "identity_resolution",
                strategy="temporal_last_message",
                confidence="UNRESOLVED",
                school_id=school_id,
                sender_jid=sender_jid,
                guardian_id=guardian.id,
                reason="missing_recent_outbound",
            )
            return None

        sent_at = message.sent_at
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - sent_at
        
        # Aumentamos a janela de correlação baseada na sessão para 72h
        if age > timedelta(hours=72):
            logger.info(
                "identity_resolution",
                strategy="temporal_last_message",
                confidence="UNRESOLVED",
                school_id=school_id,
                sender_jid=sender_jid,
                guardian_id=guardian.id,
                message_id=message.id,
                age_seconds=int(age.total_seconds()),
                reason="last_message_too_old",
            )
            return None

        logger.info(
            "identity_resolution",
            strategy="temporal_last_message",
            confidence="HIGH",
            school_id=school_id,
            sender_jid=sender_jid,
            guardian_id=guardian.id,
            message_id=message.id,
            age_seconds=int(age.total_seconds()),
        )
        return message
