"""
Versão otimizada da Fase 3 — sem prints por linha (apenas resumo)
"""

import re
import sys
from pathlib import Path
from typing import Any

import openpyxl
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from app.core.config import settings
from app.infrastructure.supabase.repositories import SupabaseRepository

def normalize_ra(raw_ra: str) -> str:
    if not raw_ra:
        return ""
    digits = re.sub(r"[^0-9]", "", raw_ra)
    digits = digits.lstrip("0")
    if len(digits) > 9:
        digits = digits[:-1]
    return digits


def normalize_phone(raw_phone: str) -> str | None:
    if not raw_phone:
        return None
    digits = re.sub(r"\D", "", raw_phone)
    if len(digits) < 10:
        return None
    if not digits.startswith("55"):
        digits = "55" + digits
    return digits


def clean_text(value: Any) -> str:
    text = str(value or "").strip()
    replacements = {
        "mÃ£e": "Mae/Responsavel",
        "mãe": "Mae/Responsavel",
        "mae": "Mae/Responsavel",
        "pai": "Pai/Responsavel",
        "vÃ³": "Avo/Responsavel",
        "vó": "Avo/Responsavel",
        "avo": "Avo/Responsavel",
        "avó": "Avo/Responsavel",
        "responsavel": "Responsavel",
        "responsável": "Responsavel",
    }
    return replacements.get(text.lower(), text or "Responsavel")


def find_legacy_contact(repo: SupabaseRepository, ra: str) -> dict | None:
    result = (
        repo.client.schema("public")
        .table("contacts")
        .select("ra, telefone_1, telefone_2, telefone_3, responsavel_1, responsavel_2, responsavel_3")
        .eq("ra", ra)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_student_id(repo: SupabaseRepository, school_id: str, ra: str) -> str | None:
    def operation():
        return (
            repo.client.schema("busca_ativa_v2")
            .table("students")
            .select("id")
            .eq("school_id", school_id)
            .eq("ra", ra)
            .limit(1)
            .execute()
        )
    try:
        response = repo._execute_with_retry(operation, operation="get_student_id")
        if response.data:
            return str(response.data[0]["id"])
        return None
    except Exception:
        return None


def get_guardian_id(repo: SupabaseRepository, school_id: str, phone_e164: str) -> str | None:
    def operation():
        return (
            repo.client.schema("busca_ativa_v2")
            .table("guardians")
            .select("id")
            .eq("school_id", school_id)
            .eq("phone_e164", phone_e164)
            .limit(1)
            .execute()
        )
    try:
        response = repo._execute_with_retry(operation, operation="get_guardian_id")
        if response.data:
            return str(response.data[0]["id"])
        return None
    except Exception:
        return None


def create_campaign(repo: SupabaseRepository, school_id: str, name: str, absence_days: str) -> str | None:
    existing = (
        repo.client.schema("busca_ativa_v2")
        .table("campaigns")
        .select("id")
        .eq("school_id", school_id)
        .eq("absence_days", absence_days)
        .limit(1)
        .execute()
    )
    if existing.data:
        return str(existing.data[0]["id"])
    result = (
        repo.client.schema("busca_ativa_v2")
        .table("campaigns")
        .insert({"school_id": school_id, "name": name, "absence_days": absence_days, "status": "draft"})
        .execute()
    )
    return str(result.data[0]["id"])


def run_batch(*, school_id: str, campaign_id: str, excel_path: Path) -> dict:
    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb.active

    repo = SupabaseRepository()

    stats = {"processed": 0, "skipped_no_contact": 0, "skipped_no_phone": 0, "students": 0, "guardians": 0, "links": 0, "identities": 0}

    # Processar todas as linhas
    for row in ws.iter_rows(min_row=2, values_only=True):
        class_name = str(row[0] or "").strip()
        name_aluno = str(row[2] or "").strip()
        ra_raw = str(row[3] or "").strip()

        if not ra_raw:
            stats["processed"] += 1
            continue

        ra = normalize_ra(ra_raw)
        if not ra:
            stats["processed"] += 1
            continue

        # Garante student
        student_id = get_student_id(repo, school_id, ra)
        if not student_id:
            stats["processed"] += 1
            continue

        stats["students"] += 1

        # Buscar contato legado
        contact = find_legacy_contact(repo, ra)
        if not contact:
            stats["skipped_no_contact"] += 1
            stats["processed"] += 1
            continue

        phone_raw = contact.get("telefone_1") or contact.get("telefone_2") or contact.get("telefone_3")
        if not phone_raw:
            stats["skipped_no_phone"] += 1
            stats["processed"] += 1
            continue

        phone_e164 = normalize_phone(str(phone_raw))
        if not phone_e164:
            stats["skipped_no_phone"] += 1
            stats["processed"] += 1
            continue

        # Guardian
        raw_resp = contact.get("responsavel_1") or contact.get("responsavel_2") or contact.get("responsavel_3") or "Responsavel"
        guardian_name = clean_text(raw_resp)

        guardian_id = get_guardian_id(repo, school_id, phone_e164)
        if not guardian_id:
            # inserir
            data = {"school_id": school_id, "phone_e164": phone_e164, "name": guardian_name, "wa_jid": f"{phone_e164}@s.whatsapp.net"}
            try:
                result = repo.client.schema("busca_ativa_v2").table("guardians").insert(data).execute()
                guardian_id = result.data[0]["id"]
                stats["guardians"] += 1
            except Exception:
                guardian_id = None

        if guardian_id:
            # Link
            try:
                repo.client.schema("busca_ativa_v2").table("student_guardians").insert(
                    {"student_id": student_id, "guardian_id": guardian_id, "is_primary": True}
                ).execute()
                stats["links"] += 1
            except Exception:
                pass

            # Phone identity
            try:
                repo.client.schema("busca_ativa_v2").table("phone_identity_map").insert(
                    {"school_id": school_id, "phone_e164": phone_e164, "wa_jid": f"{phone_e164}@s.whatsapp.net", "guardian_id": guardian_id, "confidence": "HIGH", "source": "backfill"}
                ).execute()
                stats["identities"] += 1
            except Exception:
                pass

        stats["processed"] += 1

    wb.close()
    return stats


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--school-id", required=True)
    parser.add_argument("--campaign-name", required=True)
    parser.add_argument("--absence-days", required=True)
    parser.add_argument("--excel-path")
    args = parser.parse_args()

    school_id = args.school_id
    excel_path = Path(args.excel_path) if args.excel_path else Path(settings.project_root) / settings.consolidated_report_path

    # Criar campanha
    repo = SupabaseRepository()
    campaign_id = create_campaign(repo, school_id, args.campaign_name, args.absence_days)
    if not campaign_id:
        print("Falha ao criar campanha", file=sys.stderr)
        return 1

    # Executar batch
    stats = run_batch(school_id=school_id, campaign_id=campaign_id, excel_path=excel_path)

    print(f"Processados: {stats['processed']}")
    print(f"Students: {stats['students']}")
    print(f"Guardians criados: {stats['guardians']}")
    print(f"Links: {stats['links']}")
    print(f"Identities: {stats['identities']}")
    print(f"Sem contato: {stats['skipped_no_contact']}")
    print(f"Sem telefone: {stats['skipped_no_phone']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
