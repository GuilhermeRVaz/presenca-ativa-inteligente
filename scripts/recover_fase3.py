"""
Recuperação Fase 3 — processa em lotes de 20 com pausa
"""

import re
import sys
import time
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
    if not raw_ra: return ""
    digits = re.sub(r"[^0-9]", "", raw_ra)
    digits = digits.lstrip("0")
    if len(digits) > 9: digits = digits[:-1]
    return digits

def normalize_phone(raw_phone: str) -> str | None:
    if not raw_phone: return None
    digits = re.sub(r"\D", "", raw_phone)
    if len(digits) < 10: return None
    if not digits.startswith("55"): digits = "55" + digits
    return digits

def clean_text(value: Any) -> str:
    text = str(value or "").strip()
    replacements = {"mãe":"Mae/Responsavel","mae":"Mae/Responsavel","pai":"Pai/Responsavel",
                    "vó":"Avo/Responsavel","avo":"Avo/Responsavel","tia":"Outro/Responsavel",
                    "tio":"Outro/Responsavel","primo":"Outro/Responsavel","prima":"Outro/Responsavel",
                    "responsavel":"Responsavel","responsável":"Responsavel"}
    return replacements.get(text.lower(), text or "Responsavel")

def find_legacy_contact(repo, ra):
    result = repo.client.schema("public").table("contacts").select(
        "telefone_1, telefone_2, telefone_3, responsavel_1, responsavel_2, responsavel_3"
    ).eq("ra", ra).limit(1).execute()
    return result.data[0] if result.data else None

def get_student_id(repo, school_id, ra):
    existing = repo.client.schema("busca_ativa_v2").table("students").select("id").eq("school_id", school_id).eq("ra", ra).limit(1).execute()
    return str(existing.data[0]["id"]) if existing.data else None

def get_guardian_id(repo, school_id, phone_e164):
    existing = repo.client.schema("busca_ativa_v2").table("guardians").select("id").eq("school_id", school_id).eq("phone_e164", phone_e164).limit(1).execute()
    return str(existing.data[0]["id"]) if existing.data else None

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--school-id", required=True)
    parser.add_argument("--excel-path")
    args = parser.parse_args()

    school_id = args.school_id
    excel_path = Path(args.excel_path) if args.excel_path else Path(settings.project_root) / settings.consolidated_report_path

    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb.active

    repo = SupabaseRepository()

    all_rows = list(ws.iter_rows(min_row=2, values_only=True))
    total = len(all_rows)
    print(f'Total Excel: {total}')

    batch_size = 20
    stats = {"processed":0, "no_contact":0, "no_phone":0, "guardians_created":0, "identities_created":0}

    for batch_start in range(0, total, batch_size):
        batch = all_rows[batch_start:batch_start+batch_size]
        print(f'\nLote {batch_start//batch_size + 1}/{(total+batch_size-1)//batch_size}')
        for row in batch:
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

            student_id = get_student_id(repo, school_id, ra)
            if not student_id:
                stats["processed"] += 1
                continue

            contact = find_legacy_contact(repo, ra)
            if not contact:
                stats["no_contact"] += 1
                stats["processed"] += 1
                continue

            phone_raw = contact.get("telefone_1") or contact.get("telefone_2") or contact.get("telefone_3")
            if not phone_raw:
                stats["no_phone"] += 1
                stats["processed"] += 1
                continue

            phone_e164 = normalize_phone(str(phone_raw))
            if not phone_e164:
                stats["no_phone"] += 1
                stats["processed"] += 1
                continue

            raw_resp = contact.get("responsavel_1") or contact.get("responsavel_2") or contact.get("responsavel_3") or "Responsavel"
            guardian_name = clean_text(raw_resp)

            guardian_id = get_guardian_id(repo, school_id, phone_e164)
            if not guardian_id:
                try:
                    data = {"school_id": school_id, "phone_e164": phone_e164, "name": guardian_name, "wa_jid": f"{phone_e164}@s.whatsapp.net"}
                    result = repo.client.schema("busca_ativa_v2").table("guardians").insert(data).execute()
                    guardian_id = result.data[0]["id"]
                    stats["guardians_created"] += 1
                except Exception:
                    guardian_id = None

            if guardian_id:
                try:
                    repo.client.schema("busca_ativa_v2").table("student_guardians").insert(
                        {"student_id": student_id, "guardian_id": guardian_id, "is_primary": True}
                    ).execute()
                except Exception:
                    pass
                try:
                    repo.client.schema("busca_ativa_v2").table("phone_identity_map").insert(
                        {"school_id": school_id, "phone_e164": phone_e164, "wa_jid": f"{phone_e164}@s.whatsapp.net", "guardian_id": guardian_id, "confidence": "HIGH", "source": "backfill"}
                    ).execute()
                    stats["identities_created"] += 1
                except Exception:
                    pass

            stats["processed"] += 1

        print(f'  Lote concluído. Stats: {stats}')
        time.sleep(2)

    wb.close()
    print(f'\n=== FINAL ===')
    print(f'Processados: {stats["processed"]}')
    print(f'Guardians criados: {stats["guardians_created"]}')
    print(f'Identities criadas: {stats["identities_created"]}')
    print(f'Sem contato: {stats["no_contact"]}, Sem telefone: {stats["no_phone"]}')
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
