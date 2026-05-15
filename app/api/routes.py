from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, status, Response

from app.api.schemas import (
    DispatchMessageRequest,
    DispatchMessageResponse,
    InboundReplyRequest,
    InboundReplyResponse,
    WebhookResponse,
    ConsolidatedCampaignReport,
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
    return SupabaseRepository()


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
    print(f"WEBHOOK RECEBIDO [{route}]:", payload)
    print("--> chamando inbound_service")
    repository = build_repository()
    service = InboundService(repository=repository)
    result = service.record_for_processing(payload)
    if result.status == "recorded_for_processing":
        background_tasks.add_task(_process_recorded_inbound, payload, result.school_id)
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
    repository = build_repository()
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
    repository = build_repository()
    school_id = payload.school_id or settings.default_school_id

    if not school_id:
        raise HTTPException(status_code=400, detail="school_id não configurado")

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
        
    try:
        response_id, marked = repository.save_reply(
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
        )
        logger.info(
            "inbound_reply_saved",
            response_id=response_id,
            campaign_id=campaign_id,
            student_id=student_id,
            reason=normalized_reason,
            marked_replied=marked,
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
        logger.exception("inbound_reply_failed", error=str(exc), sender_jid=payload.sender_jid)
        raise HTTPException(status_code=500, detail=f"Falha ao gravar resposta: {exc}") from exc


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
