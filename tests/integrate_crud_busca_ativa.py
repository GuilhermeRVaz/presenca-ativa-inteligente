import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / 'pages'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PAGES))

import importlib.util
import types
pkg = types.ModuleType('pages')
pkg.__path__ = [str(PAGES)]
sys.modules['pages'] = pkg

spec = importlib.util.spec_from_file_location('pages.supabase_crud', str(PAGES / 'supabase_crud.py'))
crud = importlib.util.module_from_spec(spec)
sys.modules['pages.supabase_crud'] = crud
spec.loader.exec_module(crud)

from app.infrastructure.supabase.repositories import SupabaseRepository

TEST_RA = "999999999"
TEST_NAME = "TESTE INTEGRACAO CRUD"
TEST_CLASS = "8 ANO 8A INTEGRAL 9H ANUAL"

repo = SupabaseRepository()
client = repo.client

existing = client.schema("busca_ativa_v2").table("students").select("*").eq("ra", TEST_RA).execute().data or []
if existing:
    student_id = existing[0]["id"]
    student_clean = client.schema("busca_ativa_v2").table("students").delete().eq("id", student_id).execute()
    guardians = client.schema("busca_ativa_v2").table("student_guardians").select("*").eq("student_id", student_id).execute().data or []
    for g in guardians:
        client.schema("busca_ativa_v2").table("student_guardians").delete().eq("student_id", student_id).eq("guardian_id", g["guardian_id"]).execute()
    client.schema("public").table("contacts").delete().eq("ra", TEST_RA).execute()
    print(f"cleaned_old={TEST_RA}")
else:
    student_id = None

student = crud.upsert_student(crud.NormalizedStudentInput(
    name=TEST_NAME,
    ra=TEST_RA,
    class_name=TEST_CLASS,
    grade=None,
    active=True,
))
student_id = student["id"]
print(f"student_created={student_id}")

crud.update_legacy_contact(
    ra=TEST_RA,
    name=TEST_NAME,
    class_name=TEST_CLASS,
    birth_date="01/01/2010",
    guardians=[
        ("mãe", "14996437671"),
        ("pai", "14998477641"),
    ],
)
print("legacy_contact_ok")

gid_mae = crud.upsert_guardian_and_link(
    student_id=student_id,
    relationship="mãe",
    phone_raw="14996437671",
    primary=True,
)
gid_pai = crud.upsert_guardian_and_link(
    student_id=student_id,
    relationship="pai",
    phone_raw="14998477641",
    primary=False,
)
print(f"guardians_linked={gid_mae},{gid_pai}")

student_check = client.schema("busca_ativa_v2").table("students").select("*").eq("id", student_id).execute().data or []
link_check = client.schema("busca_ativa_v2").table("student_guardians").select("*").eq("student_id", student_id).execute().data or []
legacy_check = client.schema("public").table("contacts").select("*").eq("ra", TEST_RA).execute().data or []
identity_check = client.schema("busca_ativa_v2").table("phone_identity_map").select("*").eq("guardian_id", gid_mae).execute().data or []

print(f"student_row_count={len(student_check)}")
print(f"link_row_count={len(link_check)}")
print(f"legacy_row_count={len(legacy_check)}")
print(f"identity_row_count={len(identity_check)}")

for row in student_check:
    print("student_name=" + str(row.get("name")))
    print("student_ra=" + str(row.get("ra")))
    print("student_class=" + str(row.get("class_name")))
    print("student_active=" + str(row.get("active")))

for row in link_check:
    print("link_guardian_id=" + str(row.get("guardian_id")) + " is_primary=" + str(row.get("is_primary")) + " rel=" + str(row.get("relationship")))

for row in legacy_check:
    print("legacy_turma=" + str(row.get("turma")) + " fone1=" + str(row.get("telefone_1")) + " resp1=" + str(row.get("responsavel_1")))

for row in identity_check:
    print("identity_phone=" + str(row.get("phone_e164")) + " confidence=" + str(row.get("confidence")))

# Simula o que o campaign_loader faz para validar
resolver = client.schema("busca_ativa_v2").table("students").select("id").eq("ra", TEST_RA).limit(1).execute().data or []
if resolver:
    sim_id = resolver[0]["id"]
    sim_guard = client.schema("busca_ativa_v2").table("student_guardians").select("guardian_id,is_primary,guardians(id,name,phone_e164,wa_jid)").eq("student_id", sim_id).eq("is_primary", True).limit(1).execute().data or []
    print(f"simulate_campaign_loader_primary_guardian_found={len(sim_guard) > 0}")
    if sim_guard:
        print("simulate_wa_jid=" + str(sim_guard[0]["guardians"].get("wa_jid")))

# cleanup
client.schema("busca_ativa_v2").table("student_guardians").delete().eq("student_id", student_id).execute()
client.schema("busca_ativa_v2").table("students").delete().eq("id", student_id).execute()
# limpa guardians orfãos
for gid in [gid_mae, gid_pai]:
    client.schema("busca_ativa_v2").table("guardians").delete().eq("id", gid).execute()
client.schema("public").table("contacts").delete().eq("ra", TEST_RA).execute()
print("cleanup_done")
