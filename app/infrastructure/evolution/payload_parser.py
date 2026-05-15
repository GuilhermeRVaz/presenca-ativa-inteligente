from datetime import datetime, timezone
from typing import Any

from app.domain.models import InboundMessage


class EvolutionPayloadParser:
    def parse(self, payload: dict[str, Any]) -> InboundMessage:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        key = data.get("key") if isinstance(data.get("key"), dict) else {}
        message = data.get("message") if isinstance(data.get("message"), dict) else {}

        sender_jid = str(
            key.get("remoteJid")
            or data.get("remoteJid")
            or payload.get("sender_jid")
            or payload.get("from")
            or ""
        ).strip()
        message_id = str(
            key.get("id")
            or data.get("id")
            or payload.get("message_id")
            or payload.get("messageId")
            or ""
        ).strip()
        push_name = str(data.get("pushName") or payload.get("pushName") or "").strip() or None
        
        return InboundMessage(
            message_id=message_id,
            sender_jid=sender_jid,
            push_name=push_name,
            text=self._extract_text(message, payload),
            timestamp=self._extract_timestamp(data, payload),
            stanza_id=self._extract_stanza_id(message, payload),
            from_me=bool(key.get("fromMe") or data.get("fromMe") or payload.get("fromMe")),
            has_message=bool(message),
            school_id=self._extract_school_id(payload),
            raw=payload,
        )

    def _extract_text(self, message: dict[str, Any], payload: dict[str, Any]) -> str:
        conversation = message.get("conversation")
        if conversation is not None:
            return str(conversation)
        extended = message.get("extendedTextMessage")
        if isinstance(extended, dict) and extended.get("text") is not None:
            return str(extended["text"])
        image = message.get("imageMessage")
        if isinstance(image, dict) and image.get("caption") is not None:
            return str(image["caption"])
        return str(payload.get("text") or payload.get("message") or "")

    def _extract_stanza_id(self, message: dict[str, Any], payload: dict[str, Any]) -> str | None:
        extended = message.get("extendedTextMessage")
        context = extended.get("contextInfo") if isinstance(extended, dict) else None
        if not isinstance(context, dict):
            context = message.get("contextInfo") if isinstance(message.get("contextInfo"), dict) else {}
        value = (
            context.get("stanzaId")
            or context.get("quotedMessageId")
            or payload.get("stanzaId")
            or payload.get("quoted_message_id")
        )
        return str(value).strip() if value else None

    def _extract_timestamp(self, data: dict[str, Any], payload: dict[str, Any]) -> datetime | None:
        value = data.get("messageTimestamp") or payload.get("timestamp")
        if value is None:
            return None
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            return None
        if timestamp > 10_000_000_000:
            timestamp = int(timestamp / 1000)
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)

    @staticmethod
    def _extract_school_id(payload: dict[str, Any]) -> str | None:
        value = payload.get("school_id") or payload.get("schoolId")
        return str(value).strip() if value else None
