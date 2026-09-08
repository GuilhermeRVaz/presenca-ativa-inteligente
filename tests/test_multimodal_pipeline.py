import pytest
from unittest.mock import MagicMock, patch
from app.application.inbound_service import InboundService


def test_transcribe_audio_success():
    """Testa transcrição de áudio via Whisper com sucesso."""
    service = InboundService(repository=MagicMock())
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"text": "Olá, meu filho Davi está com febre e foi ao médico hoje."}

    with patch.object(service, "_build_httpx_client") as mock_client_builder:
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client_builder.return_value = mock_client

        transcription = service.transcribe_audio(b"fake-ogg-bytes")
        assert transcription == "Olá, meu filho Davi está com febre e foi ao médico hoje."


def test_transcribe_audio_fallback_on_error():
    """Testa fallback resiliente quando a API de áudio falha."""
    service = InboundService(repository=MagicMock())

    with patch.object(service, "_build_httpx_client") as mock_client_builder:
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("OpenAI API Timeout")
        mock_client_builder.return_value = mock_client

        transcription = service.transcribe_audio(b"fake-ogg-bytes")
        assert "Mensagem de áudio recebida" in transcription


def test_analyze_document_photo_success():
    """Testa análise de imagem de atestado via GPT-4o-mini Vision."""
    service = InboundService(repository=MagicMock())

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": '{"is_atestado": true, "tipo_documento": "ATESTADO_MEDICO", "nome_aluno": "Davi Roberto", "dias_afastamento": "2 dias", "medico_crm": "Dr. Carlos CRM 12345", "resumo_motivo": "Quadro de gripe e cefaleia, repouso prescrito"}'
                }
            }
        ]
    }

    with patch.object(service, "_build_httpx_client") as mock_client_builder:
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client_builder.return_value = mock_client

        result = service.analyze_document_photo("https://example.com/atestado.jpg")
        assert result["is_atestado"] is True
        assert result["certificate_type"] == "ATESTADO_MEDICO"
        assert result["student_name"] == "Davi Roberto"
        assert result["days_off"] == "2 dias"
        assert "Dr. Carlos" in result["doctor_crm"]


def test_multimodal_tokens_enrichment():
    """Testa se os tokens [AUDIO_PTT] e [FOTO_DOCUMENTO] são enriquecidos antes do disparo para o n8n."""
    service = InboundService(repository=MagicMock())
    service.transcribe_audio = MagicMock(return_value="Davi está gripado")
    service.analyze_document_photo = MagicMock(return_value={"summary": "Atestado de 2 dias do Dr. Carlos"})

    with patch("app.core.config.settings.n8n_chat_webhook_url", "http://fake-n8n/webhook"):
        with patch("httpx.Client.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: {"status": "ok"})

            # Teste de áudio
            service._trigger_n8n_chat_interaction(
                school_id="school-1",
                sender_jid="5514997701125@s.whatsapp.net",
                response_id=None,
                student_id=None,
                text="[AUDIO_PTT]",
                received_at=None,
            )
            args, kwargs = mock_post.call_args
            payload = kwargs["json"]
            assert '[Áudio Transcrito do Responsável]: "Davi está gripado"' in payload["message_text"]
