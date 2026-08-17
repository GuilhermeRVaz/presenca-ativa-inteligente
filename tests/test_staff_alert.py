import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings

client = TestClient(app)


def test_alert_staff_endpoint_success(monkeypatch):
    """Testa o disparo de alerta para a equipe escolar (Paula - Secretaria)."""
    class MockSendResult:
        success = True
        provider_message_id = "mock-alert-msg-123"
        error = None

    def mock_send_text(self, to_jid, text, **kwargs):
        assert to_jid == settings.phone_secretaria or "5514991467883" in to_jid
        assert "Secretaria (Paula)" in text
        assert "João Silva" in text
        return MockSendResult()

    from app.infrastructure.evolution.gateway import EvolutionGateway
    monkeypatch.setattr(EvolutionGateway, "send_text", mock_send_text)

    payload = {
        "target_role": "SECRETARIA",
        "student_name": "João Silva",
        "student_class": "7º Ano A",
        "guardian_name": "Maria Silva",
        "guardian_phone": "5514999998888",
        "alert_reason": "Dúvida de Secretaria / Histórico Escolar",
        "message_summary": "Gostaria de saber quando fica pronto o histórico escolar do João.",
        "unanswered_question": "Qual o prazo para emissão do histórico escolar?",
    }

    response = client.post("/inbound/alert_staff", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["sent"] is True
    assert "Paula" in data["recipient_role"]
    assert data["provider_message_id"] == "mock-alert-msg-123"


def test_alert_staff_diretor(monkeypatch):
    """Testa o disparo de alerta de alta gravidade para o Diretor (Junior)."""
    class MockSendResult:
        success = True
        provider_message_id = "mock-alert-diretor-999"
        error = None

    def mock_send_text(self, to_jid, text, **kwargs):
        assert to_jid == settings.phone_diretor or "5514997053808" in to_jid
        assert "Direção (Junior)" in text
        return MockSendResult()

    from app.infrastructure.evolution.gateway import EvolutionGateway
    monkeypatch.setattr(EvolutionGateway, "send_text", mock_send_text)

    payload = {
        "target_role": "DIRETOR",
        "student_name": "Pedro Santos",
        "student_class": "9º Ano B",
        "guardian_name": "Carlos Santos",
        "guardian_phone": "5514988887777",
        "alert_reason": "Risco Elevado / Solicitou falar com a direção",
        "message_summary": "Preciso falar urgente com o diretor da escola sobre um ocorrido grave.",
    }

    response = client.post("/inbound/alert_staff", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["sent"] is True
    assert "Junior" in data["recipient_role"]
