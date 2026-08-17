import unittest
from app.application.inbound_service import InboundService
from app.api.schemas import WebhookResponse
from scripts.consolidate_campaign_report import analyze_inbound, extract_protocol

INITIAL_TEMPLATE_MARKERS = [
    "aqui e da", "aqui é da", "para justificar, responda",
    "esteve ausente nos dias", "faltou nos dias",
    "ausencia de", "ausência de", "poderia nos informar o motivo",
    "codigo do aluno:", "código do aluno:", "exemplo:"
]

class FakeRepository:
    def __init__(self):
        self.responses = []
        self.human_takeovers = []

    def record_raw_inbound(self, **kwargs):
        return True

    def mark_raw_inbound_processed(self, **kwargs):
        pass

    def set_human_takeover(self, school_id, sender_jid):
        self.human_takeovers.append((school_id, sender_jid))

    def find_message_by_protocol(self, school_id, protocol):
        from app.domain.models import MessageRecord
        from datetime import datetime, timezone
        return MessageRecord(
            id="msg-1",
            school_id=school_id,
            campaign_id="camp-1",
            student_id="stu-1",
            guardian_id="g-1",
            wa_jid="5511999999999@s.whatsapp.net",
            evolution_msg_id="evo-1",
            sent_at=datetime.now(timezone.utc),
        )

    def save_reply(self, **kwargs):
        self.responses.append(kwargs)
        return "resp-1"


class TestCampaignResponseDetection(unittest.TestCase):
    def setUp(self):
        self.repo = FakeRepository()
        self.service = InboundService(repository=self.repo)

    def test_outbound_initial_template_is_ignored(self):
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {
                    "remoteJid": "5511999999999@s.whatsapp.net",
                    "fromMe": True,
                    "id": "MSG12345"
                },
                "message": {
                    "conversation": "Ola mãe, aqui e da EE Decia. O(a) aluno(a) BRYAN ENZO esteve ausente... Protocolo P-67E89E"
                }
            }
        }
        res = self.service.record_for_processing(payload)
        self.assertEqual(res.status, "ignored_from_me")
        # Deve garantir que NENHUMA resposta foi salva no banco
        self.assertEqual(len(self.repo.responses), 0)

    def test_outbound_operator_audio_confirmation_is_saved(self):
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {
                    "remoteJid": "5511999999999@s.whatsapp.net",
                    "fromMe": True,
                    "id": "CONF12345"
                },
                "message": {
                    "conversation": "Obrigado mãe, justificativa anotada de febre! Protocolo P-67E89E"
                }
            }
        }
        res = self.service.record_for_processing(payload)
        self.assertEqual(res.status, "ignored_from_me")
        # Deve ter registrado como confirmação manual de operador
        self.assertEqual(len(self.repo.responses), 1)
        self.assertEqual(self.repo.responses[0]["handoff_reason"], "human_outbound_justification")

    def test_template_initial_markers_detection(self):
        text = "Ola mãe, aqui e da EE Decia. O(a) aluno(a) BRYAN ENZO... Protocolo P-67E89E"
        body_lower = text.lower()
        has_initial_marker = any(m in body_lower for m in INITIAL_TEMPLATE_MARKERS)
        self.assertTrue(has_initial_marker)

if __name__ == "__main__":
    unittest.main()
