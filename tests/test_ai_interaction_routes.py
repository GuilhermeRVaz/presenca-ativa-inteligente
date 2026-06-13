import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app

class AIInteractionRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    @patch("app.api.routes.build_repository")
    def test_save_ai_interaction_endpoint_success(self, mock_build_repo) -> None:
        mock_repo = MagicMock()
        mock_repo.save_ai_interaction.return_value = "interaction-uuid-123"
        mock_build_repo.return_value = mock_repo

        payload = {
            "response_id": "response-uuid",
            "student_id": "student-uuid",
            "prompt_version": "1.0-empatia-fase1",
            "model": "gpt-4o-mini",
            "input_text": "Responsável: ele está doente",
            "output_text": "Desejamos melhoras ao João.",
            "classified_reason": "ILLNESS",
            "risk_level": "LOW",
            "tokens_input": 150,
            "tokens_output": 50,
            "cost": 0.00005
        }

        response = self.client.post("/inbound/ai_interaction", json=payload)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["interaction_id"], "interaction-uuid-123")
        mock_repo.save_ai_interaction.assert_called_once_with(
            response_id="response-uuid",
            student_id="student-uuid",
            prompt_version="1.0-empatia-fase1",
            model="gpt-4o-mini",
            input_text="Responsável: ele está doente",
            output_text="Desejamos melhoras ao João.",
            classified_reason="ILLNESS",
            risk_level="LOW",
            tokens_input=150,
            tokens_output=50,
            cost=0.00005
        )

    @patch("app.api.routes.build_repository_internal")
    def test_get_session_context_endpoint_success(self, mock_build_repo) -> None:
        mock_repo = MagicMock()
        mock_repo.get_conversation_context.return_value = {
            "student_name": "João da Silva",
            "last_reason": "ILLNESS",
            "status": "active",
            "messages": [
                {"text": "ele está doente", "sender": "guardian", "timestamp": "2026-05-22T12:00:00Z"}
            ]
        }
        mock_build_repo.return_value = mock_repo

        response = self.client.get(
            "/students/session_context",
            params={"sender_jid": "12345@s.whatsapp.net", "school_id": "school-1"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["student_name"], "João da Silva")
        self.assertEqual(data["last_reason"], "ILLNESS")
        self.assertEqual(data["status"], "active")
        self.assertEqual(len(data["messages"]), 1)
        mock_repo.get_conversation_context.assert_called_once_with(
            school_id="school-1",
            sender_jid="12345@s.whatsapp.net",
            limit=5,
            student_id=None
        )

    @patch("app.api.routes.build_repository_internal")
    def test_get_session_context_endpoint_success_with_student_id(self, mock_build_repo) -> None:
        mock_repo = MagicMock()
        mock_repo.get_conversation_context.return_value = {
            "student_name": "João da Silva",
            "last_reason": "ILLNESS",
            "status": "resolved",
            "messages": [
                {"text": "ele está doente", "sender": "guardian", "timestamp": "2026-05-22T12:00:00Z"}
            ]
        }
        mock_build_repo.return_value = mock_repo

        response = self.client.get(
            "/students/session_context",
            params={
                "sender_jid": "12345@s.whatsapp.net",
                "school_id": "school-1",
                "student_id": "student-123"
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["student_name"], "João da Silva")
        self.assertEqual(data["last_reason"], "ILLNESS")
        self.assertEqual(data["status"], "resolved")
        mock_repo.get_conversation_context.assert_called_once_with(
            school_id="school-1",
            sender_jid="12345@s.whatsapp.net",
            limit=5,
            student_id="student-123"
        )

if __name__ == "__main__":
    unittest.main()
