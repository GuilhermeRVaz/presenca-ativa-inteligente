from datetime import datetime, date
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import json
from collections import defaultdict

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

def get_campaign_theme(name: str) -> str:
    name_lower = (name or "").lower()
    if "obmep" in name_lower:
        return "obmep"
    if "bolsa" in name_lower:
        return "bolsa"
    return "general"

def resolve_campaign_group(client, school_id: str, campaign_id_input: Any, execute_wrapper=None) -> tuple[list[str], list[dict]]:
    if execute_wrapper is None:
        execute_wrapper = lambda func, **kwargs: func()

    if isinstance(campaign_id_input, list):
        input_ids = campaign_id_input
    elif isinstance(campaign_id_input, str) and "," in campaign_id_input:
        input_ids = [c.strip() for c in campaign_id_input.split(",")]
    else:
        input_ids = [campaign_id_input]

    if not input_ids:
        return [], []

    try:
        tbl = client.schema("busca_ativa_v2").table("campaigns") if hasattr(client, "schema") else client.table("campaigns")
    except Exception:
        tbl = client.table("campaigns")

    try:
        res = execute_wrapper(
            lambda: tbl.select("id, absence_days, parent_campaign_id, campaign_type, name").in_("id", input_ids).execute(),
            operation="resolve_campaign_group_details"
        )
        camps_data = res.data or []
    except Exception as e:
        logger.warning(f"Failed to query campaigns in group: {e}")
        return input_ids, []

    if not camps_data:
        return input_ids, []

    absence_days = camps_data[0].get("absence_days")
    if not absence_days:
        return input_ids, camps_data

    try:
        res_all = execute_wrapper(
            lambda: tbl.select("id, parent_campaign_id, campaign_type, name").eq("school_id", school_id).eq("absence_days", absence_days).execute(),
            operation="resolve_campaign_group_all"
        )
        all_camps = res_all.data or []
    except Exception as e:
        logger.warning(f"Failed to query all campaigns on date: {e}")
        return input_ids, camps_data

    roots = set()
    for c in camps_data:
        p_id = c.get("parent_campaign_id")
        if p_id:
            roots.add(p_id)
        else:
            roots.add(c["id"])

    group_ids = set(input_ids)
    camps_in_group = {c["id"]: c for c in camps_data}
    input_themes = {get_campaign_theme(c.get("name")) for c in camps_data}

    for c in all_camps:
        c_id = c["id"]
        p_id = c.get("parent_campaign_id")
        
        # Link via parent chain
        is_linked = c_id in roots or p_id in roots
        
        # Link via same theme on same day
        same_theme = get_campaign_theme(c.get("name")) in input_themes
        
        if is_linked or same_theme:
            group_ids.add(c_id)
            camps_in_group[c_id] = c

    return sorted(list(group_ids)), list(camps_in_group.values())

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

    def resolve_campaign_group_ids(self, school_id: str, campaign_id_input: Any) -> tuple[list[str], list[dict]]:
        return resolve_campaign_group(self.client, school_id, campaign_id_input, self.repository._execute_with_retry)

    def generate_report(self, school_id: str, campaign_id: str) -> ConsolidatedCampaignReport:
        logger.info("analytics_report_generation_started", campaign_id=campaign_id)

        # Resolvendo o grupo de campanhas (RF-01)
        group_campaign_ids, camps_data = self.resolve_campaign_group_ids(school_id, campaign_id)

        # 1. Executar Reconciliação Retrospectiva primeiro para garantir dados limpos para o grupo inteiro
        self.reconciler.reconcile_unresolved_responses(
            window_hours=48,
            school_id=school_id,
            campaign_id=group_campaign_ids,
        )

        # 2. Buscar Dados de Outbound (Estruturais e Operacionais)
        messages_query = self.client.schema("busca_ativa_v2").table("messages").select(
            "status, student_id, last_error, wa_jid, tracking_ref, students(ra)"
        ).in_("campaign_id", group_campaign_ids)
        
        outbound_res = self.repository._execute_with_retry(
            lambda: messages_query.execute(),
            operation="analytics_get_outbound_messages"
        )
        
        messages = outbound_res.data or []
        
        def get_student_key(student_id: str, student_ra: Optional[str]) -> str:
            if student_ra and str(student_ra).strip():
                return f"ra:{str(student_ra).strip()}"
            return f"id:{student_id}"

        # Agrupar outbound por aluno único (RF-03)
        student_outbounds = defaultdict(list)
        student_id_to_ra = {}
        for m in messages:
            sid = m.get("student_id")
            if not sid:
                continue
            ra = None
            stu = m.get("students")
            if isinstance(stu, dict):
                ra = stu.get("ra")
            elif isinstance(stu, list) and len(stu) > 0:
                ra = stu[0].get("ra")
            
            if ra:
                student_id_to_ra[sid] = ra
            skey = get_student_key(sid, ra)
            student_outbounds[skey].append(m)

        total_targeted = len(student_outbounds)
        sent_success = 0
        sent_failed = 0
        for skey, msgs in student_outbounds.items():
            has_success = any(m["status"] in ["sent", "delivered", "read", "replied"] for m in msgs)
            if has_success:
                sent_success += 1
            else:
                has_failed = any(m["status"] == "failed" for m in msgs)
                if has_failed:
                    sent_failed += 1
        
        # Simulação de falhas estruturais por aluno único
        no_guardian_count = 0
        invalid_numbers_count = 0
        for skey, msgs in student_outbounds.items():
            has_success = any(m["status"] in ["sent", "delivered", "read", "replied"] for m in msgs)
            if not has_success:
                has_no_guardian = any("no guardian" in (m.get("last_error") or "").lower() for m in msgs)
                has_invalid = any("invalid" in (m.get("last_error") or "").lower() for m in msgs)
                if has_no_guardian:
                    no_guardian_count += 1
                if has_invalid:
                    invalid_numbers_count += 1

        structural = CampaignStructuralFailures(
            no_guardian_linked=no_guardian_count,
            invalid_numbers=invalid_numbers_count,
            not_found_in_db=0,
            total_structural_issues=sent_failed
        )

        # 3. Construir e Sumarizar Conversas para o grupo
        threads = self.builder.build_conversations(school_id, group_campaign_ids)
        reports = [self.summarizer.summarize(t) for t in threads]
        
        # Mapear jid de outbound para student_id para ajudar a resolver orphans
        jid_to_student_id = {}
        for m in messages:
            sid = m.get("student_id")
            wa_jid = m.get("wa_jid")
            if wa_jid and sid:
                jid_to_student_id[wa_jid] = sid

        # Carregar mapa de identidade para auxílio na resolução
        identity_map = {}
        try:
            id_rows = self.client.schema("busca_ativa_v2").table("phone_identity_map").select("wa_jid, lid_jid").execute().data or []
            for row in id_rows:
                if row.get("lid_jid") and row.get("wa_jid"):
                    identity_map[row["lid_jid"]] = row["wa_jid"]
        except Exception:
            pass

        # Agrupar reports por aluno único
        student_reports = defaultdict(list)
        for r in reports:
            sid = r.student_id
            if not sid and r.sender_jid:
                resolved_sender = identity_map.get(r.sender_jid, r.sender_jid)
                sid = jid_to_student_id.get(resolved_sender) or jid_to_student_id.get(r.sender_jid)
            
            if sid:
                ra = student_id_to_ra.get(sid)
                skey = get_student_key(sid, ra)
                student_reports[skey].append(r)

        # 3.5 Carregar TODAS as respostas para alinhamento de métricas idênticas
        try:
            camp_created = camps_data[0].get("created_at", "")
            if camp_created:
                camp_date_str = camp_created[:10]
            else:
                abs_day = camps_data[0].get("absence_days", "").split(",")[0].strip()
                camp_date_str = datetime.strptime(abs_day, "%d/%m/%Y").strftime("%Y-%m-%d")
        except Exception:
            camp_date_str = datetime.now().strftime("%Y-%m-%d")

        or_filters = [f"campaign_id.in.({','.join(group_campaign_ids)})", f"received_at.gte.{camp_date_str}T00:00:00+00:00"]
        responses_query = self.client.schema("busca_ativa_v2").table("responses").select("*").or_(",".join(or_filters))
        responses_res = self.repository._execute_with_retry(
            lambda: responses_query.execute(),
            operation="analytics_get_responses"
        )
        responses_raw = responses_res.data or []

        all_resps = []
        for r in responses_raw:
            if r.get("campaign_id") in group_campaign_ids:
                all_resps.append(r)
                continue
            rx_at_str = r.get("received_at")
            if rx_at_str:
                try:
                    if rx_at_str[:10] == camp_date_str:
                        all_resps.append(r)
                except Exception:
                    pass

        student_id_to_key = {}
        for skey, msgs in student_outbounds.items():
            for m in msgs:
                sid = m.get("student_id")
                if sid:
                    student_id_to_key[sid] = skey

        by_sender = defaultdict(list)
        for r in all_resps:
            if r.get("sender_jid"):
                by_sender[r["sender_jid"]].append(r)

        from scripts.consolidate_campaign_report import analyze_inbound, extract_protocol, suggest_student

        student_responses = defaultdict(list)
        for sender, resps in by_sender.items():
            target_skey = None
            for r in resps:
                sid = r.get("student_id")
                if sid:
                    target_skey = student_id_to_key.get(sid) or get_student_key(sid, student_id_to_ra.get(sid))
                    break

            if not target_skey:
                for r in resps:
                    proto = extract_protocol(r.get("body") or "")
                    if proto:
                        for m in messages:
                            if proto in (m.get("body_preview") or ""):
                                sid = m.get("student_id")
                                if sid:
                                    target_skey = student_id_to_key.get(sid) or get_student_key(sid, student_id_to_ra.get(sid))
                                    break
                        if target_skey:
                            break

            if not target_skey:
                resolved_sender = identity_map.get(sender, sender)
                for skey, msgs in student_outbounds.items():
                    if any(m.get("wa_jid") == resolved_sender for m in msgs):
                        target_skey = skey
                        break

            if not target_skey:
                suggestion_text = f" | ".join(str(r.get("body") or "") for r in resps)
                suggested_name, score, note = suggest_student(messages, suggestion_text)
                if suggested_name:
                    for m in messages:
                        if m.get("students", {}).get("name") == suggested_name:
                            sid = m.get("student_id")
                            if sid:
                                target_skey = student_id_to_key.get(sid) or get_student_key(sid, student_id_to_ra.get(sid))
                                break

            if target_skey:
                student_responses[target_skey].extend(resps)

        # Consolidar status e justificativas por aluno único (RF-04, RF-05, RF-06, RF-08)
        consolidated_student_reports = {}
        for skey, msgs in student_outbounds.items():
            reps = student_reports.get(skey, [])
            resps_db = student_responses.get(skey, [])
            responded = len(reps) > 0 or len(resps_db) > 0
            
            justified = False
            has_med = False
            
            # Verificar justificativas nas respostas do banco
            for r in resps_db:
                body = r.get("body") or ""
                reason_db = r.get("reason")
                has_p, has_r = analyze_inbound(body, reason_db)
                if has_r:
                    justified = True
                
                # Check medical documents
                from app.application.analytics.conversation_summarizer import ConversationSummarizer
                sumry = ConversationSummarizer()
                if any(kw in body.lower() for kw in sumry.medical_keywords):
                    has_med = True
                    justified = True

            # Verificar justificativas nos threads analisados
            for r in reps:
                if r.status == OccurrenceStatus.JUSTIFICADO:
                    justified = True
                if r.has_medical_document:
                    has_med = True

            if responded:
                if justified or has_med:
                    status = OccurrenceStatus.JUSTIFICADO
                    risk_level = RiskLevel.BAIXO
                    needs_followup = False
                elif any(r.status == OccurrenceStatus.PARCIAL for r in reps):
                    status = OccurrenceStatus.PARCIAL
                    risk_level = RiskLevel.MEDIO
                    needs_followup = True
                else:
                    status = OccurrenceStatus.CRITICO
                    risk_level = RiskLevel.ALTO
                    needs_followup = True
            else:
                status = OccurrenceStatus.SEM_RESPOSTA
                risk_level = RiskLevel.ALTO
                needs_followup = True

            consolidated_student_reports[skey] = {
                "responded": responded,
                "justified": status == OccurrenceStatus.JUSTIFICADO,
                "has_medical_document": has_med,
                "partial": status == OccurrenceStatus.PARCIAL,
                "status": status,
                "risk_level": risk_level,
                "needs_followup": needs_followup
            }

        responses_received = sum(1 for s in consolidated_student_reports.values() if s["responded"])
        response_rate = (responses_received / sent_success) if sent_success > 0 else 0

        # 4. Análise de Justificativas e Riscos
        justifications = CampaignJustificationAnalysis(
            health_issues=sum(1 for s in consolidated_student_reports.values() if s["status"] == OccurrenceStatus.JUSTIFICADO),
            medical_documents=sum(1 for s in consolidated_student_reports.values() if s["has_medical_document"]),
            partial_absences=sum(1 for s in consolidated_student_reports.values() if s["status"] == OccurrenceStatus.PARCIAL),
            unresponsive=sent_success - responses_received
        )

        risk = CampaignRiskAnalysis(
            high_risk=sum(1 for s in consolidated_student_reports.values() if s["risk_level"] == RiskLevel.ALTO),
            medium_risk=sum(1 for s in consolidated_student_reports.values() if s["risk_level"] == RiskLevel.MEDIO),
            low_risk=sum(1 for s in consolidated_student_reports.values() if s["risk_level"] == RiskLevel.BAIXO)
        )

        # Log de Diagnóstico [CONSOLIDACAO]
        principal_ids = [c["id"] for c in camps_data if c.get("campaign_type") in ["primary", "manual"] or not c.get("parent_campaign_id")]
        followup_ids = [c["id"] for c in camps_data if c.get("campaign_type") == "followup"]
        
        responded_principal_count = 0
        responded_followup_count = 0
        recovered_count = 0

        from scripts.consolidate_campaign_report import _parse_db_timestamp

        for skey, data in student_outbounds.items():
            resps_db = student_responses.get(skey, [])
            reps_threads = student_reports.get(skey, [])
            
            resp_p = False
            resp_f = False
            
            for r in resps_db:
                c_id = r.get("campaign_id")
                if c_id in principal_ids:
                    resp_p = True
                elif c_id in followup_ids:
                    resp_f = True

            if not resp_p and not resp_f:
                for r in resps_db:
                    m_id = r.get("message_id")
                    if m_id:
                        for m in data:
                            if m.get("id") == m_id:
                                if m.get("campaign_id") in principal_ids:
                                    resp_p = True
                                elif m.get("campaign_id") in followup_ids:
                                    resp_f = True
                                break

            if (resps_db or reps_threads) and not resp_p and not resp_f:
                followup_sent_at = None
                for m in data:
                    if m.get("campaign_id") in followup_ids and (m.get("sent_at") or m.get("created_at")):
                        followup_sent_at = _parse_db_timestamp(m.get("sent_at") or m.get("created_at"))
                        break
                
                replied_in_followup = False
                for r in resps_db:
                    r_ts = _parse_db_timestamp(r.get("received_at"))
                    if followup_sent_at and r_ts >= followup_sent_at:
                        replied_in_followup = True
                for e in reps_threads:
                    # Thread events
                    summary_text = getattr(e, "summary_text", "") or ""
                    for msg_node in summary_text.splitlines():
                        try:
                            # Parse received_at from summary_text line e.g. [10/06 16:32]
                            pass
                        except Exception:
                            pass
                        
                if replied_in_followup:
                    resp_f = True
                else:
                    resp_p = True

            if resp_p:
                responded_principal_count += 1
            if resp_f:
                responded_followup_count += 1
            if resp_f and not resp_p:
                recovered_count += 1

        print(f"\n[CONSOLIDACAO]")
        print(f"Alunos únicos: {sent_success}")
        print(f"Responderam: {responses_received}")
        print(f"Justificaram: {justifications.health_issues}")
        print(f"Sem resposta: {sent_success - responses_received}")
        print(f"\nOrigem:")
        print(f"Principal: {responded_principal_count}")
        print(f"Follow-up: {responded_followup_count}")
        print(f"\nRespostas recuperadas do Follow-up: {recovered_count}\n")

        # 5. Insights Automáticos
        insights = []
        if justifications.health_issues > (responses_received * 0.5) and responses_received > 0:
            insights.append("Saúde é o principal motivo das ausências hoje.")
        if justifications.medical_documents > 0:
            insights.append(f"Foram identificados {justifications.medical_documents} casos com menção a documentos médicos.")
        if risk.high_risk > (total_targeted * 0.3):
            insights.append("Alerta: Volume de alto risco acima do esperado.")
        if response_rate > 0.70:
            insights.append("Excelente engajamento das famílias na campanha.")

        # 6. Análise por Turma
        class_analysis = {
            "Geral": {"total": total_targeted, "justificadas": justifications.health_issues}
        }

        # 7. Casos Prioritários
        # Filtrar reports originais de alta prioridade de forma deduplicada
        priority_cases = []
        for skey, reps in student_reports.items():
            if not reps:
                continue
            reps_sorted = sorted(reps, key=lambda r: (0 if r.status == OccurrenceStatus.CRITICO else (1 if r.status == OccurrenceStatus.PARCIAL else 2)))
            top_rep = reps_sorted[0]
            if top_rep.risk_level == RiskLevel.ALTO or top_rep.needs_followup:
                priority_cases.append(top_rep)

        # Nome da campanha consolidado
        campaign_name = " + ".join(c.get("name", "") for c in camps_data if c.get("name")) or "Campanha Combinada"

        return ConsolidatedCampaignReport(
            campaign_id=",".join(group_campaign_ids),
            campaign_name=campaign_name,
            generated_at=datetime.now().isoformat(),
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
            priority_cases=[r.model_dump() for r in priority_cases[:10]] # Top 10 prioridades
        )

    def export_to_json(self, report: ConsolidatedCampaignReport) -> str:
        return report.json(indent=2, ensure_ascii=False)
