from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import json

from app.core.logging import logger
from app.infrastructure.supabase.repositories import SupabaseRepository
from app.api.schemas import (
    CampaignOperationalMetrics,
    CampaignStructuralFailures,
    CampaignJustificationAnalysis,
    CampaignRiskAnalysis,
    ConsolidatedCampaignReport
)
from app.application.analytics.conversation_builder import ConversationBuilder
from app.application.analytics.conversation_summarizer import ConversationSummarizer, SchoolOccurrenceReport, OccurrenceStatus, RiskLevel
from app.application.analytics.conversation_reconciler import ConversationReconciler

class CampaignAnalytics:
    """
    Motor analítico que consolida todos os dados de uma campanha escolar.
    Utiliza reconciliação, construção de conversas e sumarização determinística.
    """
    def __init__(self, repository: SupabaseRepository):
        self.repository = repository
        self.client = repository.client
        self.builder = ConversationBuilder(repository)
        self.summarizer = ConversationSummarizer()
        self.reconciler = ConversationReconciler(repository)

    def generate_report(self, school_id: str, campaign_id: str) -> ConsolidatedCampaignReport:
        logger.info("analytics_report_generation_started", campaign_id=campaign_id)

        # 1. Executar Reconciliação Retrospectiva primeiro para garantir dados limpos
        self.reconciler.reconcile_unresolved_responses(window_hours=48)

        # 2. Buscar Dados de Outbound (Estruturais e Operacionais)
        outbound_res = self.client.schema("busca_ativa_v2").table("messages") \
            .select("status, student_id, last_error") \
            .eq("campaign_id", campaign_id) \
            .execute()
        
        messages = outbound_res.data
        total_targeted = len(messages)
        sent_success = len([m for m in messages if m["status"] in ["sent", "delivered", "read", "replied"]])
        sent_failed = len([m for m in messages if m["status"] == "failed"])
        
        # Simulação de falhas estruturais (baseado em erros comuns)
        structural = CampaignStructuralFailures(
            no_guardian_linked=len([m for m in messages if "no guardian" in (m.get("last_error") or "").lower()]),
            invalid_numbers=len([m for m in messages if "invalid" in (m.get("last_error") or "").lower()]),
            not_found_in_db=0, # Geralmente quem não está no DB nem chega aqui
            total_structural_issues=sent_failed
        )

        # 3. Construir e Sumarizar Conversas
        threads = self.builder.build_conversations(school_id, campaign_id)
        reports = [self.summarizer.summarize(t) for t in threads]
        
        responses_received = len(reports)
        response_rate = (responses_received / sent_success * 100) if sent_success > 0 else 0

        # 4. Análise de Justificativas e Riscos
        justifications = CampaignJustificationAnalysis(
            health_issues=len([r for r in reports if r.status == OccurrenceStatus.JUSTIFICADO]),
            medical_documents=len([r for r in reports if r.has_medical_document]),
            partial_absences=len([r for r in reports if r.status == OccurrenceStatus.PARCIAL]),
            unresponsive=sent_success - responses_received
        )

        risk = CampaignRiskAnalysis(
            high_risk=len([r for r in reports if r.risk_level == RiskLevel.ALTO]) + justifications.unresponsive,
            medium_risk=len([r for r in reports if r.risk_level == RiskLevel.MEDIO]),
            low_risk=len([r for r in reports if r.risk_level == RiskLevel.BAIXO])
        )

        # 5. Insights Automáticos
        insights = []
        if justifications.health_issues > (responses_received * 0.5):
            insights.append("Saúde é o principal motivo das ausências hoje.")
        if justifications.medical_documents > 0:
            insights.append(f"Foram identificados {justifications.medical_documents} casos com menção a documentos médicos.")
        if risk.high_risk > (total_targeted * 0.3):
            insights.append("Alerta: Volume de alto risco acima do esperado.")
        if response_rate > 70:
            insights.append("Excelente engajamento das famílias na campanha.")

        # 6. Análise por Turma (Simulado - precisaria de join com students para real)
        # Por enquanto, placeholder estruturado
        class_analysis = {
            "Geral": {"total": total_targeted, "justificadas": justifications.health_issues}
        }

        # 7. Casos Prioritários
        priority_cases = [r for r in reports if r.risk_level == RiskLevel.ALTO or r.needs_followup]

        # Buscar nome da campanha
        campaign_info = self.client.schema("busca_ativa_v2").table("campaigns") \
            .select("name") \
            .eq("id", campaign_id) \
            .single() \
            .execute()
        
        campaign_name = campaign_info.data.get("name", "Campanha Desconhecida") if campaign_info.data else "Campanha"

        return ConsolidatedCampaignReport(
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            generated_at=datetime.now(),
            operational=CampaignOperationalMetrics(
                total_students_targeted=total_targeted,
                messages_sent_success=sent_success,
                messages_sent_failed=sent_failed,
                responses_received=responses_received,
                response_rate=response_rate
            ),
            structural=structural,
            justifications=justifications,
            risk=risk,
            insights=insights,
            class_analysis=class_analysis,
            priority_cases=priority_cases[:10] # Top 10 prioridades
        )

    def export_to_json(self, report: ConsolidatedCampaignReport) -> str:
        return report.json(indent=2, ensure_ascii=False)
