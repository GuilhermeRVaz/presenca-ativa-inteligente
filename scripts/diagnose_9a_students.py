"""
scripts/diagnose_9a_students.py

Diagnóstico detalhado dos alunos do 9º A no Supabase:
1. Lista turmas disponíveis no Supabase
2. Busca alunos por turma 9º A / 9A
3. Verifica vinculação de responsáveis (student_guardians) e telefones (phone_e164/wa_jid)
"""

import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform.startswith("win"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

from app.infrastructure.supabase.repositories import SupabaseRepository

SCHOOL_ID = "aac99735-32cb-4615-b2cb-0be315f18374"

# Lista de alunos colada pelo usuário
USER_STUDENTS = [
    {"num": 1, "name": "ANA BEATRIS MORAES SANTOS", "ra": "112910217", "p1": "14996593361"},
    {"num": 2, "name": "ANA JULIA COSTA ANDRE", "ra": "112802936", "p1": "14998124987"},
    {"num": 4, "name": "ANA LUIZA PACHELLE GUIMARÃES", "ra": "115425454", "p1": "14997140787"},
    {"num": 5, "name": "ANDRÉ SANTANA DE BRITO", "ra": "112802948", "p1": "14998068421"},
    {"num": 6, "name": "ARTHUR GABRIEL DA SILVA FERREIRA", "ra": "111193712", "p1": "14996850337"},
    {"num": 7, "name": "ARTHUR RODRIGUES DA SILVA", "ra": "112136137", "p1": "14996354733"},
    {"num": 8, "name": "DANIEL EBENÉZER DE SOUZA BRITO", "ra": "114658728", "p1": "14991981497"},
    {"num": 9, "name": "DAVI LUCAS VIANA DOS SANTOS", "ra": "112152137", "p1": "14998856921"},
    {"num": 10, "name": "DIOGO COSSO SILVA", "ra": "113063894", "p1": "14998633634"},
    {"num": 11, "name": "EDSON GUILHERME PEREIRA DA SILVA", "ra": "112036862", "p1": "14991188044"},
    {"num": 12, "name": "EDUARDO GABRIEL SILVA RIBEIRO", "ra": "111993405", "p1": ""},
    {"num": 13, "name": "EMERSON CAUÃ DA SILVA", "ra": "114658754", "p1": "14991949645"},
    {"num": 14, "name": "GABRIELLY BENTO ALVES", "ra": "113093624", "p1": "14998111495"},
    {"num": 15, "name": "HELDER HENRIQUE BRANDAO", "ra": "112756744", "p1": "14996555640"},
    {"num": 16, "name": "JESSICA DA SILVA NASCIMENTO", "ra": "112483610", "p1": "14996414676"},
    {"num": 17, "name": "JOÃO GUILHERME DA SILVA SOUZA", "ra": "112627439", "p1": "14996824439"},
    {"num": 18, "name": "JOÃO LUCAS RIBEIRO VIEIRA", "ra": "115030555", "p1": "14996810535"},
    {"num": 19, "name": "KAUAN FERNANDO PEREIRA DUARTE", "ra": "112910036", "p1": "14996332313"},
    {"num": 20, "name": "LEONARDO CESAR FERREIRA", "ra": "112862463", "p1": "14997978770"},
    {"num": 21, "name": "LEONARDO WENDEL NUNES BRAULINO", "ra": "113115868", "p1": "14998044594"},
    {"num": 22, "name": "LUCAS DANIEL BERTAGLIA MEDEIROS", "ra": "114181646", "p1": "14996530711"},
    {"num": 23, "name": "LUIS MIGUEL PAIVA BERNAVA", "ra": "112807059", "p1": "14998608582"},
    {"num": 24, "name": "LUIZ ANTÔNIO SENNE", "ra": "113931986", "p1": "14997042053"},
    {"num": 25, "name": "MARINA COSTA OLIVEIRA", "ra": "112806509", "p1": "14999074528"},
    {"num": 26, "name": "MATHEUS VINICIUS ROCHA", "ra": "112943369", "p1": "14991850874"},
    {"num": 27, "name": "MURILO HENRIQUE PEREIRA BOSCHETO", "ra": "112845111", "p1": "14991243432"},
    {"num": 28, "name": "PEDRO DANIEL DA SILVA MESSIAS", "ra": "111919014", "p1": "14996420280"},
    {"num": 29, "name": "PEDRO HENRIQUE DE CARVALHO VIEIRA", "ra": "112967105", "p1": "14997841728"},
    {"num": 30, "name": "PEDRO RUAN OLIVEIRA YOSHIKADO", "ra": "112332377", "p1": "14988386469"},
    {"num": 31, "name": "PEDRO VITOR MORAES SANTOS", "ra": "112910291", "p1": "14996593361"},
    {"num": 32, "name": "MIGUEL ANTONIO OLIVEIRA GOIS", "ra": "125423475", "p1": "42988093900"},
    {"num": 33, "name": "ESTEVAM GABRIEL PEREIRA DIAS", "ra": "115497309", "p1": "14997177242"},
    {"num": 34, "name": "EFRAIM WESLEY SILVA SOARES", "ra": "116297202", "p1": "14985995103"},
    {"num": 35, "name": "JOÃO PEDRO MAZZOCO DE OLIVEIRA", "ra": "114658793", "p1": "14998263596"},
    {"num": 36, "name": "ISIS QUINTANILHA SAMPAIO", "ra": "111571004", "p1": "14997966212"},
]


def diagnose():
    repo = SupabaseRepository(timeout=15.0, attempts=2)
    client = repo.client

    print("=" * 70)
    print("🔍 DIAGNÓSTICO DO 9º ANO / SUPABASE")
    print("=" * 70)

    # 1. Buscar todas as turmas que possuem a palavra "9" em students
    print("\n📌 1. Turmas de 9º Ano cadastradas no Supabase:")
    res_classes = client.schema("busca_ativa_v2").table("students").select("class_name").eq("school_id", SCHOOL_ID).execute()
    all_classes = sorted(list(set(row["class_name"] for row in (res_classes.data or []) if row.get("class_name"))))
    
    classes_9 = [c for c in all_classes if "9" in c]
    for c in classes_9:
        count = sum(1 for r in res_classes.data if r.get("class_name") == c)
        print(f"   • Turma no banco: '{c}' (Total alunos: {count})")
    
    if not classes_9:
        print("   ⚠️ Nenhuma turma com '9' encontrada no Supabase!")
        print(f"   Todas as turmas existentes ({len(all_classes)}): {all_classes[:10]}...")

    # 2. Buscar alunos por turma 9º Ano
    students_9a_db = []
    if classes_9:
        target_c = classes_9[0]
        print(f"\n📌 2. Alunos na turma '{target_c}':")
        res_st = client.schema("busca_ativa_v2").table("students").select("id, name, ra, class_name").eq("school_id", SCHOOL_ID).in_("class_name", classes_9).execute()
        students_9a_db = res_st.data or []
        print(f"   Total de alunos encontrados nas turmas de 9º ano no Supabase: {len(students_9a_db)}")
    
    # 3. Cruzar lista colada pelo usuário com o Supabase
    print("\n📌 3. Cruzamento dos 35 alunos da lista com o Supabase:")
    found_count = 0
    with_guardian_count = 0
    enqueueable_count = 0

    for st in USER_STUDENTS:
        ra_query = st["ra"]
        name_query = st["name"]
        
        # Buscar por RA ou Nome no banco
        res_check = client.schema("busca_ativa_v2").table("students").select("id, name, ra, class_name").eq("school_id", SCHOOL_ID).or_(f"ra.eq.{ra_query},name.ilike.%{name_query.split()[0]}%").execute()
        matches = res_check.data or []
        
        exact_match = None
        for m in matches:
            if m.get("ra") == ra_query or m.get("name", "").strip().upper() == name_query.strip().upper():
                exact_match = m
                break
        
        if not exact_match and matches:
            exact_match = matches[0]

        if not exact_match:
            print(f"❌ [Nº {st['num']:02d}] {name_query} (RA: {ra_query}) ➔ NÃO ENCONTRADO NO SUPABASE!")
            continue

        found_count += 1
        student_id = exact_match["id"]
        db_class = exact_match.get("class_name")

        # Verificar se possui responsável primário (student_guardians -> guardians)
        res_sg = client.schema("busca_ativa_v2").table("student_guardians").select("is_primary, guardians(name, phone_e164, wa_jid)").eq("student_id", student_id).execute()
        sg_list = res_sg.data or []
        
        has_primary = any(sg.get("is_primary") for sg in sg_list)
        phone = None
        for sg in sg_list:
            g = sg.get("guardians") or {}
            p = g.get("phone_e164") or g.get("wa_jid")
            if p:
                phone = p
                break

        if phone:
            with_guardian_count += 1
            enqueueable_count += 1
            status_str = f"✅ OK (Turma: '{db_class}', Tel: {phone})"
        elif sg_list:
            status_str = f"⚠️ TEM RESPONSÁVEL MAS SEM TELEFONE CADASTRADO! (Turma: '{db_class}')"
        else:
            status_str = f"❌ SEM VÍNCULO EM 'student_guardians'! (Turma: '{db_class}')"

        print(f"   [Nº {st['num']:02d}] {name_query} ➔ {status_str}")

    print("\n" + "=" * 70)
    print("📊 RESUMO DA ANÁLISE:")
    print(f"• Total de alunos na lista colada: {len(USER_STUDENTS)}")
    print(f"• Encontrados no banco Supabase:   {found_count} de {len(USER_STUDENTS)}")
    print(f"• Com responsável e tel válido:   {enqueueable_count} de {len(USER_STUDENTS)}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    diagnose()
