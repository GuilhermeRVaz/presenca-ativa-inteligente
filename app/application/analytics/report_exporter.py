import pandas as pd
import io
from typing import List
from app.api.schemas import ConsolidatedCampaignReport
from app.core.logging import logger

class ReportExporter:
    """
    Exportador de relatórios analíticos para formatos executivos (Excel/CSV).
    """

    @staticmethod
    def to_excel_bytes(report: ConsolidatedCampaignReport) -> bytes:
        """
        Gera um arquivo Excel multi-planilha com os dados da campanha.
        """
        output = io.BytesIO()
        
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # 1. Planilha de Resumo (Operational + Structural)
            summary_data = {
                "Métrica": [
                    "Total Alunos Alvo",
                    "Mensagens Enviadas (Sucesso)",
                    "Mensagens Enviadas (Falha)",
                    "Respostas Recebidas",
                    "Taxa de Resposta (%)",
                    "Falta de Responsável Vinculado",
                    "Números Inválidos",
                    "Não Encontrados no Banco",
                    "Total Falhas Estruturais"
                ],
                "Valor": [
                    report.operational.total_students_targeted,
                    report.operational.messages_sent_success,
                    report.operational.messages_sent_failed,
                    report.operational.responses_received,
                    report.operational.response_rate * 100,
                    report.structural.no_guardian_linked,
                    report.structural.invalid_numbers,
                    report.structural.not_found_in_db,
                    report.structural.total_structural_issues
                ]
            }
            pd.DataFrame(summary_data).to_excel(writer, sheet_name='Resumo Executivo', index=False)

            # 2. Planilha de Riscos e Justificativas
            risk_data = {
                "Categoria": [
                    "Alto Risco (Evasão/Sem Resposta)",
                    "Médio Risco (Problemas Escolares/Outros)",
                    "Baixo Risco (Justificadas/Saúde)",
                    "Justificativa: Saúde",
                    "Justificativa: Documentos Médicos",
                    "Justificativa: Faltas Parciais",
                    "Justificativa: Sem Resposta"
                ],
                "Contagem": [
                    report.risk.high_risk,
                    report.risk.medium_risk,
                    report.risk.low_risk,
                    report.justifications.health_issues,
                    report.justifications.medical_documents,
                    report.justifications.partial_absences,
                    report.justifications.unresponsive
                ]
            }
            pd.DataFrame(risk_data).to_excel(writer, sheet_name='Análise de Risco', index=False)

            # 3. Planilha de Casos Prioritários
            if report.priority_cases:
                priority_rows = []
                for case in report.priority_cases:
                    priority_rows.append({
                        "Aluno ID": case.get("student_id", ""),
                        "Sender JID": case.get("sender_jid", ""),
                        "Status": case.get("status", ""),
                        "Nível de Risco": case.get("risk_level", ""),
                        "Precisa Follow-up": case.get("needs_followup", False),
                        "Documento Médico": case.get("has_medical_document", False),
                        "Resumo da Conversa": case.get("summary_text", ""),
                        "Qtd Mensagens": case.get("message_count", 0),
                    })
                pd.DataFrame(priority_rows).to_excel(writer, sheet_name='Casos Prioritários', index=False)

            # 4. Análise por Turma
            if report.class_analysis:
                class_rows = []
                for class_name, metrics in report.class_analysis.items():
                    class_rows.append({
                        "Turma": class_name,
                        "Total": metrics.get("total", 0),
                        "Respondidos": metrics.get("responded", 0),
                        "Alto Risco": metrics.get("high_risk", 0)
                    })
                pd.DataFrame(class_rows).to_excel(writer, sheet_name='Análise por Turma', index=False)

            # 5. Insights Automáticos
            pd.DataFrame({"Insights": report.insights}).to_excel(writer, sheet_name='Insights IA', index=False)

        return output.getvalue()

    @staticmethod
    def to_csv_priority_cases(report: ConsolidatedCampaignReport) -> str:
        """
        Gera um CSV simplificado dos casos prioritários para importação em outros sistemas.
        """
        if not report.priority_cases:
            return "student_id,status,risk_level,summary\n"
        
        priority_rows = []
        for case in report.priority_cases:
            priority_rows.append({
                "student_id": case.get("student_id", ""),
                "sender_jid": case.get("sender_jid", ""),
                "status": case.get("status", ""),
                "risk_level": case.get("risk_level", ""),
                "needs_followup": case.get("needs_followup", False),
                "summary": case.get("summary_text", ""),
            })
        
        return pd.DataFrame(priority_rows).to_csv(index=False)
