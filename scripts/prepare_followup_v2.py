from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.infrastructure.supabase.repositories import SupabaseRepository


DEFAULT_SOURCE = (
    r"C:\Users\user\busca-ativa-inteligente\data\storage\campaigns"
    r"\followup_27_nao_respondentes.json"
)


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


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Follow-up source must be a JSON list")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare follow-up campaign in V2")
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--school-id", required=True)
    parser.add_argument("--campaign-name", default="Follow-up 27/04 - nao respondentes phone1")
    parser.add_argument("--absence-days", default="27/04/2026")
    args = parser.parse_args()

    load_dotenv(".env")
    rows = load_rows(Path(args.source))
    repository = SupabaseRepository()
    client = repository.client.schema("busca_ativa_v2")

    campaign = client.table("campaigns").insert(
        {
            "school_id": args.school_id,
            "name": args.campaign_name,
            "type": "absence",
            "absence_days": args.absence_days,
            "status": "draft",
        }
    ).execute().data[0]
    campaign_id = campaign["id"]

    prepared = []
    for row in rows:
        ra = str(row.get("ra") or "").strip()
        student_name = str(row.get("student_name") or "").strip()
        class_name = str(row.get("class_name") or "").strip()
        phone_e164 = "".join(ch for ch in str(row.get("phone1_e164") or "") if ch.isdigit())
        guardian_name = clean_text(row.get("guardian_name_phone1") or row.get("tipo_responsavel"))

        if not ra or not student_name or not phone_e164:
            raise ValueError(f"Invalid row: {row}")

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
        student_id = student_data[0]["id"] if student_data else client.table("students").select("id").eq("school_id", args.school_id).eq("ra", ra).limit(1).execute().data[0]["id"]

        client.table("student_guardians").update({"is_primary": False}).eq("student_id", student_id).execute()

        guardian_data = client.table("guardians").upsert(
            {
                "school_id": args.school_id,
                "name": guardian_name,
                "phone_e164": phone_e164,
                "wa_jid": f"{phone_e164}@s.whatsapp.net",
                "active": True,
            },
            on_conflict="school_id,phone_e164",
        ).execute().data
        guardian_id = guardian_data[0]["id"] if guardian_data else client.table("guardians").select("id").eq("school_id", args.school_id).eq("phone_e164", phone_e164).limit(1).execute().data[0]["id"]

        client.table("student_guardians").upsert(
            {
                "student_id": student_id,
                "guardian_id": guardian_id,
                "relationship": guardian_name,
                "is_primary": True,
            },
            on_conflict="student_id,guardian_id",
        ).execute()
        prepared.append({"ra": ra, "student_id": student_id, "student_name": student_name, "phone_e164": phone_e164})

    print(f"campaign_id={campaign_id}")
    print(f"prepared_count={len(prepared)}")
    for item in prepared:
        print(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
