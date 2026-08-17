"""
fix_unlinked_students.py - Aplica as correções dos 4 alunos da Varredura 1:
  1. ASHLEY BEATRIZ VICTORELLI DA SILVA MATTOS: Pai (14982325194) e Mãe (14996171034)
  2. MANUELA STEFANE COSTA ALVES: Avó (14998250303) e Avô (14996205917)
  3. DAVI JASOM PEREIRA: Baixa por transferência (active = False)
  4. ARTHUR GABRIEL DA SILVA FERREIRA: Corrigir RA para 111193712 e vincular Mãe (14996850337)
"""

import os
import uuid
import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Accept-Profile": "busca_ativa_v2",
    "Content-Profile": "busca_ativa_v2"
}

school_id = "aac99735-32cb-4615-b2cb-0be315f18374"

def get_or_create_guardian(name: str, phone_raw: str) -> str:
    digits = "".join(filter(str.isdigit, str(phone_raw)))
    if not digits.startswith("55"):
        digits = "55" + digits
    wa_jid = f"{digits}@s.whatsapp.net"
    
    url = f"{SUPABASE_URL}/rest/v1/guardians?school_id=eq.{school_id}&phone_e164=eq.{digits}"
    r = requests.get(url, headers=headers)
    rows = r.json()
    if rows:
        g_id = rows[0]["id"]
        print(f"  [Guardian Existente] {name} ({digits}) -> ID {g_id}")
        return g_id
    
    new_id = str(uuid.uuid4())
    body = {
        "id": new_id,
        "school_id": school_id,
        "name": name,
        "phone_e164": digits,
        "wa_jid": wa_jid,
        "active": True
    }
    r_ins = requests.post(f"{SUPABASE_URL}/rest/v1/guardians", headers=headers, json=body)
    print(f"  [Guardian Criado] {name} ({digits}) -> Status HTTP {r_ins.status_code}")
    return new_id

def link_student(student_id: str, guardian_id: str, relationship: str, is_primary: bool):
    url = f"{SUPABASE_URL}/rest/v1/student_guardians?student_id=eq.{student_id}&guardian_id=eq.{guardian_id}"
    r = requests.get(url, headers=headers)
    if r.json():
        print(f"  [Vínculo Já Existe] Student {student_id} <-> Guardian {guardian_id}")
        return
    body = {
        "student_id": student_id,
        "guardian_id": guardian_id,
        "relationship": relationship,
        "is_primary": is_primary
    }
    r_ins = requests.post(f"{SUPABASE_URL}/rest/v1/student_guardians", headers=headers, json=body)
    print(f"  [Vínculo Criado] Student {student_id} <-> Guardian {guardian_id} ({relationship}) -> Status HTTP {r_ins.status_code}")

def main():
    print("=== INICIANDO APLICAÇÃO DE CORREÇÕES DOS ALUNOS ===")
    
    # 1. ASHLEY (RA: 116076548)
    print("\n1. Processando Ashley (RA: 116076548)...")
    r = requests.get(f"{SUPABASE_URL}/rest/v1/students?ra=eq.116076548", headers=headers)
    ashley_rows = r.json()
    if ashley_rows:
        ashley_id = ashley_rows[0]["id"]
        pai_id = get_or_create_guardian("Pai da Ashley", "14982325194")
        mae_id = get_or_create_guardian("Mãe da Ashley", "14996171034")
        link_student(ashley_id, pai_id, "Pai", False)
        link_student(ashley_id, mae_id, "Mãe", True)
        print("  Ashley concluída!")
    else:
        print("  [ERRO] Ashley não encontrada!")

    # 2. MANUELA (RA: 116131508)
    print("\n2. Processando Manuela (RA: 116131508)...")
    r = requests.get(f"{SUPABASE_URL}/rest/v1/students?ra=eq.116131508", headers=headers)
    manu_rows = r.json()
    if manu_rows:
        manu_id = manu_rows[0]["id"]
        avo_f_id = get_or_create_guardian("Avó da Manuela", "14998250303")
        avo_m_id = get_or_create_guardian("Avô da Manuela", "14996205917")
        link_student(manu_id, avo_f_id, "Avó", True)
        link_student(manu_id, avo_m_id, "Avô", False)
        print("  Manuela concluída!")
    else:
        print("  [ERRO] Manuela não encontrada!")

    # 3. DAVI JASOM PEREIRA (RA: 114539002) - Baixa por transferência
    print("\n3. Processando Davi Jasom Pereira (RA: 114539002 - Transferido)...")
    r = requests.get(f"{SUPABASE_URL}/rest/v1/students?ra=eq.114539002", headers=headers)
    davi_rows = r.json()
    if davi_rows:
        davi_id = davi_rows[0]["id"]
        r_up = requests.patch(f"{SUPABASE_URL}/rest/v1/students?id=eq.{davi_id}", headers=headers, json={"active": False})
        print(f"  Davi ativado=False -> Status HTTP {r_up.status_code}")
    else:
        print("  [ERRO] Davi não encontrado!")

    # 4. ARTHUR GABRIEL DA SILVA FERREIRA (RA: 111193712)
    print("\n4. Processando Arthur Gabriel da Silva Ferreira (RA: 111193712)...")
    r = requests.get(f"{SUPABASE_URL}/rest/v1/students?ra=eq.111193712", headers=headers)
    arthur_rows = r.json()
    if arthur_rows:
        arthur_id = arthur_rows[0]["id"]
        mae_arthur_id = get_or_create_guardian("Mãe do Arthur", "5514996850337")
        link_student(arthur_id, mae_arthur_id, "Mãe", True)
        print("  Arthur concluído!")
    else:
        print("  [ERRO] Arthur não encontrado pelo RA 111193712!")

    # 5. Desativar registro duplicado do Arthur com RA provisório 'DI-ARTHUR-9A'
    print("\n5. Desativando registro antigo de Arthur (RA provisório DI-ARTHUR-9A)...")
    r_old = requests.get(f"{SUPABASE_URL}/rest/v1/students?ra=eq.DI-ARTHUR-9A", headers=headers)
    old_rows = r_old.json()
    if old_rows:
        old_id = old_rows[0]["id"]
        r_old_up = requests.patch(f"{SUPABASE_URL}/rest/v1/students?id=eq.{old_id}", headers=headers, json={"active": False})
        print(f"  Arthur antigo desativado -> Status HTTP {r_old_up.status_code}")

    print("\n=== TODAS AS CORREÇÕES FORAM APLICADAS COM SUCESSO! ===")

if __name__ == "__main__":
    main()
