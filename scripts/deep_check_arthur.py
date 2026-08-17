"""
scripts/deep_check_arthur.py
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

repo = SupabaseRepository(timeout=15.0, attempts=2)
client = repo.client

print("=" * 70)
print("🔍 DEEP SEARCH: ARTHUR GABRIEL, PIOVESAN, AND 997456023")
print("=" * 70)

# 1. Search students in busca_ativa_v2
print("\n--- 1. BUSCA_ATIVA_V2.STUDENTS ---")
res_st = client.schema("busca_ativa_v2").table("students").select("*").execute()
all_students = res_st.data or []
print(f"Total alunos em busca_ativa_v2: {len(all_students)}")
for st in all_students:
    name = st.get("name", "")
    if any(term in name.upper() for term in ["ARTHUR", "PIOVESAN", "FERREIRA", "GABRIEL"]):
        print(f"  • ID: {st.get('id')} | Name: {name} | Class: {st.get('class_name')} | RA: {st.get('ra')} | SchoolID: {st.get('school_id')}")

# 2. Search guardians in busca_ativa_v2
print("\n--- 2. BUSCA_ATIVA_V2.GUARDIANS ---")
res_gd = client.schema("busca_ativa_v2").table("guardians").select("*").execute()
all_guardians = res_gd.data or []
print(f"Total guardians em busca_ativa_v2: {len(all_guardians)}")
for g in all_guardians:
    phone = g.get("phone_e164", "")
    name = g.get("name", "")
    if "99745" in phone or "6023" in phone or any(term in name.upper() for term in ["PIOVESAN", "FERREIRA"]):
        print(f"  • Guardian ID: {g.get('id')} | Name: {name} | Phone: {phone}")

# 3. Check student_guardians links
print("\n--- 3. BUSCA_ATIVA_V2.STUDENT_GUARDIANS ---")
res_sg = client.schema("busca_ativa_v2").table("student_guardians").select("*, students(id, name, class_name), guardians(id, name, phone_e164)").execute()
for sg in (res_sg.data or []):
    st = sg.get("students") or {}
    gd = sg.get("guardians") or {}
    st_name = st.get("name", "")
    gd_phone = gd.get("phone_e164", "")
    if "ARTHUR" in st_name.upper() or "99745" in gd_phone:
        print(f"  • Link: Student '{st_name}' ({st.get('id')}) ➔ Guardian '{gd.get('name')}' ({gd_phone}) | Primary: {sg.get('is_primary')} | Rel: {sg.get('relationship')}")

# 4. Search campaign messages / dispatch history for 5514997456023
print("\n--- 4. CAMPAIGN MESSAGES / RECENT MESSAGES ---")
try:
    res_cm = client.schema("busca_ativa_v2").table("campaign_recipients").select("*").ilike("phone_e164", "%997456023%").execute()
    print(f"Campaign Recipients for 997456023: {res_cm.data}")
except Exception as e:
    print(f"Err checking campaign_recipients: {e}")

try:
    res_m = client.schema("busca_ativa_v2").table("messages").select("*").ilike("phone_e164", "%997456023%").execute()
    print(f"Messages for 997456023: {res_m.data}")
except Exception as e:
    print(f"Err checking messages: {e}")

print("\n" + "=" * 70)
