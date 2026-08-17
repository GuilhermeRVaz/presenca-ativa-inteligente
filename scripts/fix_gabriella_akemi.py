"""
scripts/fix_gabriella_akemi.py

Ajusta o cadastro de GABRIELLA AKEMI FERREIRA (RA 114823676) no Supabase:
1. Desvincula qualquer outro responsável (ex: avós, outros números) deixando apenas o número 14 991374483.
2. Atualiza o cadastro do responsável para o telefone E164 padrão 5514991374483 e JID 5514991374483@s.whatsapp.net.
3. Garante que este responsável seja o único vínculo ativo e primário da aluna.
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
STUDENT_ID = "60a66c1a-3807-4800-ab96-45a6c8ad0bb8"  # GABRIELLA AKEMI FERREIRA
GUARDIAN_ID = "64770b5a-07e2-4a0f-8cc1-65b9d4a3c31b"  # Guardian 14991374483


def fix_gabriella():
    repo = SupabaseRepository(timeout=15.0, attempts=2)
    client = repo.client

    print("=" * 80)
    print("🔧 AJUSTANDO CADASTRO DE GABRIELLA AKEMI FERREIRA (RA 114823676)")
    print("=" * 80)

    # 1. Atualizar os dados do responsável do telefone 14991374483
    phone_e164 = "5514991374483"
    wa_jid = "5514991374483@s.whatsapp.net"

    res_g_up = client.schema("busca_ativa_v2").table("guardians").update({
        "name": "Responsável (Gabriella Akemi Ferreira)",
        "phone_e164": phone_e164,
        "wa_jid": wa_jid
    }).eq("id", GUARDIAN_ID).execute()

    print(f"\n✅ Responsável {GUARDIAN_ID} atualizado:")
    for g in (res_g_up.data or []):
        print(f"   • Nome: {g.get('name')} | Tel: {g.get('phone_e164')} | JID: {g.get('wa_jid')}")

    # 2. Desvincular todos os outros responsáveis da aluna em student_guardians (diferentes de GUARDIAN_ID)
    res_del_links = client.schema("busca_ativa_v2").table("student_guardians").delete().eq("student_id", STUDENT_ID).neq("guardian_id", GUARDIAN_ID).execute()
    print(f"\n🧹 Outros responsáveis desvinculados da aluna GABRIELLA AKEMI FERREIRA.")

    # 3. Garantir que o vínculo do responsável correto está como primário (is_primary = True)
    res_sg_check = client.schema("busca_ativa_v2").table("student_guardians").select("*").eq("student_id", STUDENT_ID).eq("guardian_id", GUARDIAN_ID).execute()
    if res_sg_check.data:
        client.schema("busca_ativa_v2").table("student_guardians").update({
            "is_primary": True,
            "relationship": "responsible"
        }).eq("student_id", STUDENT_ID).eq("guardian_id", GUARDIAN_ID).execute()
        print("✅ Vínculo primário atualizado em student_guardians.")
    else:
        client.schema("busca_ativa_v2").table("student_guardians").insert({
            "student_id": STUDENT_ID,
            "guardian_id": GUARDIAN_ID,
            "is_primary": True,
            "relationship": "responsible"
        }).execute()
        print("✅ Novo vínculo primário inserido em student_guardians.")

    # 4. Verificação Final dos registros da aluna
    res_st = client.schema("busca_ativa_v2").table("students").select("*").eq("id", STUDENT_ID).execute()
    print("\n📌 Verificação do Estado Final da Aluna:")
    for st in (res_st.data or []):
        print(f"  • Aluna: {st.get('name')} | RA: {st.get('ra')} | Turma: {st.get('class_name')}")
        res_links = client.schema("busca_ativa_v2").table("student_guardians").select("is_primary, relationship, guardians(*)").eq("student_id", STUDENT_ID).execute()
        for link in (res_links.data or []):
            g = link.get("guardians") or {}
            print(f"    ➔ Responsável Único: '{g.get('name')}' | Tel: {g.get('phone_e164')} | JID: {g.get('wa_jid')} | Primário: {link.get('is_primary')}")

    print("\n" + "=" * 80)
    print("✨ CADASTRO DE GABRIELLA AKEMI FERREIRA CORRIGIDO COM SUCESSO!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    fix_gabriella()
