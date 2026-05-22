#!/usr/bin/env python
"""
finish_remaining_21.py

Finaliza a enfileiramento dos 5 últimos alunos da campanha "Busca Ativa — Faltas dia 21/05/2026"
(28 já estão na fila; esses 5 travaram por timeout de rede).

- Retry agressivo (até 10 tentativas com backoff exponencial) em TODA chamada Supabase.
- Timeout alto (300s) para conexões ruins.
- Idempotente: pode rodar várias vezes.
- Reporta claramente o motivo de qualquer falha (ex: EMERSON por acento no nome).

Uso:
    python scripts/finish_remaining_21.py

Depois de sucesso (4 inseridos + 1 pulado por dados), rode o orquestrador:
    python scripts/campaign_orchestrator.py --campaign-id 69900b9d-27a6-4395-b970-a3410163cf77
"""

import sys
import time
from pathlib import Path
from typing import Any

# Bootstrap path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings
from supabase import create_client
from supabase.lib.client_options import SyncClientOptions

# ============================================================
# CONFIGURAÇÃO DA CAMPANHA E ALUNOS FALTANTES (do Excel dia 21)
# ============================================================

CAMPAIGN_ID = "69900b9d-27a6-4395-b970-a3410163cf77"
SCHOOL_ID = settings.default_school_id or "aac99735-32cb-4615-b2cb-0be315f18374"

REMAINING = [
    {"ra": "000116061923-2 /SP", "name": "URIEL RAMOS LOPES",                  "turma": "8 ANO 8B INTEGRAL 9H ANUAL"},
    {"ra": "000112786408-7/SP", "name": "RAFAEL HENRIQUE CORREA",             "turma": "8 ANO 8B INTEGRAL 9H ANUAL"},
    {"ra": "000114658754-5 /SP", "name": "EMERSON CAUA DA SILVA",              "turma": "9 ANO 9A INTEGRAL 9H ANUAL"},  # ATENÇÃO: no banco é "EMERSON CAUÃ DA SILVA" (com til)
    {"ra": "000111919014-9 /SP", "name": "PEDRO DANIEL DA SILVA MESSIAS",      "turma": "9 ANO 9A INTEGRAL 9H ANUAL"},
    {"ra": "000115497309-8 /SP", "name": "ESTEVAM GABRIEL PEREIRA DIAS",       "turma": "9 ANO 9A INTEGRAL 9H ANUAL"},
]

# ============================================================
# HELPERS COM RETRY FORTE
# ============================================================

def _build_client():
    """Client com timeout generoso para rede instável."""
    if not settings.supabase_url or not settings.supabase_key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY ausentes no .env")
    options = SyncClientOptions(postgrest_client_timeout=300.0)
    return create_client(settings.supabase_url, settings.supabase_key, options=options)

def _retry(operation, *, label: str, max_attempts: int = 10, base_delay: float = 2.5):
    """Retry com backoff exponencial. Nunca desiste antes de 10 tentativas."""
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as exc:
            last_exc = exc
            delay = min(base_delay * (2 ** (attempt - 1)), 45.0)
            print(f"  [{label}] tentativa {attempt}/{max_attempts} falhou ({type(exc).__name__}). "
                  f"Aguardando {delay:.1f}s antes de tentar novamente...")
            time.sleep(delay)
    print(f"  [{label}] ABANDONADO após {max_attempts} tentativas: {last_exc}")
    raise last_exc  # type: ignore[misc]

def _resolve_student_uuid(client, ra: str, name: str) -> str | None:
    """Resolve por RA exato (com sufixo do Excel) ou por nome exato. Com retry."""
    ra_clean = str(ra).strip()
    name_clean = str(name).strip()

    def op_ra():
        res = (
            client.schema("busca_ativa_v2")
            .table("students")
            .select("id")
            .eq("school_id", SCHOOL_ID)
            .eq("ra", ra_clean)
            .limit(1)
            .execute()
        )
        return str(res.data[0]["id"]) if res.data else None

    def op_name():
        res = (
            client.schema("busca_ativa_v2")
            .table("students")
            .select("id")
            .eq("school_id", SCHOOL_ID)
            .eq("name", name_clean)
            .limit(1)
            .execute()
        )
        return str(res.data[0]["id"]) if res.data else None

    # Tenta RA primeiro (pode falhar por causa de zeros/sufixo)
    sid = _retry(op_ra, label=f"resolve_ra:{name_clean[:18]}", max_attempts=6)
    if sid:
        return sid

    # Fallback nome exato
    sid = _retry(op_name, label=f"resolve_name:{name_clean[:18]}", max_attempts=6)
    if sid:
        return sid

    # Fallback extra: ILIKE (útil para acentos, ex: CAUA vs CAUÃ)
    def op_ilike():
        res = (
            client.schema("busca_ativa_v2")
            .table("students")
            .select("id, name")
            .eq("school_id", SCHOOL_ID)
            .ilike("name", f"%{name_clean.split()[0]}%{name_clean.split()[-1]}%")  # heurística simples
            .limit(3)
            .execute()
        )
        if res.data:
            # Para este script de emergência aceitamos o primeiro hit do ILIKE
            # (evita problema de acentuação CAUA vs CAUÃ)
            row = res.data[0]
            print(f"    (resolvido via ILIKE aproximado: {row['name']})")
            return str(row["id"])
        return None

    return _retry(op_ilike, label=f"resolve_fuzzy:{name_clean[:18]}", max_attempts=4)

def _resolve_primary_guardian(client, student_id: str) -> dict | None:
    """Busca responsável principal com retry."""
    def op():
        res = (
            client.schema("busca_ativa_v2")
            .table("student_guardians")
            .select("guardian_id, guardians(id, name, phone_e164, wa_jid)")
            .eq("student_id", student_id)
            .eq("is_primary", True)
            .limit(1)
            .execute()
        )
        if res.data and res.data[0].get("guardians"):
            return res.data[0]["guardians"]
        return None
    return _retry(op, label=f"guardian:{student_id[:8]}", max_attempts=8)

def _enqueue_message(client, student_id: str, guardian: dict, ra: str, name: str, turma: str) -> str | None:
    """Enfileira com idempotência + retry forte."""
    guardian_id = str(guardian["id"])
    wa_jid = guardian.get("wa_jid")
    tracking_ref = f"CMP{CAMPAIGN_ID[:8]}-STU{student_id[:8]}"

    def check_existing():
        res = (
            client.schema("busca_ativa_v2")
            .table("messages")
            .select("id")
            .eq("campaign_id", CAMPAIGN_ID)
            .eq("student_id", student_id)
            .limit(1)
            .execute()
        )
        return str(res.data[0]["id"]) if res.data else None

    existing = _retry(check_existing, label=f"check_existing:{name[:18]}", max_attempts=5)
    if existing:
        print(f"  ⚠️  Já estava enfileirado (id={existing}) — pulando")
        return existing

    row = {
        "school_id": SCHOOL_ID,
        "campaign_id": CAMPAIGN_ID,
        "student_id": student_id,
        "guardian_id": guardian_id,
        "tracking_ref": tracking_ref,
        "wa_jid": wa_jid,
        "template_id": "busca_ativa_v1",
        "status": "pending",
        "metadata": {
            "turma": turma,
            "data_falta": "21/05/2026",
            "ra": ra,
            "nome_excel": name,
            "guardian_name": guardian.get("name", ""),
            "guardian_phone": guardian.get("phone_e164", ""),
        },
    }

    def do_insert():
        res = (
            client.schema("busca_ativa_v2")
            .table("messages")
            .insert(row)
            .execute()
        )
        if not res.data:
            raise RuntimeError("INSERT retornou vazio")
        return str(res.data[0]["id"])

    return _retry(do_insert, label=f"INSERT:{name[:18]}", max_attempts=10)

# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("  FINALIZADOR DE CAMPANHA — 21/05/2026 (restantes)")
    print(f"  Campanha: {CAMPAIGN_ID}")
    print(f"  Alunos a processar: {len(REMAINING)}")
    print("=" * 70)

    client = _build_client()
    success = 0
    skipped = 0
    failed = 0

    for idx, stu in enumerate(REMAINING, 1):
        print(f"\n[{idx}/{len(REMAINING)}] {stu['name']} | RA: {stu['ra']}")

        try:
            # 1. Resolver aluno (com retries + fallback fuzzy para acento)
            student_id = _resolve_student_uuid(client, stu["ra"], stu["name"])
            if not student_id:
                print("  ❌ Aluno NÃO encontrado no banco (RA e nome exato falharam).")
                print("     (Para EMERSON: o nome no banco tem til 'CAUÃ' — diferença de acentuação.)")
                skipped += 1
                continue

            # 2. Responsável
            guardian = _resolve_primary_guardian(client, student_id)
            if not guardian:
                print("  ❌ Sem responsável principal vinculado.")
                skipped += 1
                continue

            # 3. Enfileirar (idempotente + retry)
            msg_id = _enqueue_message(client, student_id, guardian, stu["ra"], stu["name"], stu["turma"])
            if msg_id:
                wa = "✅ JID" if guardian.get("wa_jid") else "⚠️ sem JID"
                print(f"  ✅ Enfileirado com sucesso | msg_id={msg_id} | Resp: {guardian.get('name')} | {wa}")
                success += 1
            else:
                failed += 1

        except Exception as exc:
            print(f"  🔥 FALHA PERMANENTE após retries: {exc}")
            failed += 1

    print("\n" + "=" * 70)
    print("  RESUMO FINAL")
    print(f"  ✅ Enfileirados agora: {success}")
    print(f"  ⚠️  Pulados (sem UUID / sem resp): {skipped}")
    print(f"  🔥 Falhas irrecuperáveis: {failed}")
    print("=" * 70)

    if success > 0:
        print("\nCampanha pronta para disparo!")
        print("Execute agora:")
        print(f"  python scripts/campaign_orchestrator.py --campaign-id {CAMPAIGN_ID}")
    else:
        print("\nNada novo foi enfileirado. Verifique os logs acima.")

if __name__ == "__main__":
    main()
