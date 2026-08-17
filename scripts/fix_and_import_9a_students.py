"""
scripts/fix_and_import_9a_students.py

Script para normalizar a turma dos 35 alunos do 9º A no Supabase:
1. Atualiza class_name para '9 ANO 9A INTEGRAL 9H ANUAL' para todos os alunos encontrados.
2. Insere os 3 alunos faltantes (HELDER, JESSICA, MARINA) e seus respectivos responsáveis e telefones.
3. Garante que todos os 35 alunos possuam vínculo de responsável primário e telefone E.164 (5514...).
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
TARGET_CLASS = "9 ANO 9A INTEGRAL 9H ANUAL"

USER_STUDENTS = [
    {"num": 1, "name": "ANA BEATRIS MORAES SANTOS", "ra": "112910217", "g_name": "pai", "phone": "14996593361"},
    {"num": 2, "name": "ANA JULIA COSTA ANDRE", "ra": "112802936", "g_name": "mãe", "phone": "14998124987"},
    {"num": 4, "name": "ANA LUIZA PACHELLE GUIMARÃES", "ra": "115425454", "g_name": "mãe", "phone": "14997140787"},
    {"num": 5, "name": "ANDRÉ SANTANA DE BRITO", "ra": "112802948", "g_name": "pai", "phone": "14998068421"},
    {"num": 6, "name": "ARTHUR GABRIEL DA SILVA FERREIRA", "ra": "111193712", "g_name": "mae", "phone": "14996850337"},
    {"num": 7, "name": "ARTHUR RODRIGUES DA SILVA", "ra": "112136137", "g_name": "mãe", "phone": "14996354733"},
    {"num": 8, "name": "DANIEL EBENÉZER DE SOUZA BRITO", "ra": "114658728", "g_name": "mãe", "phone": "14991981497"},
    {"num": 9, "name": "DAVI LUCAS VIANA DOS SANTOS", "ra": "112152137", "g_name": "mãe", "phone": "14998856921"},
    {"num": 10, "name": "DIOGO COSSO SILVA", "ra": "113063894", "g_name": "mãe", "phone": "14998633634"},
    {"num": 11, "name": "EDSON GUILHERME PEREIRA DA SILVA", "ra": "112036862", "g_name": "pai", "phone": "14991188044"},
    {"num": 12, "name": "EDUARDO GABRIEL SILVA RIBEIRO", "ra": "111993405", "g_name": "irmão", "phone": "14991653247"},
    {"num": 13, "name": "EMERSON CAUÃ DA SILVA", "ra": "114658754", "g_name": "mãe", "phone": "14991949645"},
    {"num": 14, "name": "GABRIELLY BENTO ALVES", "ra": "113093624", "g_name": "pai", "phone": "14998111495"},
    {"num": 15, "name": "HELDER HENRIQUE BRANDAO", "ra": "112756744", "g_name": "mãe", "phone": "14996555640"},
    {"num": 16, "name": "JESSICA DA SILVA NASCIMENTO", "ra": "112483610", "g_name": "mãe", "phone": "14996414676"},
    {"num": 17, "name": "JOÃO GUILHERME DA SILVA SOUZA", "ra": "112627439", "g_name": "mãe", "phone": "14996824439"},
    {"num": 18, "name": "JOÃO LUCAS RIBEIRO VIEIRA", "ra": "115030555", "g_name": "pai", "phone": "14996810535"},
    {"num": 19, "name": "KAUAN FERNANDO PEREIRA DUARTE", "ra": "112910036", "g_name": "mãe", "phone": "14996332313"},
    {"num": 20, "name": "LEONARDO CESAR FERREIRA", "ra": "112862463", "g_name": "mãe", "phone": "14997978770"},
    {"num": 21, "name": "LEONARDO WENDEL NUNES BRAULINO", "ra": "113115868", "g_name": "pai", "phone": "14998044594"},
    {"num": 22, "name": "LUCAS DANIEL BERTAGLIA MEDEIROS", "ra": "114181646", "g_name": "pai", "phone": "14996530711"},
    {"num": 23, "name": "LUIS MIGUEL PAIVA BERNAVA", "ra": "112807059", "g_name": "pai", "phone": "14998608582"},
    {"num": 24, "name": "LUIZ ANTÔNIO SENNE", "ra": "113931986", "g_name": "mãe", "phone": "14997042053"},
    {"num": 25, "name": "MARINA COSTA OLIVEIRA", "ra": "112806509", "g_name": "mãe", "phone": "14999074528"},
    {"num": 26, "name": "MATHEUS VINICIUS ROCHA", "ra": "112943369", "g_name": "mãe", "phone": "14991850874"},
    {"num": 27, "name": "MURILO HENRIQUE PEREIRA BOSCHETO", "ra": "112845111", "g_name": "pai", "phone": "14991243432"},
    {"num": 28, "name": "PEDRO DANIEL DA SILVA MESSIAS", "ra": "111919014", "g_name": "mãe", "phone": "14996420280"},
    {"num": 29, "name": "PEDRO HENRIQUE DE CARVALHO VIEIRA", "ra": "112967105", "g_name": "mãe", "phone": "14997841728"},
    {"num": 30, "name": "PEDRO RUAN OLIVEIRA YOSHIKADO", "ra": "112332377", "g_name": "mãe", "phone": "14988386469"},
    {"num": 31, "name": "PEDRO VITOR MORAES SANTOS", "ra": "112910291", "g_name": "pai", "phone": "14996593361"},
    {"num": 32, "name": "MIGUEL ANTONIO OLIVEIRA GOIS", "ra": "125423475", "g_name": "mãe", "phone": "42988093900"},
    {"num": 33, "name": "ESTEVAM GABRIEL PEREIRA DIAS", "ra": "115497309", "g_name": "pai", "phone": "14997177242"},
    {"num": 34, "name": "EFRAIM WESLEY SILVA SOARES", "ra": "116297202", "g_name": "pai", "phone": "14985995103"},
    {"num": 35, "name": "JOÃO PEDRO MAZZOCO DE OLIVEIRA", "ra": "114658793", "g_name": "PAI", "phone": "14998263596"},
    {"num": 36, "name": "ISIS QUINTANILHA SAMPAIO", "ra": "111571004", "g_name": "mãe", "phone": "14997966212"},
]


def format_phone(raw: str) -> str:
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""
    if not digits.startswith("55"):
        digits = f"55{digits}"
    return digits


def run_fix():
    print("=" * 70)
    print("🚀 NORMALIZANDO CADASTRO DO 9º A NO SUPABASE")
    print("=" * 70)

    repo = SupabaseRepository(timeout=30.0, attempts=3)
    client = repo.client

    updated_count = 0
    created_count = 0

    for st in USER_STUDENTS:
        name = st["name"].strip().upper()
        ra = st["ra"].strip()
        phone_e164 = format_phone(st["phone"])
        g_name = f"Responsável de {name.split()[0]}"

        # 1. Verificar se aluno existe no banco
        res_st = client.schema("busca_ativa_v2").table("students").select("id, name, ra, class_name").eq("school_id", SCHOOL_ID).or_(f"ra.eq.{ra},name.ilike.%{name.split()[0]}%").execute()
        rows = res_st.data or []

        exact_student = None
        for r in rows:
            if r.get("ra") == ra or r.get("name", "").strip().upper() == name:
                exact_student = r
                break

        if exact_student:
            student_id = exact_student["id"]
            # Atualizar class_name se divergente
            if exact_student.get("class_name") != TARGET_CLASS:
                client.schema("busca_ativa_v2").table("students").update({"class_name": TARGET_CLASS}).eq("id", student_id).execute()
                print(f"🔄 Aluno {name}: Turma atualizada de '{exact_student.get('class_name')}' ➔ '{TARGET_CLASS}'")
            updated_count += 1
        else:
            # Criar novo aluno
            new_st_payload = {
                "school_id": SCHOOL_ID,
                "name": name,
                "ra": ra,
                "class_name": TARGET_CLASS,
            }
            res_new = client.schema("busca_ativa_v2").table("students").insert(new_st_payload).execute()
            student_id = res_new.data[0]["id"]
            print(f"✨ Aluno {name}: CADASTRADO NOVO NO SUPABASE! (ID: {student_id})")
            created_count += 1

        # 2. Verificar responsável e telefone
        if phone_e164:
            res_sg = client.schema("busca_ativa_v2").table("student_guardians").select("guardian_id, is_primary, guardians(id, phone_e164)").eq("student_id", student_id).execute()
            sg_data = res_sg.data or []

            has_valid = False
            for sg in sg_data:
                g = sg.get("guardians") or {}
                if g.get("phone_e164") == phone_e164:
                    has_valid = True
                    break

            if not has_valid:
                # Buscar se o telefone já existe na tabela de responsáveis
                res_g_check = client.schema("busca_ativa_v2").table("guardians").select("id").eq("school_id", SCHOOL_ID).eq("phone_e164", phone_e164).limit(1).execute()
                g_existing = res_g_check.data or []

                if g_existing:
                    guardian_id = g_existing[0]["id"]
                else:
                    # Criar responsável
                    g_payload = {
                        "school_id": SCHOOL_ID,
                        "name": g_name,
                        "phone_e164": phone_e164,
                        "wa_jid": f"{phone_e164}@s.whatsapp.net",
                    }
                    res_g = client.schema("busca_ativa_v2").table("guardians").insert(g_payload).execute()
                    guardian_id = res_g.data[0]["id"]

                # Garantir o vínculo em student_guardians
                res_link = client.schema("busca_ativa_v2").table("student_guardians").select("*").eq("student_id", student_id).eq("guardian_id", guardian_id).execute()
                if not (res_link.data or []):
                    sg_payload = {
                        "student_id": student_id,
                        "guardian_id": guardian_id,
                        "is_primary": True,
                    }
                    client.schema("busca_ativa_v2").table("student_guardians").insert(sg_payload).execute()
                print(f"   📞 Responsável (ID: {guardian_id}) vinculado a {name}: Tel {phone_e164}")

    print("\n" + "=" * 70)
    print("✅ FINALIZADO COM SUCESSO!")
    print(f"• Alunos atualizados/ajustados: {updated_count}")
    print(f"• Novos alunos criados no banco: {created_count}")
    print(f"• Todos os 35 alunos agora pertencem à turma '{TARGET_CLASS}'")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_fix()
