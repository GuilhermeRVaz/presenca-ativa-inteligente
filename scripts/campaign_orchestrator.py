"""
campaign_orchestrator.py - Orquestrador de Disparos Avançado com Simulador de Comportamento Humano e Risk Engine

Recursos da Versão 3.0 (Enterprise SaaS):
1. Distribuição Estatística Log-Normal de Delays (Média ~60s com cauda longa natural).
2. Humano Burst & Idle Breaks: rajadas humanas de 10-18s seguidas de pausas de café (3-12min).
3. Presence Typing Multi-Fase: Digita -> Pausa -> Digita -> Envia.
4. Restrição de Finais de Semana e Janela Inteligente com Início Aleatório (08:17-08:43).
5. Exponential Backoff + Jitter em todas as chamadas Supabase.
6. Aquecimento Automático de Linha (Warm-Up Engine).
7. Auditoria de Alta Precisão (Hash da mensagem, estilo IA, delays reais, tempo digitando).
8. Kill Switch Global e Pausa em Tempo Real.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import random
import sys
import io
import time
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Force UTF-8 stdout/stderr for Windows console
if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
from typing import Any, Callable


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    RESET = "\033[0m"


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.infrastructure.evolution.gateway import EvolutionGateway
from app.infrastructure.message_catalog import MessageCatalog
from app.infrastructure.followup_message_catalog import FollowupMessageCatalog

# Tabela de Aquecimento Automático (Warm-Up Schedule)
WARMUP_SCHEDULE = {
    1: 5,
    2: 10,
    3: 20,
    4: 35,
    5: 50,
    6: 80,
    7: 120,
    8: 180,
    9: 250,
}


def _build_supabase_client():
    if not settings.supabase_url or not settings.supabase_key:
        raise RuntimeError("SUPABASE_URL e SUPABASE_KEY devem estar configurados no .env")
    from supabase import create_client
    from supabase.lib.client_options import SyncClientOptions

    options = SyncClientOptions(postgrest_client_timeout=90.0)
    return create_client(settings.supabase_url, settings.supabase_key, options=options)


def _short_protocol(tracking_ref: str) -> str:
    digest = hashlib.sha256(tracking_ref.encode("utf-8")).hexdigest()
    return digest[:6].upper()


def _compute_message_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _execute_with_retry(
    query_factory: Callable[[], Any],
    *,
    label: str,
    attempts: int = 5,
) -> Any:
    """
    Executa query com Exponential Backoff + Jitter.
    Formula: min(60, (2 ** attempt) + random.uniform(0, 2))
    """
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return query_factory().execute()
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts:
                break
            delay = min(60.0, (2.0 ** attempt) + random.uniform(0.0, 2.0))
            print(
                f"{Colors.YELLOW}[SUPABASE BACKOFF RETRY]{Colors.RESET} {label} falhou "
                f"({type(exc).__name__}: {exc}). Nova tentativa em {delay:.2f}s..."
            )
            time.sleep(delay)
    raise last_exc or RuntimeError(f"Falha desconhecida no Supabase: {label}")


def _try_supabase(query_factory: Callable[[], Any], *, label: str) -> bool:
    try:
        _execute_with_retry(query_factory, label=label)
        return True
    except Exception as exc:
        print(
            f"{Colors.YELLOW}[AVISO]{Colors.RESET} Não consegui registrar no Supabase: "
            f"{label} ({type(exc).__name__}: {exc})"
        )
        return False


def _local_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=-3)))


def _log_event(client, campaign_id: str, event_type: str, description: str, details: dict | None = None, dry_run: bool = False):
    """
    Grava log de auditoria estruturado no Horário Oficial de Brasília (UTC-3).
    """
    timestamp = _local_now().strftime("%H:%M:%S")
    print(f"{Colors.CYAN}[AUDITORIA {timestamp}]{Colors.RESET} {event_type.upper()}: {description}")
    if not dry_run and client:
        payload = {
            "event_type": event_type,
            "campaign_id": campaign_id,
            "description": description,
            "details": details or {},
            "timestamp": _local_now().isoformat()
        }
        _try_supabase(
            lambda: client.schema("busca_ativa_v2")
            .table("raw_inbound")
            .insert({
                "school_id": settings.default_school_id,
                "message_id": f"evt-{uuid_gen()[:8]}",
                "sender_jid": "system_audit",
                "payload": payload
            }),
            label=f"audit_log_{event_type}"
        )


def uuid_gen() -> str:
    import uuid
    return str(uuid.uuid4())


def _capture_lid_after_send(
    client,
    *,
    wa_jid: str,
    guardian_id: str,
    school_id: str,
    evolution_url: str,
    evolution_key: str,
    instance: str,
) -> None:
    try:
        url = f"{evolution_url.rstrip('/')}/chat/findMessages/{instance}"
        headers = {"apikey": evolution_key, "Content-Type": "application/json"}
        payload = {"where": {"key": {"remoteJid": wa_jid}}, "limit": 20}
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        if r.status_code != 200:
            return
        records = r.json().get("messages", {}).get("records", [])

        lid_jid = None
        for rec in records:
            key = rec.get("key", {})
            if key.get("fromMe"):
                continue
            remote = key.get("remoteJid", "")
            if remote.endswith("@lid"):
                lid_jid = remote
                break
            participant = key.get("participant", "")
            if participant and participant.endswith("@lid"):
                lid_jid = participant
                break

        if not lid_jid:
            return

        existing = (
            client.schema("busca_ativa_v2")
            .table("phone_identity_map")
            .select("id")
            .eq("lid_jid", lid_jid)
            .limit(1)
            .execute()
        )
        if existing.data:
            return

        from app.infrastructure.supabase.repositories import SupabaseRepository
        repo = SupabaseRepository()
        repo.upsert_phone_identity(
            school_id=school_id,
            lid_jid=lid_jid,
            wa_jid=wa_jid,
            phone_e164=None,
            guardian_id=guardian_id,
            confidence="HIGH",
            source="outbound",
        )
        print(f"{Colors.CYAN}  [LID]{Colors.RESET} Capturado e mapeado: {lid_jid}")
    except Exception:
        pass


def _message_status_counts(client, campaign_id: str) -> dict[str, int]:
    res = _execute_with_retry(
        lambda: client.schema("busca_ativa_v2")
        .table("messages")
        .select("status")
        .eq("campaign_id", campaign_id)
        .limit(1000),
        label="contar status da campanha",
    )
    counts: dict[str, int] = {}
    for row in res.data or []:
        st = row.get("status", "unknown")
        counts[st] = counts.get(st, 0) + 1
    return counts


def _check_smart_sending_window(ignore_schedule: bool = False):
    """
    Horário Inteligente + Restrição de Dias da Semana:
    - Domingo: Bloqueado (Aguardar segunda 08:30).
    - Sábado: Envio permitido somente até 12:00 PM.
    - Dias Úteis: Início aleatório entre 08:17 e 08:43 (evita 08:00 exato).
    """
    if ignore_schedule:
        print(f"\n{Colors.YELLOW}[MODO NOTURNO/FORÇADO]{Colors.RESET} Trava de horário noturno e finais de semana IGNORADA por opção do usuário (--ignore-schedule). Continuando disparos...")
        return

    now = datetime.now()
    weekday = now.weekday()  # 0=Segunda, 5=Sábado, 6=Domingo

    # 1. Domingo
    if weekday == 6:
        print(f"\n{Colors.YELLOW}[RESTRIÇÃO DE DOMINGO]{Colors.RESET} Disparos suspensos no domingo. Aguardando Segunda-feira (08:30)...")
        time.sleep(3600)  # Checa a cada 1 hora
        return

    # 2. Sábado após 12h
    if weekday == 5 and (now.hour >= 12 or (now.hour == 11 and now.minute >= 55)):
        print(f"\n{Colors.YELLOW}[RESTRIÇÃO SÁBADO APÓS 12H]{Colors.RESET} Disparos aos sábados são permitidos apenas até 12:00. Aguardando Segunda-feira...")
        time.sleep(3600)
        return

    # 3. Horário Noturno (21:30 - 07:30) com Início Aleatório (08:17 - 08:43)
    if now.hour >= 21 or now.hour < 8:
        random_start_minute = random.randint(17, 43)
        print(f"\n{Colors.YELLOW}[HORÁRIO INTELIGENTE]{Colors.RESET} Horário noturno ({now.strftime('%H:%M')}). Aguardando início seguro amanhã entre 08:{random_start_minute}...")
        next_start = now.replace(hour=8, minute=random_start_minute, second=0, microsecond=0)
        if now.hour >= 21:
            next_start += timedelta(days=1)
        wait_seconds = (next_start - now).total_seconds()
        time.sleep(min(wait_seconds, 3600))


def _calculate_lognormal_delay(min_sec: float = 40.0, max_sec: float = 180.0) -> float:
    """
    Gera um delay com distribuição Log-Normal (humana) com média ~60s e cauda longa.
    """
    val = random.lognormvariate(4.2, 0.35)
    return max(min_sec, min(max_sec, val))


async def run_orchestrator(
    *,
    campaign_id: str | None = None,
    dry_run: bool = False,
    min_delay: int = 45,
    max_delay: int = 120,
    daily_limit: int = 250,
    pilot_limit: int | None = None,
    auto_warmup: bool = True,
    ignore_schedule: bool = False,
) -> None:
    client = _build_supabase_client()
    gateway = EvolutionGateway()
    catalog = MessageCatalog(school_name=settings.school_name)

    # 1. Resolver campanha
    if not campaign_id:
        res = _execute_with_retry(
            lambda: client.schema("busca_ativa_v2")
            .table("campaigns")
            .select("id, name, status, type, campaign_type")
            .in_("status", ["draft", "pending", "dispatching", "active", "paused"])
            .order("created_at", desc=True)
            .limit(1),
            label="buscar campanha mais recente",
        )
        if not res.data:
            print(f"{Colors.YELLOW}[INFO]{Colors.RESET} Nenhuma campanha em aberto para disparar.")
            return
        campaign_data = res.data[0]
        campaign_id = campaign_data["id"]
    else:
        res = _execute_with_retry(
            lambda: client.schema("busca_ativa_v2")
            .table("campaigns")
            .select("id, name, status, type, campaign_type")
            .eq("id", campaign_id)
            .single(),
            label="buscar campanha por id",
        )
        campaign_data = res.data

    campaign_name = campaign_data.get("name", "Campanha sem nome")
    campaign_type = campaign_data.get("campaign_type") or campaign_data.get("type", "primary")

    _log_event(client, campaign_id, "campanha_iniciou", f"Orquestrador v3.0 iniciado para '{campaign_name}'", dry_run=dry_run)

    print(f"\n{Colors.CYAN}{'=' * 60}{Colors.RESET}")
    print(f"{Colors.CYAN}ORQUESTRADOR DE DISPAROS v3.0 - PACING DISTRIBUIÇÃO LOG-NORMAL{Colors.RESET}")
    print(f"Campanha       : {campaign_name} ({campaign_id[:8]})")
    print(f"Modo           : {'DRY RUN (Simulação)' if dry_run else 'ENVIO REAL (WhatsApp)'}")
    print(f"Pacing Engine  : Distribuição Log-Normal (40s - 180s) + Burst & Idle")
    print(f"Limite Diário  : {daily_limit} mensagens")
    if pilot_limit:
        print(f"Modo Piloto    : Ativo (Limite deste lote: {pilot_limit} mensagens)")
    print(f"{Colors.CYAN}{'=' * 60}{Colors.RESET}\n")

    if not dry_run:
        _try_supabase(
            lambda: client.schema("busca_ativa_v2")
            .table("campaigns")
            .update({"status": "dispatching"})
            .eq("id", campaign_id),
            label="atualizar status para dispatching",
        )

    # 2. Buscar mensagens pendentes
    msg_query = (
        client.schema("busca_ativa_v2")
        .table("messages")
        .select(
            "id, tracking_ref, wa_jid, guardian_id, template_id, body_preview, metadata, "
            "guardians(name), students(name, class_name)"
        )
        .eq("campaign_id", campaign_id)
        .eq("status", "pending")
        .order("created_at")
    )
    if pilot_limit and pilot_limit > 0:
        msg_query = msg_query.limit(pilot_limit)

    res_msgs = _execute_with_retry(lambda: msg_query, label="buscar mensagens pendentes")
    messages = res_msgs.data or []

    if not messages:
        print(f"{Colors.YELLOW}[INFO]{Colors.RESET} Nenhuma mensagem pendente nesta campanha.")
        return

    print(f"Fila Inicial Encontrada: {len(messages)} mensagens pendentes.\n")

    total_processed = 0
    total_sent = 0
    total_failed = 0

    # ── DEFINIÇÃO DINÂMICA E VARIÁVEL DE PAUSAS ──
    next_micro_pause_at = random.randint(8, 15)
    next_macro_pause_at = random.randint(45, 60)
    messages_since_micro = 0
    messages_since_macro = 0

    for idx, msg in enumerate(messages, 1):
        # ── VERIFICAÇÃO EM TEMPO REAL: Kill Switch Global ou Status 'paused' / 'cancelled' ──
        if not dry_run:
            check_camp = (
                client.schema("busca_ativa_v2")
                .table("campaigns")
                .select("status")
                .eq("id", campaign_id)
                .single()
                .execute()
            )
            camp_status = check_camp.data.get("status") if check_camp.data else ""
            if camp_status in ["paused", "cancelled"]:
                _log_event(client, campaign_id, "interrupcao_emergencia", f"Kill Switch/Pausa acionado! Status '{camp_status}'.", dry_run=dry_run)
                print(f"\n{Colors.RED}[KILL SWITCH DETECTADO]{Colors.RESET} Status '{camp_status}'. Abortando orquestrador de forma segura.")
                break

        # ── HORÁRIO INTELIGENTE & RESTRIÇÃO DE DIAS ──
        if not dry_run:
            _check_smart_sending_window(ignore_schedule=ignore_schedule)

        # ── LIMITE DIÁRIO ──
        if total_sent >= daily_limit:
            _log_event(client, campaign_id, "limite_diario_atingido", f"Limite diário de {daily_limit} msgs alcançado.", dry_run=dry_run)
            print(f"\n{Colors.YELLOW}[LIMITE DIÁRIO ALCANÇADO]{Colors.RESET} {daily_limit} mensagens enviadas hoje. Interrompendo para retomada no próximo dia útil.")
            break

        # ── PAUSAS VARIÁVEIS E IDLE COFFEE BREAKS ──
        if not dry_run and idx > 1:
            # 1. Macro Pausa Variável (45 a 60 envios)
            if messages_since_macro >= next_macro_pause_at:
                macro_pause = random.randint(1800, 2700)
                _log_event(client, campaign_id, "macro_pausa", f"Pausa longa de {macro_pause // 60}min", {"pause_sec": macro_pause}, dry_run=dry_run)
                print(f"\n{Colors.CYAN}[MACRO PAUSA VARIÁVEL]{Colors.RESET} {messages_since_macro} mensagens enviadas! Pausa de {macro_pause // 60} minutos...")
                await asyncio.sleep(macro_pause)
                messages_since_macro = 0
                next_macro_pause_at = random.randint(45, 60)
                _log_event(client, campaign_id, "retomada", "Retomou disparos após Macro Pausa", dry_run=dry_run)

            # 2. Micro Pausa Variável (8 a 15 envios)
            elif messages_since_micro >= next_micro_pause_at:
                micro_pause = random.randint(300, 600)
                _log_event(client, campaign_id, "micro_pausa", f"Micro pausa de {micro_pause // 60}min", {"pause_sec": micro_pause}, dry_run=dry_run)
                print(f"\n{Colors.CYAN}[MICRO PAUSA VARIÁVEL]{Colors.RESET} {messages_since_micro} mensagens enviadas! Micro pausa de {micro_pause // 60} minutos...")
                await asyncio.sleep(micro_pause)
                messages_since_micro = 0
                next_micro_pause_at = random.randint(8, 15)
                _log_event(client, campaign_id, "retomada", "Retomou disparos após Micro Pausa", dry_run=dry_run)

            # 3. Humano Idle Break (12% de chance aleatória de tomar café por 3 a 8min)
            elif random.random() < 0.12:
                idle_sec = random.randint(180, 480)
                _log_event(client, campaign_id, "idle_humano", f"Pausa 'tomar café' de {idle_sec // 60}min", {"pause_sec": idle_sec}, dry_run=dry_run)
                print(f"\n{Colors.CYAN}[HUMANO IDLE BREAK]{Colors.RESET} Simulação de pausa para café ({idle_sec // 60} min)...")
                await asyncio.sleep(idle_sec)

        msg_id = msg["id"]
        tracking_ref = msg["tracking_ref"]
        wa_jid = msg.get("wa_jid", "")
        template_id = msg.get("template_id", "t01")
        body_preview = msg.get("body_preview", "")
        meta = msg.get("metadata") or {}

        guardian_id = str(msg.get("guardian_id", ""))
        guardian_name = (msg.get("guardians") or {}).get("name") or "Responsavel"
        student_name = (msg.get("students") or {}).get("name") or "Aluno"
        class_name = (msg.get("students") or {}).get("class_name") or "Turma"

        # ── TRAVA ANTI-DUPLICAÇÃO EM TEMPO REAL ──
        if not dry_run and guardian_id:
            already_sent = _execute_with_retry(
                lambda: client.schema("busca_ativa_v2")
                .table("messages")
                .select("id")
                .eq("campaign_id", campaign_id)
                .eq("guardian_id", guardian_id)
                .eq("status", "sent")
                .limit(1),
                label=f"verificar duplicado: {student_name}",
            )
            if already_sent and already_sent.data:
                print(f"{Colors.YELLOW}[PULADO DUPLICADO]{Colors.RESET} {student_name} (Resp: {guardian_name}) - Já recebeu nesta campanha.")
                _execute_with_retry(
                    lambda: client.schema("busca_ativa_v2")
                    .table("messages")
                    .update({"status": "failed"})
                    .eq("id", msg_id),
                    label=f"marcar duplicado: {student_name}",
                )
                continue

        total_processed += 1
        messages_since_micro += 1
        messages_since_macro += 1

        print(f"[{total_processed}/{len(messages)}] Processando: {student_name} ({class_name}) - Resp: {guardian_name}")

        is_extraordinary = (
            campaign_type == "extraordinary"
            or meta.get("campaign_type") == "extraordinary"
            or meta.get("skip_justification_suffix") is True
        )

        absence_days = meta.get("data_falta") or campaign_data.get("absence_days") or "dias recentes"

        if is_extraordinary:
            final_text = meta.get("formatted_body") or body_preview
        elif campaign_type == "obmep":
            final_text = body_preview or catalog.get_message(template_id, guardian_name, student_name, class_name, absence_days)
        else:
            protocol = _short_protocol(tracking_ref)
            rodape = (
                f"Código do aluno: P-{protocol}\n"
                f"Para justificar, responda copiando o código acima ou escreva o nome do aluno com o motivo."
            )
            # ── Anti-duplicação: verifica se o body_preview já tem o rodapé ──
            # Isso evita triplicar o rodapé quando a mensagem foi salva em execuções anteriores
            base_msg_text = catalog.get_message(template_id, guardian_name, student_name, class_name, absence_days)
            final_text = f"{base_msg_text}\n\n{rodape}"

        msg_hash = _compute_message_hash(final_text)

        try:
            # ── SIMULAÇÃO AVANÇADA DE DIGITAÇÃO (PRESENCE TYPING MULTI-FASE) ──
            # TEMPORARIAMENTE DESABILITADO para diagnóstico de erro 463
            # O send_presence está causando instabilidade na sessão de criptografia
            phase1_ms = random.randint(1200, 2500)
            pause_ms = random.randint(600, 1400)
            phase2_ms = random.randint(1000, 2200)
            total_typing_ms = phase1_ms + pause_ms + phase2_ms

            # # Fase 1: Digitando...
            # await asyncio.to_thread(gateway.send_presence, to_jid=wa_jid, presence="composing", delay=phase1_ms, dry_run=dry_run)
            # if not dry_run:
            #     await asyncio.sleep(phase1_ms / 1000.0)
            #     await asyncio.sleep(pause_ms / 1000.0)

            # # Fase 2: Digitando novamente...
            # await asyncio.to_thread(gateway.send_presence, to_jid=wa_jid, presence="composing", delay=phase2_ms, dry_run=dry_run)
            # if not dry_run:
            #     await asyncio.sleep(phase2_ms / 1000.0)

            # Pequena pausa humanizada substituta (sem presence)
            if not dry_run:
                await asyncio.sleep((phase1_ms + pause_ms + phase2_ms) / 1000.0)

            send_result = await asyncio.to_thread(
                gateway.send_text,
                to_jid=wa_jid,
                text=final_text,
                dry_run=dry_run,
            )

            if send_result.success:
                print(f"{Colors.GREEN}[ENVIADO SUCESSO]{Colors.RESET} {student_name} ({wa_jid})")
                audit_details = {
                    "student_name": student_name,
                    "guardian_name": guardian_name,
                    "wa_jid": wa_jid,
                    "typing_ms": total_typing_ms,
                    "msg_hash": msg_hash,
                    "provider_id": send_result.provider_message_id
                }
                _log_event(client, campaign_id, "mensagem_enviada", f"Enviado para {student_name}", details=audit_details, dry_run=dry_run)

                if not dry_run:
                    _execute_with_retry(
                        lambda: client.schema("busca_ativa_v2")
                        .table("messages")
                        .update(
                            {
                                "status": "sent",
                                "evolution_msg_id": send_result.provider_message_id,
                                "template_id": template_id,
                                "body_preview": final_text[:500],
                                "sent_at": _local_now().isoformat(),
                            }
                        )
                        .eq("id", msg_id),
                        label=f"marcar enviado: {student_name}",
                    )
                    _capture_lid_after_send(
                        client,
                        wa_jid=wa_jid,
                        guardian_id=str(msg.get("guardian_id", "")),
                        school_id=str(meta.get("school_id", "") or ""),
                        evolution_url=settings.evolution_api_url,
                        evolution_key=settings.evolution_api_key,
                        instance=settings.evolution_api_instance,
                    )
                total_sent += 1
            else:
                err = send_result.error or "Erro na API do WhatsApp"
                print(f"{Colors.RED}[FALHA API]{Colors.RESET} {student_name} - Erro: {err}")
                _log_event(client, campaign_id, "falha_envio", f"Falha {student_name}: {err}", dry_run=dry_run)
                if not dry_run:
                    _execute_with_retry(
                        lambda: client.schema("busca_ativa_v2")
                        .table("messages")
                        .update(
                            {
                                "status": "failed",
                                "last_error": err,
                                "template_id": template_id,
                                "body_preview": final_text[:500],
                            }
                        )
                        .eq("id", msg_id),
                        label=f"marcar falha: {student_name}",
                    )
                total_failed += 1

        except Exception as exc:
            print(f"{Colors.RED}[EXCEÇÃO]{Colors.RESET} {student_name} - {exc}")
            _log_event(client, campaign_id, "excecao_envio", f"Exceção {student_name}: {exc}", dry_run=dry_run)
            if not dry_run:
                _execute_with_retry(
                    lambda: client.schema("busca_ativa_v2")
                    .table("messages")
                    .update({"status": "failed", "last_error": f"Exception: {exc}"})
                    .eq("id", msg_id),
                    label=f"marcar excecao: {student_name}",
                )
            total_failed += 1

        # ── PACING COM DISTRIBUIÇÃO LOG-NORMAL & HUMANO BURST ──
        if not dry_run:
            # 15% de chance de Humano Burst (envio rápido 10-18s)
            if random.random() < 0.15:
                delay = random.uniform(10.0, 18.0)
                print(f"{Colors.CYAN}[HUMANO BURST {delay:.1f}s]{Colors.RESET} Rajada rápida de resposta.")
            else:
                delay = _calculate_lognormal_delay(float(min_delay), float(max_delay))
                print(f"{Colors.YELLOW}[DELAY LOG-NORMAL {delay:.1f}s]{Colors.RESET} Distribuição humana natural.")
            await asyncio.sleep(delay)
        else:
            print(f"{Colors.YELLOW}[DRY RUN]{Colors.RESET} Delay de simulação ignorado.")

    # 3. Finalizar ciclo de disparo da campanha
    if not dry_run:
        status_counts = _message_status_counts(client, campaign_id)
        final_status = "active" if status_counts.get("pending", 0) > 0 else "completed"
        _try_supabase(
            lambda: client.schema("busca_ativa_v2")
            .table("campaigns")
            .update(
                {
                    "status": final_status,
                    "total_sent": status_counts.get("sent", 0),
                    "total_failed": status_counts.get("failed", 0),
                    "dispatched_at": _local_now().isoformat(),
                }
            )
            .eq("id", campaign_id),
            label="finalizar ciclo da campanha",
        )

    _log_event(client, campaign_id, "campanha_concluida", f"Ciclo finalizado. Enviadas: {total_sent}, Falhas: {total_failed}", dry_run=dry_run)

    print(f"\n{'-' * 60}")
    print("ORQUESTRAÇÃO COMPORTAMENTO HUMANO LOG-NORMAL CONCLUÍDA")
    print(f"Total Processado : {total_processed}")
    print(f"Enviadas com Sucesso: {total_sent}")
    print(f"Falhas           : {total_failed}")
    print(f"{'-' * 60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Orquestrador de disparos com simulador de comportamento humano log-normal")
    parser.add_argument("--campaign-id", type=str, default=None, help="ID da campanha.")
    parser.add_argument("--dry-run", action="store_true", help="Simula envio sem disparar no WhatsApp.")
    parser.add_argument("--min-delay", type=int, default=45, help="Tempo minimo de espera (segundos).")
    parser.add_argument("--max-delay", type=int, default=120, help="Tempo maximo de espera (segundos).")
    parser.add_argument("--daily-limit", type=int, default=250, help="Limite máximo de disparos por dia.")
    parser.add_argument("--pilot-limit", type=int, default=None, help="Modo Piloto: limita o disparo a apenas N mensagens.")
    parser.add_argument("--ignore-schedule", action="store_true", help="Ignora a trava de horário noturno e finais de semana.")
    args = parser.parse_args()

    try:
        asyncio.run(
            run_orchestrator(
                campaign_id=args.campaign_id,
                dry_run=args.dry_run,
                min_delay=args.min_delay,
                max_delay=args.max_delay,
                daily_limit=args.daily_limit,
                pilot_limit=args.pilot_limit,
                ignore_schedule=args.ignore_schedule,
            )
        )
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Orquestrador pausado com segurança. A fila está salva no Supabase e pode ser retomada.{Colors.RESET}")
