"""
scripts/fix_arthur_piovesan.py

Corrige o cadastro do aluno ARTHUR GABRIEL DIAS PIOVESAN (RA 114854930) no Supabase.

Causa do erro:
O aluno com RA 114854930 estava cadastrado com o nome "ARTHUR GABRIEL DA SILVA FERREIRA" por engano (nome de outro aluno da mesma turma).
Sua mãe tem o telefone 5514997456023 (Guardian ID: 9092c420-d006-4c3f-ae20-684f701cb73d).
Quando as mensagens eram enfileiradas para o telefone 5514997456023, o sistema buscava o nome do aluno no banco (que era "ARTHUR GABRIEL DA SILVA FERREIRA") e enviava a mensagem com o nome errado.

Ações deste script:
1. Atualizar o nome do aluno ID 53a73ade-09e6-4cc1-bd1b-1f330eab8566 (RA 114854930) para "ARTHUR GABRIEL DIAS PIOVESAN".
2. Atualizar o nome do responsável ID 9092c420-d006-4c3f-ae20-684f701cb73d para "Mãe (Arthur Gabriel Dias Piovesan)".
3. Garantir o vínculo correto em student_guardians entre Aluno (53a73ade-09e6-4cc1-bd1b-1f330eab8566) e Guardian (9092c420-d006-4c3f-ae20-684f701cb73d) com is_primary=True.
4. Remover a cópia/fantasma duplicada com RA "DI-ARTHUR-9A" (ID 776235d8-2dc0-461f-a12c-f49d3008ab65).
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


def fix_arthur_piovesan():
    repo = SupabaseRepository(timeout=15.0, attempts=2)
    client = repo.client

    print("=" * 80)
    print("🔧 APLICANDO CORREÇÃO DO CADASTRO DE ARTHUR GABRIEL DIAS PIOVESAN")
    print("=" * 80)

    # 1. Atualizar aluno RA 114854930 (ID 53a73ade-09e6-4cc1-bd1b-1f330eab8566)
    student_id = "53a73ade-09e6-4cc1-bd1b-1f330eab8566"
    res_st = client.schema("busca_ativa_v2").table("students").update({
        "name": "ARTHUR GABRIEL DIAS PIOVESAN"
    }).eq("id", student_id).execute()

    print(f"✅ Aluno RA 114854930 (ID: {student_id}) atualizado para:")
    for st in (res_st.data or []):
        print(f"   • Nome: {st.get('name')} | RA: {st.get('ra')} | Turma: {st.get('class_name')}")

    # 2. Atualizar o responsável com telefone 5514997456023 (Guardian ID 9092c420-d006-4c3f-ae20-684f701cb73d)
    guardian_id = "9092c420-d006-4c3f-ae20-684f701cb73d"
    res_g = client.schema("busca_ativa_v2").table("guardians").update({
        "name": "Mãe (Arthur Gabriel Dias Piovesan)"
    }).eq("id", guardian_id).execute()

    print(f"\n✅ Responsável (Tel: 5514997456023 | ID: {guardian_id}) atualizado para:")
    for g in (res_g.data or []):
        print(f"   • Nome: {g.get('name')} | Tel: {g.get('phone_e164')}")

    # 3. Garantir / Criar vínculo em student_guardians
    res_sg = client.schema("busca_ativa_v2").table("student_guardians").select("*").eq("student_id", student_id).eq("guardian_id", guardian_id).execute()
    if res_sg.data:
        client.schema("busca_ativa_v2").table("student_guardians").update({
            "is_primary": True,
            "relationship": "mother"
        }).eq("student_id", student_id).eq("guardian_id", guardian_id).execute()
        print(f"\n✅ Vínculo existente atualizado: Aluno ARTHUR GABRIEL DIAS PIOVESAN ➔ Mãe (5514997456023)")
    else:
        client.schema("busca_ativa_v2").table("student_guardians").insert({
            "student_id": student_id,
            "guardian_id": guardian_id,
            "is_primary": True,
            "relationship": "mother"
        }).execute()
        print(f"\n✅ Novo vínculo criado: Aluno ARTHUR GABRIEL DIAS PIOVESAN ➔ Mãe (5514997456023)")

    # 4. Remover registro fantasma/duplicado com RA "DI-ARTHUR-9A"
    ghost_id = "776235d8-2dc0-461f-a12c-f49d3008ab65"
    client.schema("busca_ativa_v2").table("student_guardians").delete().eq("student_id", ghost_id).execute()
    client.schema("busca_ativa_v2").table("students").delete().eq("id", ghost_id).execute()
    print(f"\n🧹 Registro duplicado/fantasma removido (ID: {ghost_id}, RA: DI-ARTHUR-9A)")

    print("\n" + "=" * 80)
    print("✨ CORREÇÃO CONCLUÍDA COM SUCESSO NO SUPABASE!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    fix_arthur_piovesan()
