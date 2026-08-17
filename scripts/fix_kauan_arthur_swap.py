"""
scripts/fix_kauan_arthur_swap.py

Script para desfazer o vínculo incorreto entre o telefone da mãe de Arthur Gabriel (14996850337)
e o aluno Kauan Fernando no Supabase.

Telefones Corretos:
- Arthur Gabriel (RA: 111193712) ➔ Mãe Carolina: 5514996850337
- Kauan Fernando (RA: 112910036) ➔ Mãe: 5514996332313
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform.startswith("win"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

from app.infrastructure.supabase.repositories import SupabaseRepository

SCHOOL_ID = "aac99735-32cb-4615-b2cb-0be315f18374"


def run_fix():
    print("=" * 70)
    print("🚀 DESFAZENDO TROCA DE TELEFONE: ARTHUR GABRIEL vs KAUAN FERNANDO")
    print("=" * 70)

    repo = SupabaseRepository(timeout=15.0, attempts=2)
    client = repo.client

    # 1. Buscar IDs corretos dos Alunos principais
    res_kauan = client.schema("busca_ativa_v2").table("students").select("id").eq("school_id", SCHOOL_ID).eq("ra", "112910036").execute()
    kauan_id = res_kauan.data[0]["id"] if res_kauan.data else None

    res_arthur = client.schema("busca_ativa_v2").table("students").select("id").eq("school_id", SCHOOL_ID).eq("ra", "111193712").execute()
    arthur_id = res_arthur.data[0]["id"] if res_arthur.data else None

    print(f"📌 Kauan Fernando ID: {kauan_id}")
    print(f"📌 Arthur Gabriel ID: {arthur_id}")

    # 2. Buscar Responsável com telefone da mãe do Arthur (5514996850337)
    res_g_arthur = client.schema("busca_ativa_v2").table("guardians").select("id").eq("school_id", SCHOOL_ID).eq("phone_e164", "5514996850337").execute()
    arthur_g_ids = [r["id"] for r in (res_g_arthur.data or [])]

    print(f"📌 IDs de Responsável com telefone 5514996850337 (Mãe Arthur): {arthur_g_ids}")

    # Remover QUALQUER vínculo entre os telefones de Arthur (5514996850337) e Kauan Fernando
    if kauan_id and arthur_g_ids:
        for gid in arthur_g_ids:
            res_del = client.schema("busca_ativa_v2").table("student_guardians").delete().eq("student_id", kauan_id).eq("guardian_id", gid).execute()
            print(f"✅ VÍNCULO REMOVIDO: Responsável {gid} (Mãe Arthur) desvinculado do aluno KAUAN FERNANDO!")

    # 3. Buscar Responsável com telefone da mãe do Kauan (5514996332313)
    res_g_kauan = client.schema("busca_ativa_v2").table("guardians").select("id").eq("school_id", SCHOOL_ID).eq("phone_e164", "5514996332313").execute()
    kauan_g_ids = [r["id"] for r in (res_g_kauan.data or [])]

    print(f"📌 IDs de Responsável com telefone 5514996332313 (Mãe Kauan): {kauan_g_ids}")

    # Garantir vínculo de Kauan (112910036) com Mãe Kauan (5514996332313)
    if kauan_id and kauan_g_ids:
        kg_id = kauan_g_ids[0]
        # Atualizar is_primary
        client.schema("busca_ativa_v2").table("student_guardians").update({"is_primary": True}).eq("student_id", kauan_id).eq("guardian_id", kg_id).execute()
        print(f"✅ VÍNCULO CONFIRMADO: Kauan Fernando vinculado exclusivamente à Mãe (Tel 5514996332313)")

    # Garantir vínculo de Arthur (111193712) com Mãe Arthur (5514996850337)
    if arthur_id and arthur_g_ids:
        ag_id = arthur_g_ids[0]
        client.schema("busca_ativa_v2").table("student_guardians").update({"is_primary": True}).eq("student_id", arthur_id).eq("guardian_id", ag_id).execute()
        print(f"✅ VÍNCULO CONFIRMADO: Arthur Gabriel vinculado exclusivamente à Mãe Carolina (Tel 5514996850337)")

    # 4. Limpar alunos duplicados fictícios/fantasma (ex: RA DI-ARTHUR-9A ou duplicados sem RA)
    ghost_students = client.schema("busca_ativa_v2").table("students").select("id, name, ra").eq("school_id", SCHOOL_ID).in_("ra", ["DI-ARTHUR-9A", "114854930"]).execute()
    for gs in (ghost_students.data or []):
        gid = gs["id"]
        client.schema("busca_ativa_v2").table("student_guardians").delete().eq("student_id", gid).execute()
        client.schema("busca_ativa_v2").table("students").delete().eq("id", gid).execute()
        print(f"🧹 ALUNO DUPLICADO REMOVIDO: {gs.get('name')} (RA: {gs.get('ra')})")

    print("\n" + "=" * 70)
    print("✨ CORREÇÃO CADASTRAL CONCLUÍDA COM SUCESSO!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_fix()
