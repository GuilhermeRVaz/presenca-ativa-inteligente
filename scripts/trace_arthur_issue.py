"""
scripts/trace_arthur_issue.py
"""
import sys
import json
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
print("🔍 RASTREAMENTO DO ERRO DE CADASTRO ARTHUR GABRIEL DIAS PIOVESAN")
print("=" * 80)

# 1. Inspect Guardian 9092c420-d006-4c3f-ae20-684f701cb73d (tel 5514997456023)
gid = "9092c420-d006-4c3f-ae20-684f701cb73d"
res_g = client.schema("busca_ativa_v2").table("guardians").select("*").eq("id", gid).execute()
print("\n📌 Guardian 9092c420-d006-4c3f-ae20-684f701cb73d:")
print(res_g.data)

res_sg = client.schema("busca_ativa_v2").table("student_guardians").select("*, students(*)").eq("guardian_id", gid).execute()
print("\n📌 Vinculos em student_guardians para o Guardian 9092c420-d006-4c3f-ae20-684f701cb73d:")
for link in (res_sg.data or []):
    st = link.get("students") or {}
    print(f"  • Student ID: {st.get('id')} | Name: {st.get('name')} | RA: {st.get('ra')} | Class: {st.get('class_name')}")

# 2. Check all student_guardians links for students named ARTHUR GABRIEL
print("\n📌 Alunos com 'ARTHUR' e seus vinculos:")
res_a = client.schema("busca_ativa_v2").table("students").select("*").eq("school_id", SCHOOL_ID).ilike("name", "%ARTHUR%").execute()
for st in (res_a.data or []):
    st_id = st["id"]
    print(f"\n  • Aluno ID: {st_id} | Nome: '{st.get('name')}' | RA: {st.get('ra')} | Turma: {st.get('class_name')}")
    res_links = client.schema("busca_ativa_v2").table("student_guardians").select("is_primary, relationship, guardians(*)").eq("student_id", st_id).execute()
    for l in (res_links.data or []):
        g = l.get("guardians") or {}
        print(f"     ➔ Guardian ID: {g.get('id')} | Nome: '{g.get('name')}' | Tel: {g.get('phone_e164')}")

# 3. Check JSON files in scripts/ (e.g. unconfirmed_report.json, meeting_report.json, etc.)
print("\n📌 Busca por '997456023' ou 'PIOVESAN' ou 'FERREIRA' em scripts/*.json:")
for json_file in ROOT.glob("scripts/*.json"):
    try:
        content = json_file.read_text(encoding="utf-8")
        if "997456023" in content or "PIOVESAN" in content:
            print(f"  • Encontrado em file: {json_file.name}")
            data = json.loads(content)
            if isinstance(data, list):
                for item in data:
                    item_str = str(item)
                    if "997456023" in item_str or "PIOVESAN" in item_str or "ARTHUR GABRIEL" in item_str:
                        print(f"    - Match: {item}")
    except Exception as e:
        pass

print("\n" + "=" * 80)
