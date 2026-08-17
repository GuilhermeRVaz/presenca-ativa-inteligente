"""
tests/test_extraordinary_campaigns.py

Testes unitários para o serviço de variações de IA e gerenciamento de campanhas extraordinárias.
"""

from __future__ import annotations

import pytest
import json
from unittest.mock import MagicMock, patch
from app.services.campaign_ai_service import CampaignAIService
from app.services.extraordinary_campaign_service import ExtraordinaryCampaignService


def test_campaign_ai_service_extract_placeholders():
    svc = CampaignAIService(api_key="test-key")
    text = "Olá {{nome_responsavel}}, o aluno {{nome_aluno}} da turma {{turma}} na {{escola}} tem aviso."
    ph = svc.extract_placeholders(text)
    assert set(ph) == {"{{nome_responsavel}}", "{{nome_aluno}}", "{{turma}}", "{{escola}}"}


def test_campaign_ai_service_generate_variants_mock():
    svc = CampaignAIService(api_key="test-key")
    base_msg = "Aviso para {{nome_responsavel}} sobre {{nome_aluno}}."
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_variants = [f"Variação {i+1}: Aviso para {{nome_responsavel}} sobre {{nome_aluno}}." for i in range(20)]
    raw_json = json.dumps({"variants": mock_variants})
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": raw_json
                }
            }
        ]
    }

    with patch("requests.post", return_value=mock_response):
        variants = svc.generate_variants(base_msg, num_variants=20)
        assert len(variants) == 20
        assert all("{{nome_responsavel}}" in v for v in variants)
        assert all("{{nome_aluno}}" in v for v in variants)

        # Test count alias parameter
        variants_count = svc.generate_variants(base_msg, count=20)
        assert len(variants_count) == 20


def test_extraordinary_campaign_service_available_classes():
    mock_repo = MagicMock()
    mock_client = MagicMock()
    mock_repo.client.schema.return_value = mock_client
    
    mock_table = MagicMock()
    mock_client.table.return_value = mock_table
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.execute.return_value.data = [
        {"class_name": "6A"},
        {"class_name": "6B"},
        {"class_name": "7A"},
    ]

    svc = ExtraordinaryCampaignService(repository=mock_repo)
    classes = svc.list_available_classes("school-123")
    assert classes == ["6A", "6B", "7A"]
