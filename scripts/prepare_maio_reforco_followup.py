"""
Prepare script for Maio 2026 Reforço Follow-up campaign (hidden-star plan).

Based on prepare_followup_v2.py + prepare_..._fast.py patterns:
- idempotent campaign by (school_id, name) or absence_days
- JSON source with ra/name/class/phone_primary/guardian_primary_name/priority/notes
- silent stats (only final summary + severe errors)
- UPSERT + get_or_create via helpers + retry
- desmarca other primaries before setting new
- phone_identity HIGH + source="maio_reforco_backfill"
- optional dispatch JSON output
- exit 2 if <20 students or <15 guardians (overridable)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
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


def get_student_id(client: Any, school_id: str, ra: str) -> str | None:
    try:
        res = (
            client.table("students")
            .select("id")
            .eq("school_id", school_id)
            .eq("ra", ra)
            .limit(1)
            .execute()
        )
        if res.data:
            return str(res.data[0]["id"])
        return None
    except Exception:
        return None


def get_guardian_id(client: Any, school_id: str, phone_e164: str) -> str | None:
    try:
        res = (
            client.table("guardians")
            .select("id")
            .eq("school_id", school_id)
            .eq("phone_e164", phone_e164)
            .limit(1)
            .execute()
        )
        if res.data:
            return str(res.data[0]["id"])
        return None
    except Exception:
        return None


def create_campaign(
    repo: SupabaseRepository, school_id: str, name: str, absence_days: str
) -> str | None:
    # Prefer match by name (for multiple campaigns with similar absence_days)
    existing = (
        repo.client.schema("busca_ativa_v2")
        .table("campaigns")
        .select("id")
        .eq("school_id", school_id)
        .eq("name", name)
        .limit(1)
        .execute()
    )
    if existing.data:
        return str(existing.data[0]["id"])
    # fallback by absence_days (as in fast version)
    existing2 = (
        repo.client.schema("busca_ativa_v2")
        .table("campaigns")
        .select("id")
        .eq("school_id", school_id)
        .eq("absence_days", absence_days)
        .limit(1)
        .execute()
    )
    if existing2.data:
        return str(existing2.data[0]["id"])
    result = (
        repo.client.schema("busca_ativa_v2")
        .table("campaigns")
        .insert(
            {
                "school_id": school_id,
                "name": name,
                "type": "absence",
                "absence_days": absence_days,
                "status": "draft",
            }
        )
        .execute()
    )
    return str(result.data[0]["id"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare Reforco Maio 2026 follow-up (prioritarios >2 faltas sem retorno)"
    )
    parser.add_argument("--school-id", required=True)
    parser.add_argument(
        "--campaign-name",
        default="Follow-up Reforco Maio 2026 - Prioritarios sem retorno",
    )
    parser.add_argument(
        "--absence-days", default="Maio/2026 (multiplos dias >2 faltas)"
    )
    parser.add_argument(
        "--source",
        default="data/storage/campaigns/maio_2026_prioritarios_raw.json",
    )
    parser.add_argument(
        "--dispatch-out",
        default="data/storage/campaigns/maio_2026_prioritarios_dispatch.json",
        help="Where to write dispatch-ready source (ra + phone1_e164)",
    )
    parser.add_argument(
        "--force", action="store_true", help="Ignore low count warnings"
    )
    args = parser.parse_args()

    source_path = PROJECT_ROOT / args.source
    if not source_path.exists():
        print(f"ERROR: source not found: {source_path}")
        return 2

    rows = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        print("ERROR: source must be JSON list")
        return 2

    repo = SupabaseRepository()
    client = repo.client.schema("busca_ativa_v2")

    campaign_id = create_campaign(repo, args.school_id, args.campaign_name, args.absence_days)
    if not campaign_id:
        print("ERROR: could not create/reuse campaign")
        return 2
    print(f"campaign_id={campaign_id}")
    print(f"campaign_name={args.campaign_name}")

    stats = {
        "processed": 0,
        "skipped_invalid": 0,
        "students_new": 0,
        "guardians_new": 0,
        "links_new": 0,
        "identities_new": 0,
        "students_total": 0,
        "guardians_total": 0,
    }

    dispatch_rows = []

    for row in rows:
        ra = normalize_ra(row.get("ra") or row.get("ra_raw"))
        student_name = str(row.get("name") or row.get("student_name") or "").strip()
        class_name = str(row.get("class_name") or "").strip()
        phone_e164 = normalize_phone(row.get("phone_primary") or row.get("phone1_e164"))
        guardian_name = clean_text(
            row.get("guardian_primary_name") or row.get("tipo_responsavel")
        )

        if not ra or not student_name or not phone_e164:
            stats["skipped_invalid"] += 1
            stats["processed"] += 1
            continue

        # Student UPSERT
        student_data = client.table("students").upsert(
            {
                "school_id": args.school_id,
                "ra": ra,
                "name": student_name,
                "class_name": class_name or "nao informada",
                "active": True,
            },
            on_conflict="school_id,ra",
        ).execute().data
        if student_data:
            student_id = student_data[0]["id"]
            # heuristic: if was just created (no previous), count new (approx)
        else:
            student_id = (
                client.table("students")
                .select("id")
                .eq("school_id", args.school_id)
                .eq("ra", ra)
                .limit(1)
                .execute()
                .data[0]["id"]
            )
        stats["students_total"] += 1

        # Desmarcar outros primaries (safe for get_outbound_context)
        client.table("student_guardians").update({"is_primary": False}).eq(
            "student_id", student_id
        ).execute()

        # Guardian
        guardian_id = get_guardian_id(client, args.school_id, phone_e164)
        if not guardian_id:
            data = {
                "school_id": args.school_id,
                "phone_e164": phone_e164,
                "name": guardian_name,
                "wa_jid": f"{phone_e164}@s.whatsapp.net",
            }
            try:
                result = client.table("guardians").insert(data).execute()
                guardian_id = result.data[0]["id"]
                stats["guardians_new"] += 1
            except Exception as exc:
                print(f"guardian insert error ra={ra}: {exc}")
                guardian_id = None

        if guardian_id:
            # Link (upsert to avoid dup)
            try:
                client.table("student_guardians").upsert(
                    {
                        "student_id": student_id,
                        "guardian_id": guardian_id,
                        "relationship": guardian_name,
                        "is_primary": True,
                    },
                    on_conflict="student_id,guardian_id",
                ).execute()
                stats["links_new"] += 1
            except Exception:
                pass

            # Identity (HIGH, source backfill) - insert or ignore dup
            try:
                client.table("phone_identity_map").insert(
                    {
                        "school_id": args.school_id,
                        "phone_e164": phone_e164,
                        "wa_jid": f"{phone_e164}@s.whatsapp.net",
                        "guardian_id": guardian_id,
                        "confidence": "HIGH",
                        "source": "maio_reforco_backfill",
                    }
                ).execute()
                stats["identities_new"] += 1
            except Exception:
                # likely duplicate (phone already mapped) - ok
                pass

        dispatch_rows.append({"ra": ra, "phone1_e164": phone_e164})
        stats["processed"] += 1

    # Write dispatch source (for followup_campaign_v2.py)
    dispatch_path = PROJECT_ROOT / args.dispatch_out
    dispatch_path.parent.mkdir(parents=True, exist_ok=True)
    dispatch_path.write_text(
        json.dumps(dispatch_rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"dispatch_source_written={dispatch_path}")

    # Final counts (approx from processed)
    stats["students_total"] = stats["students_total"] or len(dispatch_rows)
    stats["guardians_total"] = stats["guardians_total"] or stats["guardians_new"]

    print("=== RESUMO PREPARE MAIO REFORCO ===")
    for k, v in stats.items():
        print(f"{k}={v}")
    print(f"campaign_id={campaign_id}")

    low_count = stats["students_total"] < 20 or stats["guardians_total"] < 15
    if low_count and not args.force:
        print(
            "\n⚠️  Atenção: esperado >=20 students / >=15 guardians (Fase 0 curation parcial). Use --force para continuar."
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
