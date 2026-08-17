"""
swap_responsive_guardians.py - Inverte os contatos primários (is_primary) para os 8 alunos
cujos contatos primários iniciais não responderam, mas os contatos secundários (follow-up) responderam.
"""

import os
import json
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

def swap_student_guardians(student_id: str, current_primary_gid: str, new_primary_gid: str):
    # 1. Update current primary guardian to is_primary = False
    url_pri = f"{SUPABASE_URL}/rest/v1/student_guardians?student_id=eq.{student_id}&guardian_id=eq.{current_primary_gid}"
    r1 = requests.patch(url_pri, headers=headers, json={"is_primary": False})
    
    # 2. Update new primary guardian (successful follow-up) to is_primary = True
    url_sec = f"{SUPABASE_URL}/rest/v1/student_guardians?student_id=eq.{student_id}&guardian_id=eq.{new_primary_gid}"
    r2 = requests.patch(url_sec, headers=headers, json={"is_primary": True})
    
    print(f"  [SWAP OK] Student {student_id}: G_Old({current_primary_gid}) -> is_primary=False (HTTP {r1.status_code}) | G_New({new_primary_gid}) -> is_primary=True (HTTP {r2.status_code})", flush=True)

def main():
    print("=== EXECUTANDO INVERSÃO DE CONTATOS PRIMÁRIOS (SWAP FOLLOW-UP) ===", flush=True)
    
    # Load study candidates from JSON
    json_path = "scratch/followup_swap_study.json"
    if not os.path.exists(json_path):
        print(f"❌ Arquivo {json_path} não encontrado!", flush=True)
        return
        
    with open(json_path, "r", encoding="utf-8") as f:
        candidates = json.load(f)

    print(f"Total de Alunos a inverter o contato primário: {len(candidates)}\n", flush=True)

    for idx, c in enumerate(candidates, 1):
        s_name = c["student_name"]
        ra = c["student_ra"]
        s_id = c["student_id"]
        old_g = c["current_primary"]
        new_g = c["successful_secondary"]

        print(f"[{idx}] Invertendo contato de {s_name} (RA: {ra}):", flush=True)
        print(f"    - Antigo Primário (Sem resposta): {old_g['name']} ({old_g['relationship']} - {old_g['phone']}) -> Alterando para Secundário", flush=True)
        print(f"    + Novo Primário (Respondeu no Follow-up): {new_g['name']} ({new_g['relationship']} - {new_g['phone']}) -> Promovendo para Primário", flush=True)
        
        swap_student_guardians(s_id, old_g["guardian_id"], new_g["guardian_id"])
        print("-" * 70, flush=True)

    print("\n=== TODAS AS INVERSÕES FORAM EXECUTADAS COM SUCESSO! ===", flush=True)

if __name__ == "__main__":
    main()
