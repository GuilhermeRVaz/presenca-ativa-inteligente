import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings

client = TestClient(app)


def test_forward_certificate_text_only(monkeypatch):
    """Testa o encaminhamento de atestado médico apenas com resumo de texto para a Secretaria (Paula)."""
    class MockSendResult:
        success = True
        provider_message_id = "mock-cert-msg-123"
        error = None

    def mock_send_text(self, to_jid, text, **kwargs):
        assert to_jid == settings.phone_secretaria or "5514991467883" in to_jid
        assert "NOVO ATESTADO / DECLARAÇÃO MÉDICA" in text
        assert "DAVI ROBERTO DA SILVA" in text
        assert "8º Ano B" in text
        assert "Gripe forte e febre" in text
        return MockSendResult()

    from app.infrastructure.evolution.gateway import EvolutionGateway
    monkeypatch.setattr(EvolutionGateway, "send_text", mock_send_text)

    payload = {
        "student_name": "DAVI ROBERTO DA SILVA",
        "student_class": "8º Ano B",
        "guardian_name": "Nay Campos",
        "guardian_phone": "5514997701125",
        "certificate_type": "ATESTADO_MEDICO",
        "days_off": "2 dias",
        "date_start": "31/08/2026",
        "doctor_crm": "Dr. Carlos (CRM/SP 123456)",
        "certificate_summary": "Gripe forte e febre, orientado repouso domiciliar.",
    }

    response = client.post("/inbound/forward_certificate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["sent"] is True
    assert data["delivery_mode"] == "text_summary"
    assert "Paula" in data["recipient_role"]
    assert data["provider_message_id"] == "mock-cert-msg-123"


def test_forward_certificate_with_media(monkeypatch):
    """Testa o encaminhamento de atestado com anexo de imagem para a Secretaria."""
    class MockSendResult:
        success = True
        provider_message_id = "mock-cert-media-456"
        error = None

    def mock_send_media(self, to_jid, media, mediatype, mimetype, caption, file_name, **kwargs):
        assert to_jid == settings.phone_secretaria or "5514991467883" in to_jid
        assert media == "https://example.com/atestado_foto.jpg"
        assert mediatype == "image"
        assert "LIVIA VIEIRA OLIVEIRA" in caption
        assert "6º Ano B" in caption
        assert "Cefaleia e dor nos olhos" in caption
        return MockSendResult()

    from app.infrastructure.evolution.gateway import EvolutionGateway
    monkeypatch.setattr(EvolutionGateway, "send_media", mock_send_media)

    payload = {
        "student_name": "LIVIA VIEIRA OLIVEIRA",
        "student_class": "6º Ano B",
        "guardian_name": "Mariane",
        "guardian_phone": "5514988143330",
        "certificate_type": "DECLARACAO_COMPARECIMENTO",
        "days_off": "1 dia",
        "certificate_summary": "Cefaleia e dor nos olhos durante consulta oftalmológica.",
        "media_url": "https://example.com/atestado_foto.jpg",
        "media_mimetype": "image/jpeg",
    }

    response = client.post("/inbound/forward_certificate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["sent"] is True
    assert data["delivery_mode"] == "media_caption"
    assert data["provider_message_id"] == "mock-cert-media-456"


def test_forward_certificate_get_endpoint(monkeypatch):
    """Testa o endpoint GET de conveniência para forward_certificate."""
    class MockSendResult:
        success = True
        provider_message_id = "mock-cert-get-789"
        error = None

    def mock_send_text(self, to_jid, text, **kwargs):
        assert "THIAGO ULISSES" in text
        return MockSendResult()

    from app.infrastructure.evolution.gateway import EvolutionGateway
    monkeypatch.setattr(EvolutionGateway, "send_text", mock_send_text)

    response = client.get(
        "/inbound/forward_certificate",
        params={
            "student_name": "THIAGO ULISSES",
            "certificate_summary": "Quadro de virose em repouso",
            "days_off": "3 dias",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["sent"] is True
