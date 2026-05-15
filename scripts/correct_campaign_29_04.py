"""
Correção: criar campanha APENAS com os 25 alunos faltosos do dia 29/04.
Lista fornecida pelo usuário.
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

# Lista de RAs fornecida (apenas uczniów que faltaram no dia 29/04)
RAS_FALTANTES_29_04 = [
    "115245009", "116706874", "120099515", "115084504", "116709129",
    "120161971", "120161928", "116002279", "115060499", "114503219",
    "114492629", "115867875", "114788129", "112374047", "115549949",
    "116100257", "114973151", "115061377", "112594573", "112594524",
    "114496997", "114722206", "114900397", "116083865",
]

def normalize_ra(raw_ra: str) -> str:
    digits = re.sub(r"[^0-9]", "", raw_ra)
    digits = digits.lstrip("0")
    if len(digits) > 9:
        digits = digits[:-1]
    return digits

def normalize_phone(raw_phone: str) -> str | None:
    if not raw_phone: return None
    digits = re.sub(r"\D", "", raw_phone)
    if len(digits) < 10: return None
    if not digits.startswith("55"): digits = "55" + digits
    return digits

def clean_text(value: Any) -> str:
    text = str(value or "").strip()
    replacements = {
        "mãe": "Mae/Responsavel", "mae": "Mae/Responsavel",
        "pai": "Pai/Responsavel", "vó": "Avo/Responsavel", "avo": "Avo/Responsavel",
        "tia": "Outro/Responsavel", "tio": "Outro/Responsavel",
        "responsavel": "Responsavel", "responsável": "Responsavel",
    }
    return replacements.get(text.lower(), text or "Responsavel")

def main():
    school_id = "aac99735-32cb-4615-b2cb-0be315f18374"
    repo = SupabaseRepository()
    client = repo.client.schema("busca_ativa_v2")

    # 1. Buscar student_ids e phones para os RAs da lista
    rows = []
    for ra_raw in RAS_FALTANTES_29_04:
        ra = normalize_ra(ra_raw)
        # Buscar student
        s_res = client.table("students").select("id, name, class_name").eq("school_id", school_id).eq("ra", ra).limit(1).execute()
        if not s_res.data:
            print(f"[WARN] RA {ra} não encontrado em students")
            continue
        student = s_res.data[0]
        student_id = student["id"]

        # Buscar guardian via student_guardians
        sg = client.table("student_guardians").select("guardians(id, name, phone_e164)").eq("student_id", student_id).limit(1).execute()
        if not sg.data:
            print(f"[WARN] RA {ra} sem guardian vinculado")
            continue
        guardian = sg.data[0].get("guardians")
        if not guardian:
            print(f"[WARN] RA {ra} sem guardian data")
            continue
        phone = guardian.get("phone_e164")
        if not phone:
            print(f"[WARN] RA {ra} sem phone")
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

    print(f"Total de alunos corretos para campanha: {len(rows)} (de {len(RAS_FALTANTES_29_04)} RAs)")

    # 2. Salvar JSON
    output_dir = PROJECT_ROOT / "data" / "storage" / "campaigns"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "followup_29_04_faltantes_CORRIGIDO.json"
    with open(output_path, "w", encoding="utf-8") as f:
        import json
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"JSON correto salvo em: {output_path}")

    # 3. Criar nova campanha (se quiser, pode sobrescrever a antiga ou criar nova)
    # Vamos criar nova com suffixe _CORRIGIDA
    campaign_name = "Busca Ativa 29/04 - Faltantes (CORRIGIDA)"
    absence_days = "29/04/2026"
    existing = client.table("campaigns").select("id").eq("school_id", school_id).eq("absence_days", absence_days).eq("name", campaign_name).limit(1).execute()
    if existing.data:
        print(f"Campanha {campaign_name} já existe: {existing.data[0]['id']}")
        campaign_id = existing.data[0]["id"]
    else:
        result = client.table("campaigns").insert({
            "school_id": school_id,
            "name": campaign_name,
            "absence_days": absence_days,
            "status": "draft",
        }).execute()
        campaign_id = result.data[0]["id"]
        print(f"Nova campanha criada: {campaign_id}")

    print(f"\nPara rodar a campanha correta:")
    print(f"python scripts/followup_campaign_v2.py --school-id {school_id} --campaign-id {campaign_id} --base-url http://127.0.0.1:8000 --real-send --confirm-campaign-id {campaign_id} --source \"data/storage/campaigns/followup_29_04_faltantes_CORRIGIDO.json\"")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
