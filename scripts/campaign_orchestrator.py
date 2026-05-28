"""
campaign_orchestrator.py - Fase 2: execucao controlada da campanha.

Consome a fila busca_ativa_v2.messages para a campanha mais recente em
status draft/dispatching, enviando apenas mensagens com status = pending.
Mensagens ja marcadas como sent nao sao reenviadas.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import random
import sys
import time
import requests
from datetime import datetime, timezone
from pathlib import Path
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



MIN_DELAY = 45
MAX_DELAY = 120


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


def _execute_with_retry(
    query_factory: Callable[[], Any],
    *,
    label: str,
    attempts: int = 5,
) -> Any:
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return query_factory().execute()
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts:
                break
            delay = 10 * attempt
            print(
                f"{Colors.YELLOW}[SUPABASE RETRY]{Colors.RESET} {label} falhou "
                f"({type(exc).__name__}: {exc}). Nova tentativa em {delay}s..."
            )
            time.sleep(delay)
    raise last_exc or RuntimeError(f"Falha desconhecida no Supabase: {label}")


def _try_supabase(query_factory: Callable[[], Any], *, label: str) -> bool:
    try:
        _execute_with_retry(query_factory, label=label)
        return True
    except Exception as exc:
        print(
            f"{Colors.YELLOW}[AVISO]{Colors.RESET} Nao consegui registrar no Supabase: "
            f"{label} ({type(exc).__name__}: {exc})"
        )
        return False


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
    """Após um envio bem-sucedido, tenta capturar o LID do contato nas mensagens
    inbound da conversa e salva no phone_identity_map para uso futuro.
    Falhas são ignoradas silenciosamente para não bloquear o fluxo.
    """
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

        # Verifica se já está mapeado
        existing = (
            client.schema("busca_ativa_v2")
            .table("phone_identity_map")
            .select("id")
            .eq("lid_jid", lid_jid)
            .limit(1)
            .execute()
        )
        if existing.data:
            return  # Já mapeado, sem necessidade de upsert

        # Salva o novo LID
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
        pass  # Não bloqueia o fluxo principal


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
        status = str(row.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


async def run_orchestrator(campaign_id: str | None, dry_run: bool = False) -> None:
    client = _build_supabase_client()
    gateway = EvolutionGateway()

    campaign_type = "primary"
    parent_campaign_id = None

    if not campaign_id:
        print(f"{Colors.CYAN}Buscando a campanha 'draft' ou 'dispatching' mais recente...{Colors.RESET}")
        res = _execute_with_retry(
            lambda: client.schema("busca_ativa_v2")
            .table("campaigns")
            .select("id, name, campaign_type, parent_campaign_id")
            .in_("status", ["draft", "dispatching"])
            .order("created_at", desc=True)
            .limit(1),
            label="buscar campanha",
        )
        if not res.data:
            print(f"{Colors.RED}Nenhuma campanha ativa encontrada na fila.{Colors.RESET}")
            return
        campaign_id = str(res.data[0]["id"])
        campaign_name = res.data[0]["name"]
        campaign_type = res.data[0].get("campaign_type") or "primary"
        parent_campaign_id = res.data[0].get("parent_campaign_id")
        print(f"{Colors.GREEN}Campanha selecionada: {campaign_name} ({campaign_id}){Colors.RESET}")
    else:
        res = _execute_with_retry(
            lambda: client.schema("busca_ativa_v2")
            .table("campaigns")
            .select("id, name, campaign_type, parent_campaign_id")
            .eq("id", campaign_id)
            .limit(1),
            label="buscar detalhes da campanha",
        )
        if not res.data:
            print(f"{Colors.RED}Campanha com ID {campaign_id} não encontrada.{Colors.RESET}")
            return
        campaign_name = res.data[0]["name"]
        campaign_type = res.data[0].get("campaign_type") or "primary"
        parent_campaign_id = res.data[0].get("parent_campaign_id")
        print(f"{Colors.GREEN}Usando campanha informada: {campaign_name} ({campaign_id}){Colors.RESET}")

    if campaign_type == "followup":
        catalog = FollowupMessageCatalog(school_name=settings.school_name)
        print(f"{Colors.GREEN}[INFO] Catálogo ativado: FollowupMessageCatalog (Tipo: {campaign_type}){Colors.RESET}")
    else:
        catalog = MessageCatalog(school_name=settings.school_name)
        print(f"{Colors.GREEN}[INFO] Catálogo ativado: MessageCatalog (Tipo: {campaign_type}){Colors.RESET}")

    if dry_run:
        print(f"{Colors.YELLOW}MODO DRY RUN ATIVADO - NENHUMA MENSAGEM REAL SERA ENVIADA{Colors.RESET}")

    if not dry_run:
        _try_supabase(
            lambda: client.schema("busca_ativa_v2")
            .table("campaigns")
            .update({"status": "dispatching"})
            .eq("id", campaign_id),
            label="marcar campanha como dispatching",
        )


    print(f"\n{'-' * 60}\nIniciando consumo da fila...\n{'-' * 60}")

    total_processed = 0
    total_sent = 0
    total_failed = 0

    while True:
        res = _execute_with_retry(
            lambda: client.schema("busca_ativa_v2")
            .table("messages")
            .select("id, wa_jid, tracking_ref, metadata, student_id, guardian_id, origin_message_id")
            .eq("campaign_id", campaign_id)
            .eq("status", "pending")
            .order("created_at", desc=False)
            .limit(1),
            label="buscar proxima mensagem pending",
        )

        if not res.data:
            print(f"\n{Colors.GREEN}Fila zerada! Nenhuma mensagem pending encontrada.{Colors.RESET}")
            break

        msg = res.data[0]
        msg_id = msg["id"]
        wa_jid = msg.get("wa_jid")
        tracking_ref = msg["tracking_ref"]
        origin_msg_id = msg.get("origin_message_id")
        meta = msg.get("metadata") or {}
        student_name = meta.get("nome_excel", "Aluno(a)")
        total_processed += 1

        # Revalidação em Tempo Real (Não enviar se já houver resposta no primeiro contato)
        if campaign_type == "followup" and parent_campaign_id:
            replied_check = _execute_with_retry(
                lambda: client.schema("busca_ativa_v2")
                .table("messages")
                .select("id")
                .eq("campaign_id", parent_campaign_id)
                .eq("student_id", msg["student_id"])
                .eq("status", "replied")
                .limit(1),
                label="revalidar resposta do primeiro contato",
            )
            if replied_check.data:
                print(f"{Colors.YELLOW}[SKIPPED]{Colors.RESET} Aluno {student_name} - Já respondeu no primeiro contato. Pulando follow-up.")
                if not dry_run:
                    _execute_with_retry(
                        lambda: client.schema("busca_ativa_v2")
                        .table("messages")
                        .update({
                            "status": "failed",
                            "last_error": "Ignorado: Aluno já respondeu no primeiro contato."
                        })
                        .eq("id", msg_id),
                        label="marcar mensagem como pulada/failed por resposta anterior",
                    )
                total_failed += 1
                continue

        if not wa_jid:
            print(f"{Colors.RED}[FALHA]{Colors.RESET} Aluno {student_name} - Sem contato/wa_jid cadastrado")
            if not dry_run:
                _execute_with_retry(
                    lambda: client.schema("busca_ativa_v2")
                    .table("messages")
                    .update({"status": "failed", "last_error": "Sem contato/wa_jid cadastrado"})
                    .eq("id", msg_id),
                    label="marcar mensagem sem contato como failed",
                )
            total_failed += 1
            continue

        unique_key = f"{msg['student_id']}|{msg['guardian_id']}"
        if isinstance(catalog, FollowupMessageCatalog):
            template_id, text_body = catalog.build_message(
                parent_name=meta.get("guardian_name", "Responsavel"),
                student_name=student_name,
                class_name=meta.get("turma", ""),
                absence_days=meta.get("data_falta", ""),
                campaign_id=campaign_id,
                unique_key=unique_key,
                campaign_name=campaign_name,
            )
        else:
            template_id, text_body = catalog.build_message(
                parent_name=meta.get("guardian_name", "Responsavel"),
                student_name=student_name,
                class_name=meta.get("turma", ""),
                absence_days=meta.get("data_falta", ""),
                campaign_id=campaign_id,
                unique_key=unique_key,
            )
        protocol = _short_protocol(tracking_ref)
        final_text = (
            f"{text_body}\n\n"
            f"Codigo do aluno: P-{protocol}\n"
            f"Para justificar, responda copiando o codigo acima ou escreva o nome completo do aluno junto com o motivo da falta.\n"
            f"Exemplo: P-{protocol} estava com febre."
        )

        try:
            send_result = await asyncio.to_thread(
                gateway.send_text,
                to_jid=wa_jid,
                text=final_text,
                dry_run=dry_run,
            )

            if send_result.success:
                print(f"{Colors.GREEN}[ENVIADO]{Colors.RESET} Aluno {student_name} (Prot: {protocol})")
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
                                "sent_at": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                        .eq("id", msg_id),
                        label=f"marcar enviado: {student_name}",
                    )
                    # Captura o LID do contato para enriquecer o phone_identity_map
                    _capture_lid_after_send(
                        client,
                        wa_jid=wa_jid,
                        guardian_id=str(msg.get("guardian_id", "")),
                        school_id=str(msg.get("metadata", {}).get("school_id", "") or ""),
                        evolution_url=settings.evolution_api_url,
                        evolution_key=settings.evolution_api_key,
                        instance=settings.evolution_api_instance,
                    )
                total_sent += 1
            else:
                err = send_result.error or "Erro desconhecido na Evolution API"
                print(f"{Colors.RED}[FALHA]{Colors.RESET} Aluno {student_name} - Erro API: {err}")
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
            print(f"{Colors.RED}[FALHA EXCECAO]{Colors.RESET} Aluno {student_name} - {exc}")
            if not dry_run:
                _execute_with_retry(
                    lambda: client.schema("busca_ativa_v2")
                    .table("messages")
                    .update({"status": "failed", "last_error": f"Exception: {exc}"})
                    .eq("id", msg_id),
                    label=f"marcar excecao: {student_name}",
                )
            total_failed += 1

        delay = random.randint(MIN_DELAY, MAX_DELAY)
        print(f"{Colors.YELLOW}[AGUARDANDO {delay}s...]{Colors.RESET} Pacing Anti-Ban ativo.")
        await asyncio.sleep(delay)

    if not dry_run:
        status_counts = _message_status_counts(client, campaign_id)
        _try_supabase(
            lambda: client.schema("busca_ativa_v2")
            .table("campaigns")
            .update(
                {
                    "status": "active",
                    "total_sent": status_counts.get("sent", 0),
                    "total_failed": status_counts.get("failed", 0),
                    "dispatched_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", campaign_id),
            label="finalizar campanha",
        )

    print(f"\n{'-' * 60}")
    print("ORQUESTRACAO CONCLUIDA")
    print(f"Total Processado : {total_processed}")
    print(f"Sucesso (Enviado): {total_sent}")
    print(f"Falhas           : {total_failed}")
    print(f"{'-' * 60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fase 2: orquestrador de disparo anti-ban")
    parser.add_argument("--campaign-id", type=str, default=None, help="ID da campanha. Se vazio, pega a mais recente.")
    parser.add_argument("--dry-run", action="store_true", help="Simula envio sem disparar na Evolution API.")
    args = parser.parse_args()

    try:
        asyncio.run(run_orchestrator(campaign_id=args.campaign_id, dry_run=args.dry_run))
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Orquestrador interrompido. A fila esta salva e pode ser retomada.{Colors.RESET}")
