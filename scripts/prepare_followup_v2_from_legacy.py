"""
Fase 3 — Criar campanha busca ativa a partir de dados legados (public.contacts)

Fluxo:
1. Ler Excel (Relatorio_Consolidado_BuscaAtiva.xlsx) → lista de alunos (ra_raw, nome, turma)
2. Para cada aluno:
   - ra = normalize_ra(ra_raw)
   - buscar contato em public.contacts (legado) por RA
   - extrair telefone (prioridade: telefone_1 > telefone_2 > telefone_3)
   - normalizar telefone para E164
   - extrair nome do responsável (responsavel_1/2/3)
   - limpar nome via clean_text()
3. Criar campanha (status='draft', absence_days informado)
4. Para cada aluno com telefone válido:
   - UPSERT student
   - UPSERT guardian (unique por school_id+phone_e164)
   - link student_guardians
   - UPSERT phone_identity_map (phone_e164 → wa_jid)
5. Logar estatísticas.
"""

import re
import sys
from pathlib import Path
from typing import Any

import openpyxl
from dotenv import load_dotenv

# Ajustar path para importar módulos do projeto
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from app.core.config import settings
from app.infrastructure.supabase.repositories import SupabaseRepository

# ---------------------------------------------------------------------------
# Funções utilitárias
# ---------------------------------------------------------------------------

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
    """
    Reutiliza a lógica de prepare_followup_v2.py existente.
    Normaliza variações de 'mãe', 'pai', 'avó', etc.
    """
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


# ---------------------------------------------------------------------------
# Acesso ao legado (public.contacts)
# ---------------------------------------------------------------------------

def find_legacy_contact(ra: str) -> dict | None:
    """
    Busca contato no legado (public.contacts) pelo RA.
    Retorna dict com campos: telefone_1, telefone_2, telefone_3, responsavel_1, responsavel_2, responsavel_3
    """
    repo = SupabaseRepository()
    result = (
        repo.client.schema("public")
        .table("contacts")
        .select("ra, nome_aluno, telefone_1, telefone_2, telefone_3, responsavel_1, responsavel_2, responsavel_3")
        .eq("ra", ra)
        .limit(1)
        .execute()
    )
    if result.data:
        return result.data[0]
    return None


# ---------------------------------------------------------------------------
# UPSERTs no novo schema
# ---------------------------------------------------------------------------

def upsert_student(repo: SupabaseRepository, school_id: str, ra: str, name: str, class_name: str) -> str | None:
    try:
        existing = (
            repo.client.schema("busca_ativa_v2")
            .table("students")
            .select("id")
            .eq("school_id", school_id)
            .eq("ra", ra)
            .limit(1)
            .execute()
        )
        if existing.data:
            return str(existing.data[0]["id"])

        data = {"school_id": school_id, "ra": ra, "name": name, "class_name": class_name}
        result = (
            repo.client.schema("busca_ativa_v2")
            .table("students")
            .insert(data)
            .execute()
        )
        if result.data:
            return str(result.data[0]["id"])
        return None
    except Exception as exc:
        print(f"    [ERROR upsert_student] RA={ra}: {exc}")
        return None


def upsert_guardian(repo: SupabaseRepository, school_id: str, phone_e164: str, guardian_name: str) -> str | None:
    try:
        existing = (
            repo.client.schema("busca_ativa_v2")
            .table("guardians")
            .select("id")
            .eq("school_id", school_id)
            .eq("phone_e164", phone_e164)
            .limit(1)
            .execute()
        )
        if existing.data:
            return str(existing.data[0]["id"])

        data = {"school_id": school_id, "phone_e164": phone_e164, "name": guardian_name, "wa_jid": f"{phone_e164}@s.whatsapp.net"}
        result = (
            repo.client.schema("busca_ativa_v2")
            .table("guardians")
            .insert(data)
            .execute()
        )
        if result.data:
            return str(result.data[0]["id"])
        return None
    except Exception as exc:
        print(f"    [ERROR upsert_guardian] phone={phone_e164}: {exc}")
        return None


def upsert_guardian(repo: SupabaseRepository, school_id: str, phone_e164: str, guardian_name: str) -> str | None:
    try:
        data = {"school_id": school_id, "phone_e164": phone_e164, "name": guardian_name, "wa_jid": f"{phone_e164}@s.whatsapp.net"}
        result = (
            repo.client.schema("busca_ativa_v2")
            .table("guardians")
            .upsert(data, on_conflict="school_id,phone_e164")
            .execute()
        )
        if result.data:
            return str(result.data[0]["id"])
        return None
    except Exception as exc:
        print(f"    [ERROR upsert_guardian] phone={phone_e164}: {exc}")
        return None


def link_student_guardian(repo: SupabaseRepository, student_id: str, guardian_id: str) -> bool:
    try:
        repo.client.schema("busca_ativa_v2").table("student_guardians").upsert(
            {"student_id": student_id, "guardian_id": guardian_id, "is_primary": True},
            on_conflict="student_id,guardian_id"
        ).execute()
        return True
    except Exception as exc:
        print(f"    [ERROR link] student={student_id} guardian={guardian_id}: {exc}")
        return False


def upsert_phone_identity(repo: SupabaseRepository, school_id: str, phone_e164: str, guardian_id: str) -> bool:
    try:
        # Verificar existência
        existing = (
            repo.client.schema("busca_ativa_v2")
            .table("phone_identity_map")
            .select("id")
            .eq("school_id", school_id)
            .eq("phone_e164", phone_e164)
            .limit(1)
            .execute()
        )
        if existing.data:
            return True  # já existe

        data = {
            "school_id": school_id,
            "phone_e164": phone_e164,
            "wa_jid": f"{phone_e164}@s.whatsapp.net",
            "guardian_id": guardian_id,
            "confidence": "HIGH",
            "source": "backfill",
        }
        repo.client.schema("busca_ativa_v2").table("phone_identity_map").insert(data).execute()
        return True
    except Exception as exc:
        print(f"    [ERROR phone_identity] phone={phone_e164}: {exc}")
        return False


def create_campaign(repo: SupabaseRepository, school_id: str, name: str, absence_days: str) -> str | None:
    """Cria campanha em draft se não existir com mesmo absence_days."""
    try:
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
            print(f"  [CAMPAIGN EXISTS] absence_days={absence_days} id={existing.data[0]['id']}")
            return str(existing.data[0]["id"])

        result = (
            repo.client.schema("busca_ativa_v2")
            .table("campaigns")
            .insert({
                "school_id": school_id,
                "name": name,
                "absence_days": absence_days,
                "status": "draft",
            })
            .execute()
        )
        cid = str(result.data[0]["id"])
        print(f"  [CAMPAIGN CREATED] id={cid} name={name}")
        return cid
    except Exception as exc:
        print(f"  [ERROR create_campaign] {exc}")
        return None


# ---------------------------------------------------------------------------
# Processamento principal
# ---------------------------------------------------------------------------

def prepare_followup_from_legacy(*, school_id: str, campaign_name: str, absence_days: str, excel_path: Path | None = None) -> dict:
    if excel_path is None:
        excel_path = PROJECT_ROOT / settings.consolidated_report_path

    if not excel_path.exists():
        raise FileNotFoundError(f"Excel não encontrado: {excel_path}")

    print(f"Lendo Excel: {excel_path}")
    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb.active

    repo = SupabaseRepository()

    stats = {
        "total_excel": 0,
        "found_in_legacy": 0,
        "missing_contact": 0,
        "missing_phone": 0,
        "students_created": 0,
        "guardians_created": 0,
        "links_created": 0,
        "identities_created": 0,
    }

    # Criar campanha
    campaign_id = create_campaign(repo, school_id, campaign_name, absence_days)
    if not campaign_id:
        raise RuntimeError("Falha ao criar campanha")

    # Processar cada linha do Excel
    for row in ws.iter_rows(min_row=2, values_only=True):
        class_name = str(row[0] or "").strip()
        name_aluno = str(row[2] or "").strip()
        ra_raw = str(row[3] or "").strip()

        if not ra_raw:
            print(f"  [SKIP] RA vazio — {name_aluno}")
            stats["total_excel"] += 1
            continue

        ra = normalize_ra(ra_raw)
        if not ra:
            print(f"  [SKIP] RA inválido: {ra_raw!r} — {name_aluno}")
            stats["total_excel"] += 1
            continue

        # Buscar no legado
        contact = find_legacy_contact(ra)
        if not contact:
            print(f"  [NO CONTACT] RA={ra} ({name_aluno}) não encontrado em public.contacts")
            stats["missing_contact"] += 1
            stats["total_excel"] += 1
            continue

        stats["found_in_legacy"] += 1

        # Selecionar telefone (prioridade: 1 > 2 > 3)
        phone_raw = contact.get("telefone_1") or contact.get("telefone_2") or contact.get("telefone_3")
        if not phone_raw:
            print(f"  [NO PHONE] RA={ra} ({name_aluno}) — contato sem telefone")
            stats["missing_phone"] += 1
            stats["total_excel"] += 1
            continue

        phone_e164 = normalize_phone(str(phone_raw))
        if not phone_e164:
            print(f"  [INVALID PHONE] RA={ra} ({name_aluno}) — phone_raw={phone_raw!r}")
            stats["missing_phone"] += 1
            stats["total_excel"] += 1
            continue

        # Nome do responsável
        raw_resp = contact.get("responsavel_1") or contact.get("responsavel_2") or contact.get("responsavel_3") or "Responsavel"
        guardian_name = clean_text(str(raw_resp))

        # UPSERT student
        student_id = upsert_student(repo, school_id, ra, name_aluno, class_name)
        if not student_id:
            stats["total_excel"] += 1
            continue

        # UPSERT guardian
        guardian_id = upsert_guardian(repo, school_id, phone_e164, guardian_name)
        if not guardian_id:
            stats["total_excel"] += 1
            continue

        # Link
        if link_student_guardian(repo, student_id, guardian_id):
            stats["links_created"] += 1

        # Phone identity map
        if upsert_phone_identity(repo, school_id, phone_e164, guardian_id):
            stats["identities_created"] += 1

        # Contadores
        if student_id and guardian_id:
            # Só conta como criado se realmente inseriu (não era existente)
            # Para simplificar, assumimos que upsert_student/guardian retornam id sempre
            # Mas não sabemos se foi insert ou get. Vamos assumir inserts como 'created'.
            # Em produção, seria mais preciso checar existência antes.
            pass

        stats["total_excel"] += 1
        print(f"  [OK] RA={ra} {name_aluno} | phone={phone_e164} guardian={guardian_name}")

    wb.close()

    # Contagem final
    students_count = (
        repo.client.schema("busca_ativa_v2")
        .table("students")
        .select("count", count="exact")
        .execute()
    )
    guardians_count = (
        repo.client.schema("busca_ativa_v2")
        .table("guardians")
        .select("count", count="exact")
        .execute()
    )

    stats["students_total"] = students_count.count
    stats["guardians_total"] = guardians_count.count
    stats["campaign_id"] = campaign_id

    print(f"\n=== RESULTADO ===")
    print(f"Excel processado: {stats['total_excel']}")
    print(f"Encontrados no legado: {stats['found_in_legacy']}")
    print(f"Sem contato (RA não existe): {stats['missing_contact']}")
    print(f"Sem telefone válido: {stats['missing_phone']}")
    print(f"Students no banco: {students_count.count}")
    print(f"Guardians no banco: {guardians_count.count}")
    print(f"Campanha criada: {campaign_id}")

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Prepara campanha follow-up v2 a partir de dados legados")
    parser.add_argument("--school-id", required=True, help="UUID da escola")
    parser.add_argument("--campaign-name", required=True, help="Nome da campanha")
    parser.add_argument("--absence-days", required=True, help="Dia de ausência (ex: 29/04/2026)")
    parser.add_argument("--excel-path", help="Caminho para Excel (opcional)")
    args = parser.parse_args()

    try:
        stats = prepare_followup_from_legacy(
            school_id=args.school_id,
            campaign_name=args.campaign_name,
            absence_days=args.absence_days,
            excel_path=Path(args.excel_path) if args.excel_path else None,
        )
        # Validações esperadas
        if stats["students_total"] < 240:
            print(f"\n⚠️  Atenção: esperado >=240 students, encontrados {stats['students_total']}")
            return 2
        if stats["guardians_total"] < 240:
            print(f"\n⚠️  Atenção: esperado >=240 guardians, encontrados {stats['guardians_total']}")
            return 2
        return 0
    except Exception as e:
        print(f"Erro: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
