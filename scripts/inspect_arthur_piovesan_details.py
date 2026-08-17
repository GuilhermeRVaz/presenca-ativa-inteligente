"""
scripts/inspect_arthur_piovesan_details.py
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
repo = SupabaseRepository(timeout=15.0, attempts=2)
client = repo.client

print("=" * 80)
print("🔍 INSPEÇÃO DETALHADA DOS REGISTROS DE ARTHUR GABRIEL NO SUPABASE")
print("=" * 80)

# 1. Alunos com RA 114854930, 111193712 e DI-ARTHUR-9A
ras = ["114854930", "111193712", "DI-ARTHUR-9A"]
res_st = client.schema("busca_ativa_v2").table("students").select("*").in_("ra", ras).execute()
students = res_st.data or []

print(f"\n📌 Alunos encontrados com os RAs {ras}:")
for st in students:
    st_id = st["id"]
    print(f"\n  • Aluno ID: {st_id}")
    print(f"    - Nome:      {st.get('name')}")
    print(f"    - RA:        {st.get('ra')}")
    print(f"    - Turma:     {st.get('class_name')}")
    print(f"    - School ID: {st.get('school_id')}")
    
    # Responsáveis vinculados em student_guardians
    res_sg = client.schema("busca_ativa_v2").table("student_guardians").select("*, guardians(*)").eq("student_id", st_id).execute()
    links = res_sg.data or []
    print(f"    - Total Responsáveis vinculados: {len(links)}")
    for l in links:
        g = l.get("guardians") or {}
        print(f"      ➔ Guardian ID: {g.get('id')} | Nome: '{g.get('name')}' | Tel: {g.get('phone_e164')} | Primário: {l.get('is_primary')} | Rel: {l.get('relationship')}")

# 2. Guardian 9092c420-d006-4c3f-ae20-684f701cb73d (tel 5514997456023)
gid = "9092c420-d006-4c3f-ae20-684f701cb73d"
res_g = client.schema("busca_ativa_v2").table("guardians").select("*").eq("id", gid).execute()
print(f"\n📌 Guardian ID {gid}:")
print(res_g.data)

res_sg_g = client.schema("busca_ativa_v2").table("student_guardians").select("*, students(*)").eq("guardian_id", gid).execute()
print(f"📌 Vinculos em student_guardians para Guardian {gid}:")
for l in (res_sg_g.data or []):
    st = l.get("students") or {}
    print(f"  ➔ Student ID: {st.get('id')} | Name: '{st.get('name')}' | RA: {st.get('ra')}")

# 3. Verificar se o link em student_guardians entre 53a73ade-09e6-4cc1-bd1b-1f330eab8566 e 9092c420-d006-4c3f-ae20-684f701cb73d existe
res_link_check = client.schema("busca_ativa_v2").table("student_guardians").select("*").eq("student_id", "53a73ade-09e6-4cc1-bd1b-1f330eab8566").eq("guardian_id", gid).execute()
print(f"\n📌 Link especifico (Aluno 53a7... <-> Guardian 9092...):")
print(res_link_check.data)

print("\n" + "=" * 80)
