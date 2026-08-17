"""
scripts/verify_final_state.py
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
print("🔍 VERIFICAÇÃO FINAL DOS CADASTROS DOS ARTHURS NO SUPABASE")
print("=" * 80)

# 1. Deativate ghost student 776235d8-2dc0-461f-a12c-f49d3008ab65
try:
    client.schema("busca_ativa_v2").table("students").update({"active": False}).eq("id", "776235d8-2dc0-461f-a12c-f49d3008ab65").execute()
    print("✅ Registro duplicado DI-ARTHUR-9A desativado (active=False).")
except Exception as e:
    print(f"Nota ao desativar fantasma: {e}")

# 2. Consultar Alunos com ARTHUR no nome
res_a = client.schema("busca_ativa_v2").table("students").select("*").eq("school_id", SCHOOL_ID).ilike("name", "%ARTHUR GABRIEL%").execute()
print("\n📌 Alunos com 'ARTHUR GABRIEL' cadastrados na escola:")
for st in (res_a.data or []):
    st_id = st["id"]
    print(f"\n  • Aluno ID: {st_id}")
    print(f"    Nome:      {st.get('name')}")
    print(f"    RA:        {st.get('ra')}")
    print(f"    Turma:     {st.get('class_name')}")
    print(f"    Ativo:     {st.get('active')}")
    
    # Guardians
    res_sg = client.schema("busca_ativa_v2").table("student_guardians").select("is_primary, relationship, guardians(*)").eq("student_id", st_id).execute()
    for l in (res_sg.data or []):
        g = l.get("guardians") or {}
        print(f"      ➔ Responsável: '{g.get('name')}' | Tel: {g.get('phone_e164')} | Primário: {l.get('is_primary')} | Rel: {l.get('relationship')}")

# 3. Consultar especificamente a mãe de Arthur Gabriel Dias Piovesan (5514997456023)
print("\n📌 Registro do Responsável com telefone 5514997456023:")
res_g = client.schema("busca_ativa_v2").table("guardians").select("*").eq("phone_e164", "5514997456023").execute()
for g in (res_g.data or []):
    gid = g["id"]
    print(f"  • Guardian ID: {gid} | Nome: '{g.get('name')}' | Tel: {g.get('phone_e164')}")
    res_links = client.schema("busca_ativa_v2").table("student_guardians").select("is_primary, relationship, students(*)").eq("guardian_id", gid).execute()
    for link in (res_links.data or []):
        st = link.get("students") or {}
        print(f"    ➔ Vinculado ao Aluno: '{st.get('name')}' (RA: {st.get('ra')}, Turma: {st.get('class_name')})")

print("\n" + "=" * 80)
