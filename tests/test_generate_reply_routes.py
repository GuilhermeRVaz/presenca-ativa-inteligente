from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_generate_reply_endpoint():
    payload = {
        "school_id": "aac99735-32cb-4615-b2cb-0be315f18374",
        "sender_jid": "5514998389191@s.whatsapp.net",
        "push_name": "Ana",
        "message_text": "P-BEAC50 estava com febre e dor de cabeça",
        "student_name": "EMANUELA MARIANO DA SILVA",
        "category": "DOENCA",
        "last_reason": None,
        "messages_history": []
    }
    response = client.post("/inbound/generate_reply", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "response_text" in data
    assert "EMANUELA MARIANO DA SILVA" in data["response_text"]
    assert "saúde" in data["response_text"].lower() or "recuperação" in data["response_text"].lower()


def test_generate_sac_reply_endpoint():
    payload = {
        "message_text": "qual o horario das aulas?",
        "rag_context": [{"content": "O horário das aulas é das 07:00 às 16:00."}]
    }
    response = client.post("/inbound/generate_sac_reply", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "response_text" in data
    assert "07:00" in data["response_text"]
