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
    needs_review: bool | None = Field(None, description="Flag sinalizando necessidade de revisão humana")
    handoff_reason: str | None = Field(None, description="Motivo do desvio para humano")
    detected_intent: str | None = Field(None, description="Intenção detectada pela IA")
    risk_level: str | None = Field(None, description="Nível de risco detectado (LOW, MEDIUM, HIGH)")

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


class AIInteractionRequest(BaseModel):
    """Payload enviado pelo n8n para logar métricas e textos de processamento de IA."""
    response_id: str | None = Field(None, description="UUID da resposta correlacionada")
    student_id: str | None = Field(None, description="UUID do aluno")
    prompt_version: str = Field(..., description="Versão do prompt utilizado")
    model: str = Field(..., description="Modelo da LLM, ex: gpt-4o-mini")
    input_text: str = Field(..., description="Texto ou prompt de entrada")
    output_text: str = Field(..., description="Resposta gerada pela IA")
    classified_reason: str | None = Field(None, description="Classificação final obtida")
    risk_level: str | None = Field(None, description="Nível de risco extraído (LOW, MEDIUM, HIGH)")
    tokens_input: int | None = Field(None, description="Quantidade de tokens de entrada")
    tokens_output: int | None = Field(None, description="Quantidade de tokens de saída")
    cost: float | None = Field(None, description="Custo estimado em USD da chamada")


class AIInteractionResponse(BaseModel):
    ok: bool = True
    interaction_id: str


class StaffAlertRequest(BaseModel):
    """Payload para disparar alerta WhatsApp para a equipe escolar (Junior, Paula, Anderson, Lucimara)."""
    target_role: str = Field(..., description="Papel do destinatário: DIRETOR, SECRETARIA, VICE_DIRETOR, COORDENACAO")
    student_name: str | None = Field(None, description="Nome do aluno")
    student_class: str | None = Field(None, description="Turma do aluno")
    guardian_name: str | None = Field(None, description="Nome do responsável")
    guardian_phone: str | None = Field(None, description="Telefone do responsável")
    alert_reason: str = Field(..., description="Motivo do alerta / Intenção (ex: Dúvida de Secretaria, Risco Elevado, Pedagógico)")
    message_summary: str = Field(..., description="Resumo da mensagem ou texto do responsável")
    unanswered_question: str | None = Field(None, description="Dúvida específica não respondida pela IA")
    school_id: str | None = Field(None, description="UUID da escola")


class StaffAlertResponse(BaseModel):
    ok: bool = True
    sent: bool
    recipient_role: str
    recipient_phone: str
    provider_message_id: str | None = None
    error: str | None = None


class ClassificationRequest(BaseModel):
    school_id: str | None = Field(None, description="UUID da escola")
    sender_jid: str | None = Field(None, description="JID do responsável")
    message_text: str = Field(..., description="Texto da mensagem recebida")
    student_name: str | None = Field(None, description="Nome do aluno se disponível")
    last_reason: str | None = Field(None, description="Último motivo registrado")
    campaign_name: str | None = Field(None, description="Nome da campanha ativa")
    messages_history: list[dict[str, Any]] | None = Field(None, description="Histórico recente de mensagens")


class ClassificationResponse(BaseModel):
    intent: str
    category: str | None = None
    risk_level: str = "LOW"
    needs_human: bool = False
    confidence: float = 1.0
    needs_review: bool = False
    handoff_reason: str | None = None


class GenerateReplyRequest(BaseModel):
    school_id: str | None = Field(None, description="UUID da escola")
    sender_jid: str | None = Field(None, description="JID do responsável")
    push_name: str | None = Field(None, description="Nome do remetente WhatsApp")
    message_text: str = Field(..., description="Texto da mensagem")
    student_name: str | None = Field(None, description="Nome do aluno")
    category: str | None = Field(None, description="Categoria do motivo")
    last_reason: str | None = Field(None, description="Último motivo registrado")
    messages_history: list[dict[str, Any]] | None = Field(None, description="Histórico de mensagens")
    rag_context: list[dict[str, Any]] | None = Field(None, description="Contexto RAG para SAC")


class GenerateReplyResponse(BaseModel):
    response_text: str
    model: str = "gpt-4o-mini"
    prompt_version: str = "v2"
    detected_intent: str = "JUSTIFICATIVA_FALTA"
    risk_level: str = "LOW"




