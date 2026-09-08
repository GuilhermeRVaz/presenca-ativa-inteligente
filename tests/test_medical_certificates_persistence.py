import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_list_medical_certificates_endpoint():
    """Testa a listagem de atestados médicos da escola."""
    mock_certs = [
        {
            "id": "cert-uuid-1",
            "school_id": "school-1",
            "student_name": "Davi Roberto da Silva",
            "student_class": "8º Ano B",
            "certificate_type": "ATESTADO_MEDICO",
            "days_off": "2 dias",
            "doctor_crm": "Dr. Carlos (CRM 123456)",
            "summary": "Gripe forte e febre",
            "status": "PENDENTE",
            "created_at": "2026-09-01T10:00:00Z"
        }
    ]

    with patch("app.api.routes.build_repository_internal") as mock_build_repo:
        mock_repo = MagicMock()
        mock_repo.list_medical_certificates.return_value = mock_certs
        mock_build_repo.return_value = mock_repo

        response = client.get("/api/v1/medical_certificates?status=PENDENTE")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["count"] == 1
        assert data["data"][0]["student_name"] == "Davi Roberto da Silva"
        mock_repo.list_medical_certificates.assert_called_once_with(
            school_id="aac99735-32cb-4615-b2cb-0be315f18374",
            status="PENDENTE",
            student_id=None,
            limit=50
        )


def test_update_medical_certificate_status_endpoint():
    """Testa a homologação de um atestado pela secretaria escolar."""
    mock_updated = {
        "id": "cert-uuid-1",
        "status": "HOMOLOGADO",
        "homologated_by": "Paula - Secretaria",
        "homologated_at": "2026-09-01T10:30:00Z"
    }

    with patch("app.api.routes.build_repository_internal") as mock_build_repo:
        mock_repo = MagicMock()
        mock_repo.update_medical_certificate_status.return_value = mock_updated
        mock_build_repo.return_value = mock_repo

        response = client.patch(
            "/api/v1/medical_certificates/cert-uuid-1/status",
            json={"status": "HOMOLOGADO", "homologated_by": "Paula - Secretaria"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["certificate"]["status"] == "HOMOLOGADO"
        assert data["certificate"]["homologated_by"] == "Paula - Secretaria"
