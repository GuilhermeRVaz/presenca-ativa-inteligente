"""
scripts/inspect_gabriella_akemi.py

Verifica o cadastro de GABRIELLA AKEMI FERREIRA (RA 114823676) e seus responsáveis no Supabase.
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
print("🔍 INSPEÇÃO: GABRIELLA AKEMI FERREIRA (RA 114823676)")
print("=" * 80)

# 1. Buscar aluna por RA ou Nome
res_st = client.schema("busca_ativa_v2").table("students").select("*").eq("school_id", SCHOOL_ID).or_("ra.eq.114823676,name.ilike.%GABRIELLA AKEMI%").execute()
students = res_st.data or []

print(f"\n📌 Alunas encontradas ({len(students)}):")
for st in students:
    st_id = st["id"]
    print(f"\n  • Aluna ID: {st_id}")
    print(f"    Nome:      {st.get('name')}")
    print(f"    RA:        {st.get('ra')}")
    print(f"    Turma:     {st.get('class_name')}")
    print(f"    Ativo:     {st.get('active')}")
    
    # Responsáveis vinculados
    res_sg = client.schema("busca_ativa_v2").table("student_guardians").select("is_primary, relationship, guardians(*)").eq("student_id", st_id).execute()
    links = res_sg.data or []
    print(f"    Total Responsáveis vinculados: {len(links)}")
    for l in links:
        g = l.get("guardians") or {}
        print(f"      ➔ Guardian ID: {g.get('id')} | Nome: '{g.get('name')}' | Tel: {g.get('phone_e164')} | JID: {g.get('wa_jid')} | Primário: {l.get('is_primary')} | Rel: {l.get('relationship')}")

# 2. Verificar se o telefone 14991374483 / 5514991374483 existe em guardians
phone_target = "5514991374483"
res_g = client.schema("busca_ativa_v2").table("guardians").select("*").ilike("phone_e164", "%991374483%").execute()
print(f"\n📌 Responsáveis encontrados com o telefone final 991374483 ({len(res_g.data or [])}):")
for g in (res_g.data or []):
    gid = g["id"]
    print(f"  • Guardian ID: {gid} | Nome: '{g.get('name')}' | Tel: {g.get('phone_e164')}")
    res_links = client.schema("busca_ativa_v2").table("student_guardians").select("is_primary, relationship, students(*)").eq("guardian_id", gid).execute()
    for link in (res_links.data or []):
        st = link.get("students") or {}
        print(f"    ➔ Vinculado a: '{st.get('name')}' (RA: {st.get('ra')}, Turma: {st.get('class_name')})")

print("\n" + "=" * 80)
