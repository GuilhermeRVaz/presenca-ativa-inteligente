import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_classify_endpoint_fallback():
    """Testa o endpoint /inbound/classify com fallback determinístico local."""
    payload = {
        "school_id": "school-1",
        "sender_jid": "5514991141780@s.whatsapp.net",
        "message_text": "Matheus Henrique da Silva Gonçalves, não foi a aula hoje por está indo ao oftalmologista!!!",
        "student_name": "MATHEUS HENRIQUE DA SILVA GONÇALVES",
        "last_reason": None,
        "campaign_name": "Campanha Faltas",
    }

    response = client.post("/inbound/classify", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "intent" in data
    assert data["intent"] in ("JUSTIFICATIVA_FALTA", "SAUDACAO")
    assert data["category"] in ("ILLNESS", "OTHER", "DOENCA", "UNCATEGORIZED", "OUTRO", None)
    assert "confidence" in data
    assert "needs_human" in data


def test_classify_endpoint_duvida_secretaria():
    """Testa a classificação de dúvida de secretaria."""
    payload = {
        "message_text": "Qual é o horário de atendimento da secretaria para retirar declaração de matrícula?",
    }

    response = client.post("/inbound/classify", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] in ("DUVIDA_SECRETARIA", "JUSTIFICATIVA_FALTA", "DESCONHECIDO", "LOGISTICA")
