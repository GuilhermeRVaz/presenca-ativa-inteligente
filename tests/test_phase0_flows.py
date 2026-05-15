import unittest
from datetime import datetime, timedelta, timezone

from app.application.identity_resolver import IdentityResolver
from app.application.inbound_service import InboundService
from app.core.config import settings
from app.domain.models import GuardianRecord, IdentityMapRecord, MessageRecord
from app.infrastructure.evolution.payload_parser import EvolutionPayloadParser


class FakeInboundRepository:
    def __init__(self) -> None:
        self.raw_seen: set[str] = set()
        self.responses: list[dict] = []
        self.identities: dict[str, IdentityMapRecord] = {}
        self.messages_by_evolution_id: dict[str, MessageRecord] = {}
        self.messages_by_protocol: dict[str, MessageRecord] = {}
        self.last_messages_by_guardian_id: dict[str, MessageRecord] = {}
        self.reply_message: MessageRecord | None = None
        self.active_campaign_id: str | None = None
        self.recent_messages: list[MessageRecord] = []
        self.upserts: list[dict] = []
        self.processed_marks: list[dict] = []
        self.fail_save_response = False

    def record_raw_inbound(self, *, school_id, message_id, sender_jid, payload):
        if message_id in self.raw_seen:
            return False
        self.raw_seen.add(message_id)
        return True

    def mark_raw_inbound_processed(self, *, message_id, processed, error):
        self.processed_marks.append(
            {"message_id": message_id, "processed": processed, "error": error}
        )
        return None

    def save_response(self, **kwargs):
        if self.fail_save_response:
            raise RuntimeError("boom")
        self.responses.append(kwargs)
        return "response-1"

    def find_identity_by_jid(self, *, school_id, sender_jid):
        return self.identities.get(sender_jid)

    def find_message_by_evolution_id(self, *, school_id, evolution_msg_id):
        return self.messages_by_evolution_id.get(evolution_msg_id)

    def find_message_by_protocol(self, *, school_id, protocol):
        return self.messages_by_protocol.get(protocol)

    def get_last_outbound_message_for_guardian(self, *, school_id, guardian_id, guardian=None):
        return self.last_messages_by_guardian_id.get(guardian_id)

    def find_recent_messages_for_identity(self, *, school_id, sender_jid, hours):
        return self.recent_messages

    def get_active_campaign_for_today(self, *, school_id):
        return self.active_campaign_id

    def find_reply_message(self, *, school_id, campaign_id, sender_jid, guardian_id=None):
        return self.reply_message

    def upsert_phone_identity(self, **kwargs):
        self.upserts.append(kwargs)
        return "identity-1"

    def get_guardian_by_id(self, guardian_id):
        for message in [*self.messages_by_evolution_id.values(), *self.messages_by_protocol.values()]:
            if message.guardian and message.guardian.id == guardian_id:
                return message.guardian
        for identity in self.identities.values():
            if identity.guardian and identity.guardian.id == guardian_id:
                return identity.guardian
        return None


class Phase0FlowTests(unittest.TestCase):
    def setUp(self):
        self._old_n8n_webhook_url = settings.n8n_webhook_url
        settings.n8n_webhook_url = ""

    def tearDown(self):
        settings.n8n_webhook_url = self._old_n8n_webhook_url

    def test_parser_extracts_inbound_fields(self):
        payload = {
            "school_id": "school-1",
            "data": {
                "key": {"id": "msg-1", "remoteJid": "123@lid", "fromMe": False},
                "messageTimestamp": 1713950000,
                "message": {
                    "extendedTextMessage": {
                        "text": "foi ao medico",
                        "contextInfo": {"stanzaId": "out-1"},
                    }
                },
            },
        }

        inbound = EvolutionPayloadParser().parse(payload)

        self.assertEqual(inbound.message_id, "msg-1")
        self.assertEqual(inbound.sender_jid, "123@lid")
        self.assertEqual(inbound.text, "foi ao medico")
        self.assertEqual(inbound.stanza_id, "out-1")
        self.assertEqual(inbound.school_id, "school-1")

    def test_inbound_duplicate_is_ignored_before_response(self):
        repo = FakeInboundRepository()
        service = InboundService(repository=repo)
        payload = {
            "school_id": "school-1",
            "data": {
                "key": {"id": "msg-1", "remoteJid": "123@lid", "fromMe": False},
                "message": {"conversation": "ok"},
            },
        }

        first = service.process(payload)
        second = service.process(payload)

        self.assertEqual(first.status, "processed")
        self.assertEqual(second.status, "duplicate_ignored")
        self.assertEqual(len(repo.responses), 1)

    def test_inbound_failure_is_saved_for_retry(self):
        repo = FakeInboundRepository()
        repo.fail_save_response = True
        service = InboundService(repository=repo)
        payload = {
            "school_id": "school-1",
            "data": {
                "key": {"id": "msg-1", "remoteJid": "123@lid", "fromMe": False},
                "message": {"conversation": "ok"},
            },
        }

        result = service.process(payload)

        self.assertEqual(result.status, "error_saved_for_retry")
        self.assertEqual(repo.processed_marks[-1]["processed"], False)
        self.assertIn("boom", repo.processed_marks[-1]["error"])

    def test_non_message_payload_is_ignored(self):
        repo = FakeInboundRepository()
        service = InboundService(repository=repo)
        payload = {
            "school_id": "school-1",
            "data": {
                "key": {"id": "msg-1", "remoteJid": "123@lid", "fromMe": False},
                "status": "DELIVERY_ACK",
            },
        }

        result = service.process(payload)

        self.assertEqual(result.status, "ignored_non_message_event")
        self.assertEqual(len(repo.raw_seen), 0)

    def test_identity_resolver_uses_stanza_id_and_learns_lid(self):
        repo = FakeInboundRepository()
        guardian = GuardianRecord(
            id="guardian-1",
            name="Maria",
            phone_e164="5511999999999",
            wa_jid="5511999999999@s.whatsapp.net",
        )
        repo.messages_by_evolution_id["out-1"] = MessageRecord(
            id="message-1",
            school_id="school-1",
            campaign_id="campaign-1",
            student_id="student-1",
            guardian_id="guardian-1",
            wa_jid="5511999999999@s.whatsapp.net",
            evolution_msg_id="out-1",
            sent_at=None,
            guardian=guardian,
        )

        result = IdentityResolver(repo).resolve_identity(
            sender_jid="123@lid",
            stanza_id="out-1",
            school_id="school-1",
        )

        self.assertEqual(result.confidence, "HIGH")
        self.assertEqual(result.guardian.id, "guardian-1")
        self.assertEqual(repo.upserts[0]["lid_jid"], "123@lid")
        self.assertEqual(repo.upserts[0]["confidence"], "HIGH")

    def test_identity_resolver_uses_direct_guardian_last_message(self):
        repo = FakeInboundRepository()
        guardian = GuardianRecord(
            id="guardian-1",
            name="Maria",
            phone_e164="5511999999999",
            wa_jid="5511999999999@s.whatsapp.net",
        )
        repo.identities["5511999999999@s.whatsapp.net"] = IdentityMapRecord(
            guardian=guardian,
            confidence="HIGH",
        )
        repo.last_messages_by_guardian_id["guardian-1"] = MessageRecord(
            id="message-1",
            school_id="school-1",
            campaign_id="campaign-1",
            student_id="student-1",
            guardian_id="guardian-1",
            wa_jid="5511999999999@s.whatsapp.net",
            evolution_msg_id="out-1",
            sent_at=datetime.now(timezone.utc) - timedelta(hours=2),
            guardian=guardian,
        )

        result = IdentityResolver(repo).resolve_identity(
            sender_jid="5511999999999@s.whatsapp.net",
            stanza_id=None,
            school_id="school-1",
        )

        self.assertEqual(result.confidence, "HIGH")
        self.assertEqual(result.source, "temporal_last_message")
        self.assertEqual(result.message.id, "message-1")
        self.assertEqual(result.message.campaign_id, "campaign-1")

    def test_identity_resolver_uses_protocol_match_and_learns_lid(self):
        repo = FakeInboundRepository()
        guardian = GuardianRecord(
            id="guardian-1",
            name="Maria",
            phone_e164="5511999999999",
            wa_jid="5511999999999@s.whatsapp.net",
        )
        repo.messages_by_protocol["ABC123"] = MessageRecord(
            id="message-1",
            school_id="school-1",
            campaign_id="campaign-1",
            student_id="student-1",
            guardian_id="guardian-1",
            wa_jid="5511999999999@s.whatsapp.net",
            evolution_msg_id=None,
            sent_at=datetime.now(timezone.utc),
            guardian=guardian,
        )

        result = IdentityResolver(repo).resolve_identity(
            sender_jid="123@lid",
            stanza_id=None,
            school_id="school-1",
            message_text="P-ABC123 estava com febre",
        )

        self.assertEqual(result.confidence, "HIGH")
        self.assertEqual(result.source, "protocol_match")
        self.assertEqual(result.message.id, "message-1")
        self.assertEqual(repo.upserts[0]["lid_jid"], "123@lid")
        self.assertEqual(repo.upserts[0]["guardian_id"], "guardian-1")

    def test_identity_resolver_does_not_use_old_temporal_candidate(self):
        repo = FakeInboundRepository()
        guardian = GuardianRecord(
            id="guardian-1",
            name="Maria",
            phone_e164="5511999999999",
            wa_jid="5511999999999@s.whatsapp.net",
        )
        repo.recent_messages = [
            MessageRecord(
                id="message-1",
                school_id="school-1",
                campaign_id="campaign-1",
                student_id="student-1",
                guardian_id="guardian-1",
                wa_jid="5511999999999@s.whatsapp.net",
                evolution_msg_id="out-1",
                sent_at=datetime.now(timezone.utc) - timedelta(hours=25),
                guardian=guardian,
            )
        ]

        result = IdentityResolver(repo).resolve_identity(
            sender_jid="123@lid",
            stanza_id=None,
            school_id="school-1",
        )

        self.assertEqual(result.confidence, "UNRESOLVED")
        self.assertEqual(repo.upserts, [])

    def test_identity_resolver_uses_recent_temporal_candidate(self):
        repo = FakeInboundRepository()
        guardian = GuardianRecord(
            id="guardian-1",
            name="Maria",
            phone_e164="5511999999999",
            wa_jid="5511999999999@s.whatsapp.net",
        )
        repo.recent_messages = [
            MessageRecord(
                id="message-1",
                school_id="school-1",
                campaign_id="campaign-1",
                student_id="student-1",
                guardian_id="guardian-1",
                wa_jid="5511999999999@s.whatsapp.net",
                evolution_msg_id="out-1",
                sent_at=datetime.now(timezone.utc) - timedelta(hours=2),
                guardian=guardian,
            )
        ]

        result = IdentityResolver(repo).resolve_identity(
            sender_jid="123@lid",
            stanza_id=None,
            school_id="school-1",
        )

        self.assertEqual(result.confidence, "MEDIUM")
        self.assertEqual(repo.upserts[0]["confidence"], "MEDIUM")

    def test_inbound_uses_active_campaign_and_reply_message_after_identity_resolution(self):
        repo = FakeInboundRepository()
        guardian = GuardianRecord(
            id="guardian-1",
            name="Maria",
            phone_e164="5511999999999",
            wa_jid="5511999999999@s.whatsapp.net",
        )
        repo.identities["123@lid"] = IdentityMapRecord(
            guardian=guardian,
            confidence="HIGH",
        )
        repo.active_campaign_id = "campaign-1"
        repo.reply_message = MessageRecord(
            id="message-1",
            school_id="school-1",
            campaign_id="campaign-1",
            student_id="student-1",
            guardian_id="guardian-1",
            wa_jid="5511999999999@s.whatsapp.net",
            evolution_msg_id="out-1",
            sent_at=datetime.now(timezone.utc) - timedelta(hours=2),
            guardian=guardian,
        )
        service = InboundService(repository=repo)
        payload = {
            "school_id": "school-1",
            "data": {
                "key": {"id": "msg-1", "remoteJid": "123@lid", "fromMe": False},
                "message": {"conversation": "foi ao medico"},
            },
        }

        result = service.process(payload)

        self.assertEqual(result.status, "processed")
        self.assertEqual(repo.responses[0]["message_id"], "message-1")
        self.assertEqual(repo.responses[0]["campaign_id"], "campaign-1")
        self.assertEqual(repo.responses[0]["student_id"], "student-1")


if __name__ == "__main__":
    unittest.main()
