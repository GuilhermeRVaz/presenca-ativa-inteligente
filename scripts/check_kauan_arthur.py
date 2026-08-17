"""
scripts/check_kauan_arthur.py

Investigação da troca de telefones entre KAUAN FERNANDO e ARTHUR GABRIEL no Supabase.
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

print("=" * 70)
print("🔍 INVESTIGANDO SUPABASE: KAUAN FERNANDO vs ARTHUR GABRIEL")
print("=" * 70)

# 1. Aluno KAUAN
res_k = client.schema("busca_ativa_v2").table("students").select("id, name, ra, class_name").eq("school_id", SCHOOL_ID).ilike("name", "%KAUAN FERNANDO%").execute()
kauan_rows = res_k.data or []
print("\n📌 Registro Aluno KAUAN FERNANDO no Supabase:")
for k in kauan_rows:
    st_id = k["id"]
    print(f"   • ID: {st_id} | Nome: {k.get('name')} | RA: {k.get('ra')} | Turma: {k.get('class_name')}")
    res_sg = client.schema("busca_ativa_v2").table("student_guardians").select("guardian_id, is_primary, guardians(id, name, phone_e164)").eq("student_id", st_id).execute()
    for sg in (res_sg.data or []):
        g = sg.get("guardians") or {}
        print(f"     ➔ Responsável ID: {g.get('id')} | Nome: {g.get('name')} | Tel: {g.get('phone_e164')} | Primário: {sg.get('is_primary')}")

# 2. Aluno ARTHUR GABRIEL
res_a = client.schema("busca_ativa_v2").table("students").select("id, name, ra, class_name").eq("school_id", SCHOOL_ID).ilike("name", "%ARTHUR GABRIEL%").execute()
arthur_rows = res_a.data or []
print("\n📌 Registro Aluno ARTHUR GABRIEL no Supabase:")
for a in arthur_rows:
    st_id = a["id"]
    print(f"   • ID: {st_id} | Nome: {a.get('name')} | RA: {a.get('ra')} | Turma: {a.get('class_name')}")
    res_sg = client.schema("busca_ativa_v2").table("student_guardians").select("guardian_id, is_primary, guardians(id, name, phone_e164)").eq("student_id", st_id).execute()
    for sg in (res_sg.data or []):
        g = sg.get("guardians") or {}
        print(f"     ➔ Responsável ID: {g.get('id')} | Nome: {g.get('name')} | Tel: {g.get('phone_e164')} | Primário: {sg.get('is_primary')}")

# 3. Consulta de Guardians pelos Telefones
phones = ["5514996332313", "5514996850337"]
print("\n📌 Consulta de Responsáveis no Supabase pelos Telefones:")
for p in phones:
    res_g = client.schema("busca_ativa_v2").table("guardians").select("id, name, phone_e164").eq("school_id", SCHOOL_ID).eq("phone_e164", p).execute()
    g_list = res_g.data or []
    for g in g_list:
        gid = g["id"]
        print(f"   • Tel: {p} ➔ Guardian ID: {gid} | Nome: {g.get('name')}")
        res_links = client.schema("busca_ativa_v2").table("student_guardians").select("is_primary, students(id, name, class_name)").eq("guardian_id", gid).execute()
        for link in (res_links.data or []):
            st = link.get("students") or {}
            print(f"     ➔ Vinculado ao Aluno ID: {st.get('id')} | Nome: {st.get('name')} | Turma: {st.get('class_name')}")

print("\n" + "=" * 70)
