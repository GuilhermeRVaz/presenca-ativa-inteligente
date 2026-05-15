from app.infrastructure.supabase.repositories import SupabaseRepository
r = SupabaseRepository()
client = r.client.schema("busca_ativa_v2")

# Verificar student_guardians com dados
sg = client.table("student_guardians").select(
    "student_id, guardians(id, name, phone_e164), students(ra, name, class_name)"
).limit(5).execute()

print("Exemplos de student_guardians (amostra):")
for item in sg.data:
    st = item.get("students", {})
    gu = item.get("guardians", {})
    print(f"  RA={st.get('ra')} aluno={st.get('name')} | phone={gu.get('phone_e164')} guardian={gu.get('name')}")

# Contar distinct guardians usados na campanha
print(f"\nTotal student_guardians na escola: {len(client.table('student_guardians').select('id').execute().data)}")

# Guardians distintos
print(f"Guardians distintos: {len(client.table('guardians').select('id').execute().data)}")

# Students da campanha (que têm student_guardian)
students_in = client.table("student_guardians").select("student_id").execute()
student_ids = {s["student_id"] for s in students_in.data}
print(f"Students únicos com guardian: {len(student_ids)}")
