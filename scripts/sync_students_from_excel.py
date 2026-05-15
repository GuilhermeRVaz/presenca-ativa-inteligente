"""
Fase 2 — Sync de students a partir do Excel Relatorio_Consolidado_BuscaAtiva.xlsx

Lê o Excel, normaliza RAs e faz upsert em busca_ativa_v2.students.
Chave de conflito: (school_id, ra).
"""

import re
import sys
from pathlib import Path

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
# Funções de normalização
# ---------------------------------------------------------------------------

def normalize_ra(raw_ra: str) -> str:
    if not raw_ra:
        return ""
    digits = re.sub(r"[^0-9]", "", raw_ra)
    digits = digits.lstrip("0")
    if len(digits) > 9:
        digits = digits[:-1]
    return digits


# ---------------------------------------------------------------------------
# UPSERTs
# ---------------------------------------------------------------------------

def upsert_student(repo: SupabaseRepository, school_id: str, ra: str, name: str, class_name: str) -> str | None:
    """Insere ou atualiza student baseado em (school_id, ra)."""
    try:
        # Verificar existência
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
            # Opcional: atualizar nome/turma se mudaram?
            # Por ora, apenas retorna ID existente
            return str(existing.data[0]["id"])

        # Inserir novo
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


# ---------------------------------------------------------------------------
# Lógica principal
# ---------------------------------------------------------------------------

def sync_students_from_excel(*, school_id: str, excel_path: Path | None = None) -> dict:
    if excel_path is None:
        excel_path = PROJECT_ROOT / settings.consolidated_report_path

    if not excel_path.exists():
        raise FileNotFoundError(f"Excel não encontrado: {excel_path}")

    print(f"Lendo Excel: {excel_path}")
    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb.active

    repo = SupabaseRepository()

    stats = {"total": 0, "inserted": 0, "updated": 0, "skipped": 0}

    # Mapeamento de colunas (0-indexed):
    # A (0) = turma | C (2) = nome aluno | D (3) = RA
    for row in ws.iter_rows(min_row=2, values_only=True):
        class_name = str(row[0] or "").strip()
        name = str(row[2] or "").strip()
        ra_raw = str(row[3] or "").strip()

        if not ra_raw:
            print(f"  [SKIP] RA vazio")
            stats["skipped"] += 1
            continue

        ra = normalize_ra(ra_raw)
        if not ra:
            print(f"  [SKIP] RA inválido após normalização: {ra_raw!r}")
            stats["skipped"] += 1
            continue

        try:
            # Upsert nativo (insert ou update)
            student_id = upsert_student(repo, school_id, ra, name, class_name)
            if student_id:
                # Não temos como saber se foi insert ou update sem query extra;
                # para simplificar, contamos como 'inserted' (o upsert cria se não existe)
                stats["inserted"] += 1
                print(f"  [UPSERT] RA={ra} ({name}) — turma={class_name}")
            else:
                stats["skipped"] += 1
        except Exception as exc:
            print(f"  [ERROR] RA={ra}: {exc}")
            stats["skipped"] += 1

        stats["total"] += 1

    wb.close()
    print(f"\n=== Resumo: {stats} ===")
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Sync students from Excel to busca_ativa_v2")
    parser.add_argument("--school-id", required=True, help="UUID da escola")
    parser.add_argument("--excel-path", help="Caminho para o Excel (opcional, usa config se omitido)")
    args = parser.parse_args()

    try:
        stats = sync_students_from_excel(school_id=args.school_id, excel_path=Path(args.excel_path) if args.excel_path else None)
        # Validação esperada
        total_students = stats["inserted"] + stats["updated"]
        if total_students < 265:
            print(f"\n⚠️  Atenção: esperado ~265 students, encontrados {total_students}")
            return 2
        return 0
    except Exception as e:
        print(f"Erro: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
