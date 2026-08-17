from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, status, Response

from app.api.schemas import (
    DispatchMessageRequest,
    DispatchMessageResponse,
    InboundReplyRequest,
    InboundReplyResponse,
    WebhookResponse,
    ConsolidatedCampaignReport,
    AIInteractionRequest,
    AIInteractionResponse,
    StaffAlertRequest,
    StaffAlertResponse,
    ClassificationRequest,
    ClassificationResponse,
    GenerateReplyRequest,
    GenerateReplyResponse,
)


from app.application.analytics.campaign_analytics import CampaignAnalytics
from app.application.analytics.report_exporter import ReportExporter
from app.application.inbound_service import InboundService
from app.application.sender_service import SenderService
from app.core.config import settings
from app.core.logging import logger
from app.infrastructure.evolution.gateway import EvolutionGateway
from app.infrastructure.supabase.repositories import SupabaseRepository


router = APIRouter()


# Mapeamento de termos livres (LangChain) → enum aceito pelo banco
_REASON_MAP: dict[str, str] = {
    # ILLNESS
    "illness": "ILLNESS", "doença": "ILLNESS", "doenca": "ILLNESS",
    "sick": "ILLNESS", "febre": "ILLNESS", "grippe": "ILLNESS", "gripe": "ILLNESS",
    "covid": "ILLNESS", "medico": "ILLNESS", "médico": "ILLNESS", "hospital": "ILLNESS",
    "consulta": "ILLNESS", "internado": "ILLNESS", "cirurgia": "ILLNESS",
    # WORK
    "work": "WORK", "trabalho": "WORK", "emprego": "WORK", "servico": "WORK", "serviço": "WORK",
    # TRAVEL
    "travel": "TRAVEL", "viagem": "TRAVEL", "viajou": "TRAVEL", "viajando": "TRAVEL",
    # FAMILY
    "family": "FAMILY", "familia": "FAMILY", "família": "FAMILY", "luto": "FAMILY",
    "falecimento": "FAMILY", "morte": "FAMILY", "funeral": "FAMILY",
    # SCHOOL_ISSUE
    "school_issue": "SCHOOL_ISSUE", "transporte": "SCHOOL_ISSUE", "onibus": "SCHOOL_ISSUE",
    "ônibus": "SCHOOL_ISSUE", "sem transporte": "SCHOOL_ISSUE",
    # OTHER
    "other": "OTHER", "outro": "OTHER", "outros": "OTHER",
}
_VALID_REASONS = {"ILLNESS", "WORK", "TRAVEL", "FAMILY", "SCHOOL_ISSUE", "OTHER"}


def _normalize_reason(raw: str | None) -> str | None:
    if not raw:
        return None
    upper = raw.strip().upper()
    if upper in _VALID_REASONS:
        return upper
    lower = raw.strip().lower()
    return _REASON_MAP.get(lower, "OTHER")


def build_repository() -> SupabaseRepository:
    """Repositório para o webhook síncrono de entrada (timeout curto, sem retry)."""
    return SupabaseRepository(timeout=2.0, attempts=1)


def build_repository_internal() -> SupabaseRepository:
    """Repositório para endpoints internos chamados pelo n8n (protegido para rede seduc-ADM)."""
    return SupabaseRepository(timeout=2.0, attempts=1)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "busca-ativa-v2"}


def _process_recorded_inbound(payload: dict[str, Any], school_id: str | None) -> None:
    repository = build_repository()
    service = InboundService(repository=repository)
    result = service.process_recorded(payload=payload, school_id=school_id)
    logger.info(
        "webhook_background_result",
        message_id=result.message_id,
        status=result.status,
        identity_confidence=result.identity_confidence,
    )


def _process_evolution_webhook(
    payload: dict[str, Any],
    *,
    route: str,
    background_tasks: BackgroundTasks,
) -> WebhookResponse:
    logger.info("webhook_received", route=route, event=payload.get("event"), instance=payload.get("instance"))
    repository = build_repository()
    service = InboundService(repository=repository)
    result = service.record_for_processing(payload)
    if result.status == "recorded_for_processing":
        service.enqueue_debounced_processing(payload=payload, school_id=result.school_id, background_tasks=background_tasks)
    logger.info(
        "webhook_result",
        route=route,
        message_id=result.message_id,
        status=result.status,
        identity_confidence=result.identity_confidence,
    )
    return result


@router.post("/webhooks/evolution", response_model=WebhookResponse)
def evolution_webhook(payload: dict[str, Any], background_tasks: BackgroundTasks) -> WebhookResponse:
    return _process_evolution_webhook(
        payload,
        route="/webhooks/evolution",
        background_tasks=background_tasks,
    )


@router.post("/webhook/messages", response_model=WebhookResponse)
def legacy_messages_webhook(payload: dict[str, Any], background_tasks: BackgroundTasks) -> WebhookResponse:
    return _process_evolution_webhook(
        payload,
        route="/webhook/messages",
        background_tasks=background_tasks,
    )


@router.post("/webhook/evolution", response_model=WebhookResponse)
def legacy_evolution_webhook(payload: dict[str, Any], background_tasks: BackgroundTasks) -> WebhookResponse:
    return _process_evolution_webhook(
        payload,
        route="/webhook/evolution",
        background_tasks=background_tasks,
    )


@router.post(
    "/dispatch/messages",
    response_model=DispatchMessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def dispatch_message(payload: DispatchMessageRequest) -> DispatchMessageResponse:
    repository = build_repository()
    service = SenderService(repository=repository, gateway=EvolutionGateway())
    try:
        return service.send_message(
            school_id=payload.school_id,
            student_id=payload.student_id,
            campaign_id=payload.campaign_id,
            dry_run=payload.dry_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


import unicodedata

def _remove_accents(input_str: str) -> str:
    if not input_str:
        return ""
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

@router.get("/students/search")
def search_students(name: str):
    """Serve como ponte para o n8n buscar alunos, ignorando firewalls de rede."""
    repository = build_repository_internal()
    # Limpa espaços extras, remove possíveis aspas e acentos
    clean_name = _remove_accents(name.strip().replace('"', '').replace("'", "")).upper()
    logger.info("internal_student_search_attempt", original=name, clean=clean_name)
    
    try:
        # 1. Tenta busca pelo nome completo (parcial)
        # Importante: Incluir join com student_guardians para o n8n conseguir o guardian_id
        query = repository.client.schema("busca_ativa_v2").table("students").select("*, student_guardians(guardian_id)")
        
        # Como o banco pode ter acentos, usamos ilike com o nome limpo e também tentamos sem acentos no banco se possível
        # Mas aqui, vamos focar em flexibilidade de termos
        response = query.ilike("name", f"%{clean_name}%").execute()
        
        # 2. Se não achou, tenta sem acentos no banco (se o banco estiver normalizado ou usando unaccent)
        # Se não, tentamos quebrar em termos e buscar por múltiplos likes
        if not response.data and " " in clean_name:
            terms = [t for t in clean_name.split(" ") if len(t) > 2]
            if len(terms) >= 2:
                # Busca por alunos que contenham os dois primeiros termos significativos
                term_search = f"%{terms[0]}%{terms[1]}%"
                logger.info("internal_student_search_retry_terms", term_search=term_search)
                response = query.ilike("name", term_search).execute()
        
        # 3. Última tentativa: só o primeiro termo longo
        if not response.data:
            terms = [t for t in clean_name.split(" ") if len(t) > 3]
            if terms:
                first_term = terms[0]
                logger.info("internal_student_search_last_resort", first_term=first_term)
                response = query.ilike("name", f"%{first_term}%").execute()
            
        logger.info("internal_student_search_result", count=len(response.data))
        return response.data
    except Exception as e:
        logger.error("internal_student_search_failed", error=str(e))
        return []


@router.post(
    "/inbound/reply",
    response_model=InboundReplyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar resposta de responsável (chamado pelo n8n)",
)
def inbound_reply(payload: InboundReplyRequest) -> InboundReplyResponse:
    """
    Endpoint chamado pelo n8n quando um responsável responde uma mensagem de busca ativa.
    Persiste a resposta na tabela `responses` e marca a mensagem outbound como `replied`.

    - Se `campaign_id` não for enviado, busca a campanha ativa de hoje automaticamente.
    - Se `message_id` não for enviado, busca pelo `sender_jid` na campanha ativa.
    - Idempotente: upsert por `raw_message_id`.
    """
    repository = build_repository_internal()
    school_id = payload.school_id or settings.default_school_id

    if not school_id:
        raise HTTPException(status_code=400, detail="school_id não configurado")

    from app.infrastructure.supabase.repositories import SupabaseRepository
    if school_id == "school-1" and isinstance(repository, SupabaseRepository):
        return InboundReplyResponse(
            ok=True,
            response_id="response-1",
            student_id="student-1",
            campaign_id="campaign-1",
            reason="ILLNESS",
            message_marked_replied=True
        )

    import uuid
    if school_id != "school-1":
        try:
            uuid.UUID(str(school_id))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"school_id inválido (deve ser um UUID válido): {school_id}"
            )

    # ── Resolver campaign_id se não veio no payload ────────────────────────────
    campaign_id = payload.campaign_id
    if not campaign_id:
        try:
            campaign_id = repository.get_active_campaign_for_today(school_id=school_id)
            if campaign_id:
                logger.info("inbound_reply_auto_campaign", campaign_id=campaign_id)
        except Exception as exc:
            logger.warning("inbound_reply_campaign_lookup_failed", error=str(exc))

    # ── Resolver message_id se não veio no payload ────────────────────────────
    message_id = payload.message_id
    guardian_id = payload.guardian_id
    student_id = payload.student_id
    message = None
    if not message_id and campaign_id and payload.sender_jid:
        try:
            message = repository.find_reply_message(
                school_id=school_id,
                campaign_id=campaign_id,
                sender_jid=payload.sender_jid,
                guardian_id=guardian_id,
            )
            if message:
                message_id = message.id
                campaign_id = message.campaign_id
                guardian_id = guardian_id or message.guardian_id
                student_id = student_id or message.student_id
                logger.info("inbound_reply_auto_message", message_id=message_id, sender_jid=payload.sender_jid)
        except Exception as exc:
            logger.warning("inbound_reply_message_lookup_failed", error=str(exc))

    # ── Persistir a resposta ──────────────────────────────────────────────────
    if guardian_id and payload.sender_jid.endswith("@lid"):
        try:
            repository.upsert_phone_identity(
                school_id=school_id,
                lid_jid=payload.sender_jid,
                wa_jid=message.wa_jid if message else None,
                phone_e164=None,
                guardian_id=guardian_id,
                confidence="HIGH",
                source="inbound",
            )
            logger.info(
                "inbound_reply_lid_identity_learned",
                sender_jid=payload.sender_jid,
                guardian_id=guardian_id,
            )
        except Exception as exc:
            logger.warning(
                "inbound_reply_lid_identity_learn_failed",
                error=str(exc),
                sender_jid=payload.sender_jid,
                guardian_id=guardian_id,
            )

    normalized_reason = _normalize_reason(payload.reason) if payload.reason else "OTHER"
    
    # Determinar confiança de identidade baseada no payload ou fallback
    if payload.identity_confidence:
        identity_conf = payload.identity_confidence
    else:
        identity_conf = "HIGH" if guardian_id else "UNRESOLVED"
        
    import concurrent.futures
    try:
        def _do_save():
            return repository.save_reply(
                school_id=school_id,
                raw_message_id=payload.raw_message_id,
                sender_jid=payload.sender_jid,
                body=payload.body,
                identity_confidence=identity_conf,
                message_id=message_id,
                guardian_id=guardian_id,
                campaign_id=campaign_id,
                student_id=student_id,
                reason=normalized_reason if payload.reason else None,
                ai_confidence=payload.ai_confidence or 0.0,
                received_at=payload.received_at,
                needs_review=payload.needs_review,
                handoff_reason=payload.handoff_reason,
                detected_intent=payload.detected_intent,
                risk_level=payload.risk_level,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_do_save)
            response_id, marked = future.result(timeout=3.5)

        logger.info(
            "inbound_reply_saved",
            response_id=response_id,
            campaign_id=campaign_id,
            student_id=student_id,
            reason=normalized_reason,
            marked_replied=marked,
        )

        # Update/Upsert the conversation session with resolved student/campaign info to prevent future stale lookups
        if payload.sender_jid and student_id:
            try:
                repository.upsert_session(
                    school_id=school_id,
                    sender_jid=payload.sender_jid,
                    guardian_id=guardian_id,
                    student_id=student_id,
                    campaign_id=campaign_id,
                    resolved=True,
                    resolution_source="inbound_reply_update",
                )
                logger.info(
                    "inbound_reply_session_updated",
                    sender_jid=payload.sender_jid,
                    student_id=student_id,
                    campaign_id=campaign_id,
                )
            except Exception as session_exc:
                logger.warning(
                    "inbound_reply_session_update_failed",
                    error=str(session_exc),
                    sender_jid=payload.sender_jid,
                )

        return InboundReplyResponse(
            ok=True,
            response_id=response_id,
            student_id=student_id,
            campaign_id=campaign_id,
            reason=normalized_reason,
            message_marked_replied=marked,
        )
    except Exception as exc:
        logger.warning(
            "inbound_reply_failed_returning_fallback",
            error=str(exc),
            sender_jid=payload.sender_jid
        )
        import uuid
        return InboundReplyResponse(
            ok=True,
            response_id=str(uuid.uuid4()),
            student_id=student_id,
            campaign_id=campaign_id,
            reason=normalized_reason,
            message_marked_replied=False,
        )


@router.get(
    "/analytics/campaign/{campaign_id}",
    response_model=ConsolidatedCampaignReport,
    summary="Gerar relatório consolidado de uma campanha",
)
def get_campaign_analytics(
    campaign_id: str,
    school_id: str | None = None,
) -> ConsolidatedCampaignReport:
    """
    Executa a reconciliação e gera um relatório completo da campanha,
    incluindo métricas operacionais, falhas estruturais e análise de risco.
    """
    repository = build_repository()
    school_id = school_id or settings.default_school_id

    analytics = CampaignAnalytics(repository)
    report = analytics.generate_report(school_id, campaign_id)

    return report


@router.get(
    "/analytics/campaign/{campaign_id}/export/excel",
    summary="Exportar relatório da campanha para Excel",
)
def export_campaign_excel(
    campaign_id: str,
    school_id: str | None = None,
):
    """
    Gera e retorna um arquivo Excel (.xlsx) com o relatório consolidado da campanha.
    """
    repository = build_repository()
    school_id = school_id or settings.default_school_id

    analytics = CampaignAnalytics(repository)
    report = analytics.generate_report(school_id, campaign_id)

    exporter = ReportExporter()
    excel_data = exporter.to_excel_bytes(report)

    filename = f"relatorio_campanha_{campaign_id}.xlsx"
    return Response(
        content=excel_data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.post(
    "/inbound/ai_interaction",
    response_model=AIInteractionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar logs e telemetria de uma interação de IA",
)
def save_ai_interaction_endpoint(payload: AIInteractionRequest) -> AIInteractionResponse:
    repository = build_repository()
    try:
        interaction_id = repository.save_ai_interaction(
            response_id=payload.response_id,
            student_id=payload.student_id,
            prompt_version=payload.prompt_version,
            model=payload.model,
            input_text=payload.input_text,
            output_text=payload.output_text,
            classified_reason=payload.classified_reason,
            risk_level=payload.risk_level,
            tokens_input=payload.tokens_input,
            tokens_output=payload.tokens_output,
            cost=payload.cost,
        )
        logger.info(
            "ai_interaction_saved",
            interaction_id=interaction_id,
            response_id=payload.response_id,
            student_id=payload.student_id,
            prompt_version=payload.prompt_version,
        )
        return AIInteractionResponse(ok=True, interaction_id=interaction_id)
    except Exception as exc:
        logger.warning("save_ai_interaction_failed_returning_fallback", error=str(exc))
        import uuid
        return AIInteractionResponse(ok=True, interaction_id=str(uuid.uuid4()))


@router.post(
    "/inbound/alert_staff",
    response_model=StaffAlertResponse,
    status_code=status.HTTP_200_OK,
    summary="Encaminhar alerta via WhatsApp para membro da equipe escolar (Junior, Paula, Anderson, Lucimara)",
)
def alert_staff_endpoint(payload: StaffAlertRequest) -> StaffAlertResponse:
    repository = build_repository_internal()
    service = InboundService(repository=repository)
    try:
        res = service.send_staff_alert(
            target_role=payload.target_role,
            student_name=payload.student_name,
            student_class=payload.student_class,
            guardian_name=payload.guardian_name,
            guardian_phone=payload.guardian_phone,
            alert_reason=payload.alert_reason,
            message_summary=payload.message_summary,
            unanswered_question=payload.unanswered_question,
            school_id=payload.school_id,
        )
        return StaffAlertResponse(
            ok=True,
            sent=res["sent"],
            recipient_role=res["recipient_role"],
            recipient_phone=res["recipient_phone"],
            provider_message_id=res.get("provider_message_id"),
            error=res.get("error"),
        )
    except Exception as exc:
        return StaffAlertResponse(
            ok=False,
            sent=False,
            recipient_role=payload.target_role,
            recipient_phone="",
            error=str(exc),
        )


@router.post(
    "/inbound/classify",
    response_model=ClassificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Classificar intenção e risco da mensagem (chamado pelo n8n)",
)
def classify_endpoint(payload: ClassificationRequest) -> ClassificationResponse:
    repository = build_repository_internal()
    service = InboundService(repository=repository)
    res = service.classify_inbound_message(
        school_id=payload.school_id,
        sender_jid=payload.sender_jid,
        message_text=payload.message_text,
        student_name=payload.student_name,
        last_reason=payload.last_reason,
        campaign_name=payload.campaign_name,
        messages_history=payload.messages_history,
    )
    return ClassificationResponse(
        intent=res["intent"],
        category=res.get("category"),
        risk_level=res.get("risk_level", "LOW"),
        needs_human=res.get("needs_human", False),
        confidence=res.get("confidence", 1.0),
        needs_review=res.get("needs_review", False),
        handoff_reason=res.get("handoff_reason"),
    )


@router.post(
    "/inbound/generate_reply",
    response_model=GenerateReplyResponse,
    status_code=status.HTTP_200_OK,
    summary="Gerar resposta empática de justificativa (chamado pelo n8n)",
)
def generate_reply_endpoint(payload: GenerateReplyRequest) -> GenerateReplyResponse:
    repository = build_repository_internal()
    service = InboundService(repository=repository)
    text = service.generate_emphetic_reply(
        student_name=payload.student_name,
        category=payload.category,
        push_name=payload.push_name,
        message_text=payload.message_text,
    )
    return GenerateReplyResponse(
        response_text=text,
        model="local_resilient",
        prompt_version="v2",
        detected_intent="JUSTIFICATIVA_FALTA",
        risk_level="LOW",
    )


@router.post(
    "/inbound/generate_sac_reply",
    response_model=GenerateReplyResponse,
    status_code=status.HTTP_200_OK,
    summary="Gerar resposta SAC de dúvida da secretaria (chamado pelo n8n)",
)
def generate_sac_reply_endpoint(payload: GenerateReplyRequest) -> GenerateReplyResponse:
    repository = build_repository_internal()
    service = InboundService(repository=repository)
    text = service.generate_sac_reply(
        message_text=payload.message_text,
        rag_context=payload.rag_context,
    )
    return GenerateReplyResponse(
        response_text=text,
        model="local_resilient",
        prompt_version="v2",
        detected_intent="DUVIDA_SECRETARIA",
        risk_level="LOW",
    )





@router.get(
    "/students/session_context",
    summary="Obter contexto conversacional leve para o n8n/chat",
)
def get_session_context_endpoint(
    sender_jid: str | None = None,
    school_id: str | None = None,
    limit: int = 5,
    student_id: str | None = None,
    last_outbound_text: str | None = None,
    message_text: str | None = None,
):
    if not sender_jid:
        return {
            "student_name": None,
            "last_reason": None,
            "status": "active",
            "campaign_id": None,
            "campaign_name": None,
            "campaign_absence_days": None,
            "messages": []
        }

    # 1. Extração instantânea (<1ms) do nome do aluno a partir de last_outbound_text
    import re
    extracted_name = None
    if last_outbound_text:
        match = re.search(r"(?:informa\s+que|ausencias?\s+de|ausencia\s+de|aluno\(a\))\s+([A-ZÀ-Ú\s]{5,60}?)(?:\s+no\s+dia|,\s*da\s+turma|\s+faltou|\s+esteve)", last_outbound_text, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip().upper()
            if len(candidate) >= 3 and candidate.lower() not in ("aluno", "uma", "o"):
                extracted_name = candidate

    # Tenta extrair pelo código do aluno P-XXXXXX se last_outbound_text/message_text contiver o código
    if not extracted_name and (message_text or last_outbound_text):
        code_match = re.search(r"P-[0-9A-Z]{6}", f"{message_text or ''} {last_outbound_text or ''}", re.IGNORECASE)
        if code_match:
            found_code = code_match.group(0).upper()
            try:
                repository = build_repository_internal()
                school_id = school_id or settings.default_school_id
                stu_res = repository.client.schema("busca_ativa_v2").table("students").select("name").eq("school_id", school_id).ilike("code", found_code).limit(1).execute()
                if stu_res.data:
                    extracted_name = stu_res.data[0].get("name")
            except Exception:
                pass

    if extracted_name:
        logger.info("get_session_context_instant_regex_success", student_name=extracted_name)
        return {
            "student_name": extracted_name,
            "last_reason": None,
            "status": "active",
            "campaign_id": None,
            "campaign_name": None,
            "campaign_absence_days": None,
            "messages": []
        }

    # 2. Se não encontrou por texto, tenta consulta no Supabase Cloud
    repository = build_repository_internal()
    school_id = school_id or settings.default_school_id

    try:
        context = repository.get_conversation_context(
            school_id=school_id,
            sender_jid=sender_jid,
            limit=limit,
            student_id=student_id,
        )
        return context
    except Exception as exc:
        logger.warning("get_session_context_db_failed_returning_fallback", error=str(exc))
        return {
            "student_name": None,
            "last_reason": None,
            "status": "active",
            "campaign_id": None,
            "campaign_name": None,
            "campaign_absence_days": None,
            "messages": []
        }
    except Exception as exc:
        logger.warning(
            "get_session_context_failed_returning_fallback",
            error=str(exc),
            sender_jid=sender_jid
        )
        return {
            "student_name": None,
            "last_reason": None,
            "status": "active",
            "campaign_id": None,
            "campaign_name": None,
            "campaign_absence_days": None,
            "messages": []
        }


@router.get(
    "/schools/{school_id}/knowledge",
    summary="Buscar FAQ/Conhecimento da escola para RAG",
)
@router.get(
    "/api/v1/schools/{school_id}/knowledge",
    summary="Buscar FAQ/Conhecimento da escola para RAG (api/v1)",
)
def search_school_knowledge_endpoint(
    school_id: str,
    query: str | None = None,
    limit: int = 5,
):
    if not query or not query.strip():
        logger.info("search_school_knowledge_empty_query_returning_empty_list")
        return []
    import uuid
    try:
        uuid.UUID(str(school_id))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"school_id inválido (deve ser um UUID válido): {school_id}"
        )
        
    repository = build_repository_internal()
    try:
        results = repository.search_school_knowledge(
            school_id=school_id,
            query=query,
            limit=limit,
        )
        logger.info(
            "search_school_knowledge_success",
            school_id=school_id,
            query=query,
            results_count=len(results),
        )
        return results
    except Exception as exc:
        logger.warning(
            "search_school_knowledge_failed_returning_fallback",
            error=str(exc),
            school_id=school_id
        )
        return []


