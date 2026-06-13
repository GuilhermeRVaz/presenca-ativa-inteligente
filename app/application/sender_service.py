import hashlib

from app.api.schemas import DispatchMessageResponse
from app.core.config import settings
from app.core.logging import logger
from app.domain.ports import OutboundRepository, WhatsAppGateway
from app.infrastructure.followup_message_catalog import FollowupMessageCatalog
from app.infrastructure.message_catalog import MessageCatalog


class SenderService:
    def __init__(self, repository: OutboundRepository, gateway: WhatsAppGateway) -> None:
        self.repository = repository
        self.gateway = gateway
        self.catalog = MessageCatalog(school_name=settings.school_name)
        self.followup_catalog = FollowupMessageCatalog(school_name=settings.school_name)

    def send_message(
        self,
        *,
        school_id: str,
        student_id: str,
        campaign_id: str,
        dry_run: bool = False,
    ) -> DispatchMessageResponse:
        context = self.repository.get_outbound_context(
            school_id=school_id,
            student_id=student_id,
            campaign_id=campaign_id,
        )
        if not context.guardian.wa_jid:
            raise ValueError("guardian has no wa_jid")

        tracking_ref = f"CMP{campaign_id}-STU{student_id}"
        catalog = self._select_catalog(context.campaign.name)
        template_id, body = catalog.build_message(
            parent_name=context.guardian.name,
            student_name=context.student.name,
            class_name=context.student.class_name,
            absence_days=context.campaign.absence_days,
            campaign_id=campaign_id,
            unique_key=f"{student_id}|{context.guardian.id}",
        )
        protocol = self._short_protocol(tracking_ref)
        body = f"{body}\n\nProtocolo: {protocol}"

        message_id = self.repository.create_outbound_message(
            school_id=school_id,
            campaign_id=campaign_id,
            student_id=student_id,
            guardian_id=context.guardian.id,
            tracking_ref=tracking_ref,
            wa_jid=context.guardian.wa_jid,
            template_id=template_id,
            body_preview=body[:500],
        )
        # Simula a presenca de digitando por 2 segundos antes do envio
        self.gateway.send_presence(
            to_jid=context.guardian.wa_jid,
            presence="composing",
            delay=2000,
            dry_run=dry_run,
        )
        if not dry_run:
            import time
            time.sleep(2.0)

        send_result = self.gateway.send_text(
            to_jid=context.guardian.wa_jid,
            text=body,
            dry_run=dry_run,
        )
        status = "sent" if send_result.success else "failed"
        self.repository.update_outbound_message_status(
            message_id=message_id,
            status=status,
            evolution_msg_id=send_result.provider_message_id,
            error=send_result.error,
        )

        if send_result.success:
            self.repository.upsert_phone_identity(
                school_id=school_id,
                lid_jid=None,
                wa_jid=context.guardian.wa_jid,
                phone_e164=context.guardian.phone_e164,
                guardian_id=context.guardian.id,
                confidence="HIGH",
                source="outbound",
            )

        logger.info(
            "outbound_message_dispatched",
            message_id=message_id,
            campaign_id=campaign_id,
            student_id=student_id,
            status=status,
        )
        return DispatchMessageResponse(
            ok=send_result.success,
            status=status,
            message_id=message_id,
            evolution_msg_id=send_result.provider_message_id,
            tracking_ref=tracking_ref,
            dry_run=dry_run,
        )

    @staticmethod
    def _short_protocol(tracking_ref: str) -> str:
        digest = hashlib.sha256(tracking_ref.encode("utf-8")).hexdigest()
        return digest[:6].upper()

    def _select_catalog(self, campaign_name: str):
        normalized = (campaign_name or "").strip().lower()
        if "follow" in normalized or "retorno" in normalized or "nao respond" in normalized:
            return self.followup_catalog
        return self.catalog
