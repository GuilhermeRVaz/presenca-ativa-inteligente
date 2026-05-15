from pydantic import BaseModel, Field, model_validator
from typing import Any


class WebhookResponse(BaseModel):
    ok: bool = True
    status: str
    message_id: str | None = None
    school_id: str | None = None
    duplicate: bool = False
    identity_confidence: str | None = None
    response_id: str | None = None


class DispatchMessageRequest(BaseModel):
    school_id: str = Field(..., min_length=1)
    student_id: str = Field(..., min_length=1)
    campaign_id: str = Field(..., min_length=1)
    dry_run: bool = False


class DispatchMessageResponse(BaseModel):
    ok: bool
    status: str
    message_id: str | None = None
    evolution_msg_id: str | None = None
    tracking_ref: str
    dry_run: bool = False


class InboundReplyRequest(BaseModel):
    """Payload enviado pelo n8n quando um responsável responde a campanha."""
    # Identificação da resposta
    sender_jid: str = Field(..., description="JID WhatsApp do responsável (ex: 5514999991234@s.whatsapp.net)")
    body: str = Field(..., description="Texto completo da mensagem recebida")
    raw_message_id: str = Field(..., description="ID único da mensagem na Evolution API")

    # Contexto da campanha (preenchido pelo n8n após triagem)
    student_id: str | None = Field(None, description="UUID do aluno no banco")
    guardian_id: str | None = Field(None, description="UUID do responsável no banco")
    campaign_id: str | None = Field(None, description="UUID da campanha ativa")
    message_id: str | None = Field(None, description="UUID da mensagem outbound original")

    # Classificação (preenchida pelo LangChain/n8n)
    reason: str | None = Field(
        None,
        description=(
            "Motivo da falta. Valores aceitos pelo banco: "
            "ILLNESS, WORK, TRAVEL, FAMILY, SCHOOL_ISSUE, OTHER. "
            "Qualquer outro texto é mapeado para OTHER automaticamente."
        ),
    )
    ai_confidence: float | None = Field(None, ge=0.0, le=1.0)
    identity_confidence: str | None = Field(None, description="Confiança da identidade (HIGH, MEDIUM, LOW, UNRESOLVED)")

    # Opcional
    school_id: str | None = Field(None, description="UUID da escola (usa DEFAULT_SCHOOL_ID se omitido)")
    received_at: str | None = Field(None, description="ISO 8601 timestamp da mensagem")

    @model_validator(mode='before')
    @classmethod
    def convert_empty_strings(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: (None if v == "" else v) for k, v in data.items()}
        return data


class InboundReplyResponse(BaseModel):
    ok: bool = True
    response_id: str
    student_id: str | None = None
    campaign_id: str | None = None
    reason: str | None = None
    message_marked_replied: bool = False

# Analytics Schemas
class CampaignOperationalMetrics(BaseModel):
    total_students_targeted: int
    messages_sent_success: int
    messages_sent_failed: int
    responses_received: int
    response_rate: float

class CampaignStructuralFailures(BaseModel):
    no_guardian_linked: int
    invalid_numbers: int
    not_found_in_db: int
    total_structural_issues: int

class CampaignJustificationAnalysis(BaseModel):
    health_issues: int
    medical_documents: int
    partial_absences: int
    unresponsive: int

class CampaignRiskAnalysis(BaseModel):
    high_risk: int
    medium_risk: int
    low_risk: int

class ConsolidatedCampaignReport(BaseModel):
    campaign_id: str
    campaign_name: str
    generated_at: str
    operational: CampaignOperationalMetrics
    structural: CampaignStructuralFailures
    justifications: CampaignJustificationAnalysis
    risk: CampaignRiskAnalysis
    insights: list[str]
    class_analysis: dict[str, Any]
    priority_cases: list[dict[str, Any]]
