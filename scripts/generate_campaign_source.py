"""
Gerar JSON source para followup_campaign_v2.py a partir dos dados da campanha 29/04.
"""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client
from supabase.lib.client_options import SyncClientOptions

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from app.core.config import settings
from app.infrastructure.supabase.repositories import SupabaseRepository

def main():
    school_id = "aac99735-32cb-4615-b2cb-0be315f18374"
    campaign_name = "Busca Ativa 29/04 - Faltantes"

    repo = SupabaseRepository()
    client = repo.client.schema("busca_ativa_v2")

    # Buscar campanha
    camp = client.table("campaigns").select("id").eq("absence_days", "29/04/2026").limit(1).execute()
    if not camp.data:
        print("Campanha não encontrada!")
        return 1
    campaign_id = camp.data[0]["id"]
    print(f"Campanha: {campaign_id}")

    # Buscar todos os student_guardians da campanha, com dados do student e guardian
    # Primeiro, buscar student_ids da escola
    students_res = client.table("students").select("id, ra, name, class_name").eq("school_id", school_id).execute()
    student_ids = [s["id"] for s in students_res.data]
    print(f"Students da escola: {len(student_ids)}")

    # Buscar student_guardians desses students
    sg_res = client.table("student_guardians").select(
        "student_id, guardians(id, name, phone_e164)"
    ).in_("student_id", student_ids).execute()

    rows = []
    for sg in sg_res.data:
        student_id = sg["student_id"]
        guardian = sg.get("guardians")
        if not guardian:
            continue
        phone = guardian.get("phone_e164")
        if not phone:
            continue

        # Buscar student (RA)
        s_res = client.table("students").select("ra, name, class_name").eq("id", student_id).limit(1).execute()
        if not s_res.data:
            continue
        student = s_res.data[0]
        ra = student.get("ra", "")
        if not ra:
            continue

        rows.append({
            "ra": ra,
            "student_name": student.get("name", ""),
            "class_name": student.get("class_name", ""),
            "phone1_e164": phone,
            "guardian_name_phone1": guardian.get("name", "Responsavel"),
            "tipo_responsavel": None,
            "student_id": student_id,
            "guardian_id": guardian.get("id"),
        })

    print(f"Total de registros para campanha: {len(rows)}")

    # Salvar JSON
    output_dir = PROJECT_ROOT / "data" / "storage" / "campaigns"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "followup_29_04_faltantes.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    print(f"JSON salvo em: {output_path}")
    print(f"Formato: {len(rows)} registros com ra, phone1_e164, guardian_name_phone1")

    # Mostrar exemplo
    if rows:
        print("\nExemplo (primeiro):")
        print(json.dumps(rows[0], ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
