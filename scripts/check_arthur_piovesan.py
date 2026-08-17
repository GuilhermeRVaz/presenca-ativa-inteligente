"""
scripts/check_arthur_piovesan.py

Investigação dos alunos ARTHUR GABRIEL DIAS PIOVESAN e ARTHUR GABRIEL DA SILVA FERREIRA no Supabase,
além do telefone 5514997456023.
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
print("🔍 INVESTIGANDO SUPABASE: ARTHUR GABRIEL DIAS PIOVESAN vs ARTHUR GABRIEL DA SILVA FERREIRA")
print("=" * 70)

# 1. Alunos com ARTHUR GABRIEL
res_a = client.schema("busca_ativa_v2").table("students").select("id, name, ra, class_name").eq("school_id", SCHOOL_ID).ilike("name", "%ARTHUR GABRIEL%").execute()
arthur_rows = res_a.data or []
print("\n📌 Registros de Alunos com 'ARTHUR GABRIEL':")
for a in arthur_rows:
    st_id = a["id"]
    print(f"\n  • Aluno ID: {st_id} | Nome: {a.get('name')} | RA: {a.get('ra')} | Turma: {a.get('class_name')}")
    res_sg = client.schema("busca_ativa_v2").table("student_guardians").select("guardian_id, is_primary, relationship, guardians(id, name, phone_e164)").eq("student_id", st_id).execute()
    for sg in (res_sg.data or []):
        g = sg.get("guardians") or {}
        print(f"     ➔ Responsável ID: {g.get('id')} | Nome: {g.get('name')} | Tel: {g.get('phone_e164')} | Grau: {sg.get('relationship')} | Primário: {sg.get('is_primary')}")

# 2. Responsáveis com o telefone 5514997456023
phone = "5514997456023"
print(f"\n📌 Responsáveis no Supabase com o telefone {phone}:")
res_g = client.schema("busca_ativa_v2").table("guardians").select("id, name, phone_e164").eq("school_id", SCHOOL_ID).ilike("phone_e164", f"%{phone[-10:]}%").execute()
for g in (res_g.data or []):
    gid = g["id"]
    print(f"   • Guardian ID: {gid} | Nome: {g.get('name')} | Tel: {g.get('phone_e164')}")
    res_links = client.schema("busca_ativa_v2").table("student_guardians").select("is_primary, relationship, students(id, name, class_name, ra)").eq("guardian_id", gid).execute()
    for link in (res_links.data or []):
        st = link.get("students") or {}
        print(f"     ➔ Vinculado ao Aluno: {st.get('name')} (ID: {st.get('id')}, RA: {st.get('ra')}, Turma: {st.get('class_name')}) | Rel: {link.get('relationship')}")

print("\n" + "=" * 70)
