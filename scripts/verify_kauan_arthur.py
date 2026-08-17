"""
scripts/verify_kauan_arthur.py
Verifica os vínculos atuais de Kauan e Arthur no Supabase.
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
print("🔍 VERIFICAÇÃO FINAL: KAUAN vs ARTHUR")
print("=" * 70)

# Kauan
res_k = client.schema("busca_ativa_v2").table("students").select("id, name, ra, class_name").eq("school_id", SCHOOL_ID).eq("ra", "112910036").execute()
if res_k.data:
    st = res_k.data[0]
    print(f"\n📌 Aluno: {st['name']} (RA: {st['ra']})")
    res_sg = client.schema("busca_ativa_v2").table("student_guardians").select("is_primary, guardians(name, phone_e164)").eq("student_id", st["id"]).execute()
    for sg in (res_sg.data or []):
        g = sg.get("guardians") or {}
        print(f"   ➔ Responsável: {g.get('name')} | Tel: {g.get('phone_e164')} | Primário: {sg.get('is_primary')}")

# Arthur
res_a = client.schema("busca_ativa_v2").table("students").select("id, name, ra, class_name").eq("school_id", SCHOOL_ID).eq("ra", "111193712").execute()
if res_a.data:
    st = res_a.data[0]
    print(f"\n📌 Aluno: {st['name']} (RA: {st['ra']})")
    res_sg = client.schema("busca_ativa_v2").table("student_guardians").select("is_primary, guardians(name, phone_e164)").eq("student_id", st["id"]).execute()
    for sg in (res_sg.data or []):
        g = sg.get("guardians") or {}
        print(f"   ➔ Responsável: {g.get('name')} | Tel: {g.get('phone_e164')} | Primário: {sg.get('is_primary')}")

print("\n" + "=" * 70)
