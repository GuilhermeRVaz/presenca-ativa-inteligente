import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.api.routes import inbound_reply
from app.api.schemas import InboundReplyRequest
from app.domain.models import GuardianRecord, MessageRecord


class FakeReplyRepository:
    def __init__(self) -> None:
        self.active_campaign_id = "campaign-1"
        self.upserts: list[dict] = []
        self.saved: list[dict] = []
        self.session_upserts: list[dict] = []
        guardian = GuardianRecord(
            id="guardian-1",
            name="Maria",
            phone_e164="5511999999999",
            wa_jid="5511999999999@s.whatsapp.net",
        )
        self.reply_message = MessageRecord(
            id="message-1",
            school_id="school-1",
            campaign_id="campaign-1",
            student_id="student-1",
            guardian_id="guardian-1",
            wa_jid="5511999999999@s.whatsapp.net",
            evolution_msg_id="out-1",
            sent_at=datetime.now(timezone.utc),
            guardian=guardian,
        )

    def get_active_campaign_for_today(self, *, school_id):
        return self.active_campaign_id

    def find_reply_message(self, *, school_id, campaign_id, sender_jid, guardian_id=None):
        return self.reply_message

    def upsert_phone_identity(self, **kwargs):
        self.upserts.append(kwargs)
        return "identity-1"

    def save_reply(self, **kwargs):
        self.saved.append(kwargs)
        return "response-1", True

    def upsert_session(self, **kwargs):
        self.session_upserts.append(kwargs)
        # Return a dummy record or mock response
        return None


class InboundReplyRouteTests(unittest.TestCase):
    def test_inbound_reply_learns_lid_identity_from_n8n_guardian(self):
        repo = FakeReplyRepository()
        payload = InboundReplyRequest(
            school_id="school-1",
            sender_jid="123@lid",
            raw_message_id="raw-1",
            body="foi ao medico",
            guardian_id="guardian-1",
            reason="ILLNESS",
            ai_confidence=0.9,
            student_id="student-1",
        )

        with patch("app.api.routes.build_repository_internal", return_value=repo):
            response = inbound_reply(payload)

        self.assertTrue(response.ok)
        self.assertEqual(response.response_id, "response-1")
        self.assertEqual(repo.upserts[0]["school_id"], "school-1")
        self.assertEqual(repo.upserts[0]["lid_jid"], "123@lid")
        self.assertEqual(repo.upserts[0]["wa_jid"], "5511999999999@s.whatsapp.net")
        self.assertEqual(repo.upserts[0]["guardian_id"], "guardian-1")
        self.assertEqual(repo.upserts[0]["confidence"], "HIGH")
        self.assertEqual(repo.saved[0]["identity_confidence"], "HIGH")
        self.assertEqual(repo.saved[0]["message_id"], "message-1")
        self.assertEqual(repo.saved[0]["student_id"], "student-1")
        self.assertEqual(len(repo.session_upserts), 1)
        self.assertEqual(repo.session_upserts[0]["student_id"], "student-1")
        self.assertEqual(repo.session_upserts[0]["resolved"], True)


if __name__ == "__main__":
    unittest.main()
