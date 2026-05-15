from enum import Enum
from typing import Optional
from pydantic import BaseModel
from app.application.analytics.conversation_builder import ConversationThread

class OccurrenceStatus(str, Enum):
    JUSTIFICADO = "JUSTIFICADO"
    PARCIAL = "PARCIAL"
    CRITICO = "CRITICO"
    SEM_RESPOSTA = "SEM_RESPOSTA"

class RiskLevel(str, Enum):
    BAIXO = "BAIXO"
    MEDIO = "MEDIO"
    ALTO = "ALTO"

class SchoolOccurrenceReport(BaseModel):
    sender_jid: str
    student_id: Optional[str]
    campaign_id: Optional[str]
    guardian_id: Optional[str]
    status: OccurrenceStatus
    risk_level: RiskLevel
    needs_followup: bool
    has_medical_document: bool
    summary_text: str
    message_count: int
    duration_seconds: int

class ConversationSummarizer:
    """
    Transforma a conversa consolidada em um relatório de ocorrência escolar usando
    lógica baseada puramente em regras e análise determinística.
    """
    def __init__(self):
        # Palavras-chave extraídas a partir de regras de negócio
        self.medical_keywords = {"atestado", "médico", "medico", "receita", "hospital", "ubs", "upa", "cirurgia", "exame", "postinho"}
        self.health_keywords = {"doente", "febre", "dor", "gripe", "virose", "passando mal", "consulta"}
        self.work_logistics_keywords = {"trabalho", "serviço", "servico", "viajou", "viagem", "problema familiar", "chovendo", "chuva", "transporte", "onibus", "ônibus"}
        self.partial_keywords = {"vai amanha", "vai hoje", "chegando", "atrasou", "perdeu a hora", "vai mais tarde"}
        self.critical_keywords = {"não quer ir", "nao quer ir", "recusa", "problema na escola", "bullying", "bateram", "apanhou", "desistiu", "vai parar"}

    def summarize(self, thread: ConversationThread) -> SchoolOccurrenceReport:
        if not thread.messages:
            return SchoolOccurrenceReport(
                sender_jid=thread.sender_jid,
                student_id=thread.student_id,
                campaign_id=thread.campaign_id,
                guardian_id=thread.guardian_id,
                status=OccurrenceStatus.SEM_RESPOSTA,
                risk_level=RiskLevel.ALTO,
                needs_followup=True,
                has_medical_document=False,
                summary_text="Nenhuma mensagem válida na conversa.",
                message_count=0,
                duration_seconds=0
            )

        full_text = " | ".join([m.body for m in thread.messages]).lower()
        
        has_medical_document = any(kw in full_text for kw in self.medical_keywords)
        
        # Determinação baseada em regras
        if has_medical_document or any(kw in full_text for kw in self.health_keywords):
            status = OccurrenceStatus.JUSTIFICADO
            risk_level = RiskLevel.BAIXO
            needs_followup = False
        elif any(kw in full_text for kw in self.work_logistics_keywords):
            status = OccurrenceStatus.JUSTIFICADO
            risk_level = RiskLevel.MEDIO
            needs_followup = False
        elif any(kw in full_text for kw in self.partial_keywords):
            status = OccurrenceStatus.PARCIAL
            risk_level = RiskLevel.MEDIO
            needs_followup = True
        elif any(kw in full_text for kw in self.critical_keywords):
            status = OccurrenceStatus.CRITICO
            risk_level = RiskLevel.ALTO
            needs_followup = True
        else:
            # Caso não encaixe em nenhuma regra específica, usamos a heurística do engajamento
            if thread.message_count >= 3 or thread.duration_seconds > 120:
                # Se há troca de mensagens ou conversa longa
                status = OccurrenceStatus.PARCIAL
                risk_level = RiskLevel.MEDIO
                needs_followup = True
            else:
                # Mensagens genéricas/isoladas sem muito contexto
                status = OccurrenceStatus.CRITICO
                risk_level = RiskLevel.ALTO
                needs_followup = True

        summary_lines = []
        for m in thread.messages:
            # Formatação simples do histórico da conversa
            summary_lines.append(f"[{m.received_at.strftime('%d/%m %H:%M')}] {m.body}")
            
        summary_text = "\n".join(summary_lines)

        return SchoolOccurrenceReport(
            sender_jid=thread.sender_jid,
            student_id=thread.student_id,
            campaign_id=thread.campaign_id,
            guardian_id=thread.guardian_id,
            status=status,
            risk_level=risk_level,
            needs_followup=needs_followup,
            has_medical_document=has_medical_document,
            summary_text=summary_text,
            message_count=thread.message_count,
            duration_seconds=thread.duration_seconds
        )
