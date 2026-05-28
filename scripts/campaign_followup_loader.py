"""
campaign_followup_loader.py — Fase 1.5: Carga e Preparação do Follow-up (Segundo Contato)

Responsabilidades:
  1. Localizar a campanha principal do dia desejado (status active/completed/dispatching).
  2. Identificar alunos que NÃO responderam (envio inicial de sucesso, mas sem status 'replied').
  3. Resolver o responsável secundário para cada um deles (is_primary = False, priorizando por data de criação).
  4. Criar/Reutilizar a campanha de follow-up em status 'draft' (com campaign_type = 'followup').
  5. Enfileirar as mensagens para os segundos contatos com status='pending'.
  6. Garantir idempotência completa (evitar enfileirar o mesmo aluno/responsável duas vezes).
  7. Rastrear o vínculo com parent_campaign_id e origin_message_id.

Uso:
  python scripts/campaign_followup_loader.py --day 4
  python scripts/campaign_followup_loader.py --day 4 --preview   # Apenas exibe métricas em formato texto/JSON
  python scripts/campaign_followup_loader.py --day 4 --dry-run   # Simula gravação
"""

import argparse
import hashlib
import sys
import json
from datetime import date, datetime, timezone
from pathlib import Path

# ─── Bootstrap do path para importar módulos do projeto ─────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.core.logging import logger

# ─── Constantes ──────────────────────────────────────────────────────────────
SUCCESS_STATUSES = {"sent", "delivered", "read"}


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    RESET = "\033[0m"


def _build_supabase_client():
    if not settings.supabase_url or not settings.supabase_key:
        raise RuntimeError("SUPABASE_URL e SUPABASE_KEY devem estar configurados no .env")
    from supabase import create_client
    from supabase.lib.client_options import SyncClientOptions
    options = SyncClientOptions(postgrest_client_timeout=60.0)
    return create_client(settings.supabase_url, settings.supabase_key, options=options)


import time
from typing import Any

def _execute_with_retry(operation_call: Any, *, operation: str, attempts: int = 5) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation_call()
        except Exception as exc:
            last_error = exc
            if attempt >= attempts:
                break
            time.sleep(2**attempt)
    raise RuntimeError(
        f"Supabase {operation} failed after {attempts} attempts: {last_error!r}"
    ) from last_error


def main():
    parser = argparse.ArgumentParser(description="Fase 1.5: Carga e Preparação do Follow-up (Segundo Contato)")
    parser.add_argument("--day", type=int, required=True, help="Dia do Excel/Campanha principal (Ex: 4)")
    parser.add_argument("--month", type=int, default=None, help="Mês da campanha. Padrão: mês atual")
    parser.add_argument("--year", type=int, default=None, help="Ano da campanha. Padrão: ano atual")
    parser.add_argument("--dry-run", action="store_true", help="Simula sem gravar dados no banco")
    parser.add_argument("--preview", action="store_true", help="Apenas exibe métricas e candidatos em formato de preview")
    args = parser.parse_args()

    today = date.today()
    month = args.month or today.month
    year = args.year or today.year
    school_id = settings.default_school_id

    if not school_id:
        print(f"{Colors.RED}[ERRO] DEFAULT_SCHOOL_ID não configurado no .env{Colors.RESET}")
        sys.exit(1)

    parent_campaign_name = f"Busca Ativa — Faltas dia {args.day:02d}/{month:02d}/{year}"
    absence_days = f"{args.day:02d}/{month:02d}/{year}"

    client = _build_supabase_client()

    print(f"\n{Colors.CYAN}{'='*60}")
    print(f" FAREJANDO CAMPANHA PRINCIPAL: {parent_campaign_name}")
    print(f"{'='*60}{Colors.RESET}")

    # 1. Localizar campanhas principais
    operation_find = lambda: (
        client.schema("busca_ativa_v2")
        .table("campaigns")
        .select("id, name, status")
        .eq("school_id", school_id)
        .eq("absence_days", absence_days)
        .or_("campaign_type.eq.primary,campaign_type.is.null")
        .order("created_at", desc=True)
        .execute()
    )
    parent_res = _execute_with_retry(operation_find, operation="find_parent_campaigns")

    if not parent_res.data:
        # Tenta pelo nome exato como fallback
        operation_fallback = lambda: (
            client.schema("busca_ativa_v2")
            .table("campaigns")
            .select("id, name, status")
            .eq("school_id", school_id)
            .eq("name", parent_campaign_name)
            .execute()
        )
        parent_res = _execute_with_retry(operation_fallback, operation="find_parent_campaign_fallback")

    if not parent_res.data:
        print(f"{Colors.RED}[ERRO] Campanha principal para {absence_days} não foi localizada.{Colors.RESET}")
        sys.exit(1)

    parent_campaign_ids = [c["id"] for c in parent_res.data]
    parent_campaign_names = [c["name"] for c in parent_res.data]

    if len(parent_campaign_ids) > 1:
        parent_campaign_id = ",".join(parent_campaign_ids)
        parent_campaign_name_str = " + ".join(parent_campaign_names)
        print(f"{Colors.GREEN}[INFO] AUTO-CONSOLIDAÇÃO: Encontradas {len(parent_campaign_ids)} campanhas principais para a data {absence_days}:{Colors.RESET}")
        for c in parent_res.data:
            print(f"   - {c['name']} ({c['id']})")
    else:
        parent_campaign_id = parent_campaign_ids[0]
        parent_campaign_name_str = parent_campaign_names[0]
        print(f"{Colors.GREEN}[OK] Campanha principal localizada: {parent_campaign_name_str} ({parent_campaign_id}){Colors.RESET}")

    # 2. Executar o relatório consolidado da campanha principal para obter a verdade operacional
    print(f"\n{Colors.CYAN}Gerando relatório consolidado oficial para obter não-respondentes...{Colors.RESET}")
    from scripts.consolidate_campaign_report import run_consolidate
    
    report_res = run_consolidate(campaign_id=parent_campaign_id, school_id=school_id)
    final_blocks = report_res.get("final_blocks", [])
    
    # Obter todas as mensagens da campanha principal para metadados/IDs
    operation_msgs = lambda: (
        client.schema("busca_ativa_v2")
        .table("messages")
        .select("id, status, student_id, guardian_id, wa_jid, metadata")
        .in_("campaign_id", parent_campaign_ids)
        .execute()
    )
    msg_res = _execute_with_retry(operation_msgs, operation="fetch_parent_messages")
    
    if not msg_res.data:
        print(f"{Colors.YELLOW}[AVISO] Nenhuma mensagem encontrada na campanha principal.{Colors.RESET}")
        sys.exit(0)

    msg_by_student = {m["student_id"]: m for m in msg_res.data}
    
    student_primary_messages = {}
    eligible_student_ids = set()
    total_sent = 0
    total_replied = 0

    for block in final_blocks:
        stu_id = block["student"]["id"]
        if block["summary"]["responded"]:
            total_replied += 1
            
        has_outbound = any(e.type == "OUTBOUND_INITIAL" for e in block["events"])
        if has_outbound:
            total_sent += 1
            if not block["summary"]["responded"]:
                eligible_student_ids.add(stu_id)
                if stu_id in msg_by_student:
                    student_primary_messages[stu_id] = msg_by_student[stu_id]

    print(f"\n{Colors.CYAN}Estatísticas Rápidas da Campanha Principal:{Colors.RESET}")
    print(f" - Total de contatos primários na fila: {len(msg_res.data)}")
    print(f" - Enviados com sucesso (primários)   : {total_sent}")
    print(f" - Respondidos                        : {total_replied}")
    print(f" - Elegíveis para follow-up           : {len(eligible_student_ids)}")

    students_with_secondary = []
    students_without_secondary = []

    # 3. Resolver contatos secundários para os elegíveis
    for stu_id in eligible_student_ids:
        orig_msg = student_primary_messages[stu_id]
        student_name = orig_msg.get("metadata", {}).get("nome_excel", "Aluno")

        # Buscar responsáveis secundários
        operation_sg = lambda: (
            client.schema("busca_ativa_v2")
            .table("student_guardians")
            .select("guardian_id, created_at, guardians(id, name, phone_e164, wa_jid)")
            .eq("student_id", stu_id)
            .eq("is_primary", False)
            .order("created_at", desc=False)
            .execute()
        )
        sg_res = _execute_with_retry(operation_sg, operation="fetch_secondary_guardian")

        if sg_res.data and sg_res.data[0].get("guardians"):
            guardian = sg_res.data[0]["guardians"]
            students_with_secondary.append((stu_id, orig_msg, guardian))
        else:
            students_without_secondary.append((stu_id, orig_msg))

    print(f" - Possuem segundo contato            : {len(students_with_secondary)}")
    print(f" - Não possuem segundo contato        : {len(students_without_secondary)}")

    # Se for modo PREVIEW, formata e printa JSON estruturado para o Streamlit ler
    if args.preview:
        preview_data = {
            "total_eligible": len(eligible_student_ids),
            "with_secondary": len(students_with_secondary),
            "without_secondary": len(students_without_secondary),
            "eligible_students": [
                {
                    "student_name": msg["metadata"].get("nome_excel", "Aluno(a)"),
                    "student_id": stu_id,
                    "primary_guardian": msg["metadata"].get("guardian_name", "Responsável Primário"),
                    "secondary_guardian": g["name"],
                    "secondary_phone": g["phone_e164"],
                }
                for stu_id, msg, g in students_with_secondary
            ],
            "no_secondary_students": [
                {
                    "student_name": msg["metadata"].get("nome_excel", "Aluno(a)"),
                    "student_id": stu_id,
                    "primary_guardian": msg["metadata"].get("guardian_name", "Responsável Primário"),
                }
                for stu_id, msg in students_without_secondary
            ]
        }
        
        print(f"\n{Colors.GREEN}=== CANDIDATOS DO SEGUNDO CONTATO (PREVIEW) ==={Colors.RESET}")
        for stu_id, msg, g in students_with_secondary:
            print(f" [ELEGIVEL] {msg['metadata'].get('nome_excel', 'Aluno')}: Contatar {g['name']} ({g['phone_e164']})")
        
        if students_without_secondary:
            print(f"\n{Colors.YELLOW}=== ALERTAS: ALUNOS SEM SEGUNDO CONTATO ==={Colors.RESET}")
            for stu_id, msg in students_without_secondary:
                print(f" [ALERT] {msg['metadata'].get('nome_excel', 'Aluno')}: Sem responsável secundário configurado.")

        print("\n__PREVIEW_JSON_START__")
        print(json.dumps(preview_data, ensure_ascii=False))
        print("__PREVIEW_JSON_END__")
        sys.exit(0)

    # 4. Executar carga real/dry-run
    followup_campaign_name = f"Follow-up — Faltas dia {args.day:02d}/{month:02d}/{year}"
    print(f"\n{Colors.CYAN}{'='*60}")
    print(f" PREPARANDO CAMPANHA DE FOLLOW-UP: {followup_campaign_name}")
    print(f" Mode: {'[DRY RUN] (sem gravacao)' if args.dry_run else '[PRODUCAO] (grava no banco)'}")
    print(f"{'='*60}{Colors.RESET}")

    followup_campaign_id = None
    if args.dry_run:
        fake_id = hashlib.md5(followup_campaign_name.encode()).hexdigest()
        followup_campaign_id = f"{fake_id[:8]}-{fake_id[8:12]}-{fake_id[12:16]}-{fake_id[16:20]}-{fake_id[20:32]}"
        print(f"{Colors.YELLOW}[DRY RUN] Campanha criada virtualmente: {followup_campaign_name} ({followup_campaign_id}){Colors.RESET}")
    else:
        # Criar ou Reutilizar campanha de follow-up
        operation_exist = lambda: (
            client.schema("busca_ativa_v2")
            .table("campaigns")
            .select("id")
            .eq("school_id", school_id)
            .eq("name", followup_campaign_name)
            .limit(1)
            .execute()
        )
        existing_followup = _execute_with_retry(operation_exist, operation="check_existing_followup_campaign")
        if existing_followup.data:
            followup_campaign_id = existing_followup.data[0]["id"]
            print(f"[{Colors.GREEN}OK{Colors.RESET}] Reutilizando campanha de follow-up existente ({followup_campaign_id})")
        else:
            operation_create = lambda: (
                client.schema("busca_ativa_v2")
                .table("campaigns")
                .insert({
                    "school_id": school_id,
                    "name": followup_campaign_name,
                    "type": "absence",
                    "campaign_type": "followup",
                    "parent_campaign_id": parent_campaign_ids[0],
                    "absence_days": absence_days,
                    "status": "draft",
                    "total_sent": 0,
                    "total_replied": 0,
                })
                .execute()
            )
            create_res = _execute_with_retry(operation_create, operation="create_followup_campaign")
            if not create_res.data:
                print(f"{Colors.RED}[ERRO] Falha ao criar campanha de follow-up no Supabase.{Colors.RESET}")
                sys.exit(1)
            followup_campaign_id = create_res.data[0]["id"]
            print(f"[{Colors.GREEN}OK{Colors.RESET}] Campanha de follow-up criada no Supabase ({followup_campaign_id})")

    enqueued_count = 0
    skipped_count = 0

    for idx, (stu_id, orig_msg, guardian) in enumerate(students_with_secondary, 1):
        student_name = orig_msg.get("metadata", {}).get("nome_excel", "Aluno")
        guardian_id = str(guardian["id"])
        guardian_name = str(guardian["name"])
        wa_jid = guardian.get("wa_jid") or f"{guardian['phone_e164']}@s.whatsapp.net"

        # Idempotência: verificar se já está enfileirado para a mesma campanha, student e wa_jid
        if not args.dry_run:
            operation_msg_exist = lambda: (
                client.schema("busca_ativa_v2")
                .table("messages")
                .select("id")
                .eq("campaign_id", followup_campaign_id)
                .eq("student_id", stu_id)
                .eq("wa_jid", wa_jid)
                .in_("status", ["pending", "sent", "delivered", "read", "replied"])
                .limit(1)
                .execute()
            )
            existing_msg = _execute_with_retry(operation_msg_exist, operation="check_existing_followup_message")
            if existing_msg.data:
                print(f" [{idx}/{len(students_with_secondary)}] [PULADO] {student_name} | Responsável {guardian_name} já enfileirado — pulando")
                skipped_count += 1
                continue

        tracking_ref = f"FOL{followup_campaign_id[:8]}-STU{stu_id[:8]}"
        print(f" [{idx}/{len(students_with_secondary)}] [FILA] {student_name} | Responsável {guardian_name} ({guardian['phone_e164']}) -> Fila")

        # Dados da mensagem
        meta = {
            "nome_excel": student_name,
            "guardian_name": guardian_name,
            "turma": orig_msg.get("metadata", {}).get("turma", ""),
            "data_falta": orig_msg.get("metadata", {}).get("data_falta", ""),
            "school_id": school_id,
            "is_followup": True,
        }

        row = {
            "school_id": school_id,
            "campaign_id": followup_campaign_id,
            "student_id": stu_id,
            "guardian_id": guardian_id,
            "tracking_ref": tracking_ref,
            "wa_jid": wa_jid,
            "template_id": "busca_ativa_v1_followup",
            "status": "pending",
            "origin_message_id": orig_msg["id"],
            "metadata": meta,
        }

        if not args.dry_run:
            operation_insert_msg = lambda: (
                client.schema("busca_ativa_v2").table("messages").insert(row).execute()
            )
            _execute_with_retry(operation_insert_msg, operation="enqueue_followup_message")

        enqueued_count += 1

    print(f"\n{Colors.GREEN}{'='*60}")
    print(" CARGA CONCLUÍDA COM SUCESSO!")
    print(f" - Mensagens Enfileiradas : {enqueued_count}")
    print(f" - Registros Pulados      : {skipped_count}")
    print(f"{'='*60}{Colors.RESET}\n")


if __name__ == "__main__":
    main()
