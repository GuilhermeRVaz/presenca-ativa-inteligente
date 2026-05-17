import os
import sys
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path

# Configurações de Caminho
ROOT_DIR = Path.cwd()
sys.path.append(str(ROOT_DIR))

load_dotenv(ROOT_DIR / ".env")

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY")
INSTANCE_NAME = os.getenv("EVOLUTION_API_INSTANCE")

def fetch_mapping():
    """Mapeia LID/JID para Nome do Aluno cruzando tabelas do Supabase."""
    try:
        from app.infrastructure.supabase.repositories import SupabaseRepository
        repo = SupabaseRepository()
        client = repo.client.schema("busca_ativa_v2")
        
        # 1. Pegar Mapa de Identidade (LID -> Guardian)
        print("Mapeando identidades (LID -> Aluno)...")
        id_map = client.table("phone_identity_map").select("lid_jid, wa_jid, guardian_id").execute().data
        
        # 2. Pegar Relacao Aluno-Responsavel
        rel_map = client.table("student_guardians").select("student_id, guardian_id").execute().data
        
        # 3. Pegar Nomes de Alunos
        students = client.table("students").select("id, name").execute().data
        student_names = {s["id"]: s["name"] for s in students}
        
        # Construir dicionario de traducao: JID/LID -> Nome do Aluno
        translation = {}
        
        # Mapear por Guardian
        guardian_to_student = {}
        for r in rel_map:
            s_name = student_names.get(r["student_id"])
            if s_name:
                guardian_to_student[r["guardian_id"]] = s_name
                
        for entry in id_map:
            s_name = guardian_to_student.get(entry["guardian_id"])
            if s_name:
                if entry.get("lid_jid"): translation[entry["lid_jid"]] = s_name
                if entry.get("wa_jid"): translation[entry["wa_jid"]] = s_name

        print(f"Mapeamento completo: {len(translation)} IDs vinculados a nomes.")
        return translation
    except Exception as e:
        print(f"Aviso: Falha no mapeamento: {e}")
        return {}

def fetch_chat_history(jid, limit=50):
    """Busca o historico real de uma conversa especifica usando filtro aninhado."""
    url = f"{EVOLUTION_API_URL}/chat/findMessages/{INSTANCE_NAME}"
    headers = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}
    payload = {
        "where": {
            "key": {
                "remoteJid": jid
            }
        },
        "limit": limit
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            return data.get("messages", {}).get("records", [])
        return []
    except Exception as e:
        print(f"Erro ao buscar JID {jid}: {e}")
        return []

def run():
    print(f"--- GERANDO RELATORIO CIRURGICO (BUSCA POR CONTATO) ---")
    
    name_map = fetch_mapping()
    jids_to_check = list(name_map.keys())
    
    print(f"Verificando historico para {len(jids_to_check)} contatos mapeados...")
    
    conversations = {}
    TARGET_DATE = datetime(2026, 5, 15).date()
    START_TIME = datetime(2026, 5, 15, 10, 0, 0)
    
    processed_count = 0
    for jid in jids_to_check:
        processed_count += 1
        if processed_count % 50 == 0:
            print(f"Processados {processed_count}/{len(jids_to_check)} contatos...")
            
        records = fetch_chat_history(jid)
        if not records: continue
        
        for msg in records:
            key = msg.get("key", {})
            
            content = ""
            m = msg.get("message", {})
            if "conversation" in m: content = m["conversation"]
            elif "extendedTextMessage" in m: content = m.get("extendedTextMessage", {}).get("text", "")
            elif "imageMessage" in m: content = "[IMAGEM]"
            elif "audioMessage" in m: content = "[AUDIO]"
            
            if not content and "conversation" in msg: content = msg["conversation"]
            if not content: continue
            
            ts = msg.get("messageTimestamp")
            if not ts: continue
            dt = datetime.fromtimestamp(ts)
            
            if dt.date() != TARGET_DATE: continue
            if dt < START_TIME: continue
            
            if jid not in conversations: conversations[jid] = []
            conversations[jid].append({
                "time": dt.strftime("%H:%M:%S"),
                "sender": "ESCOLA" if key.get("fromMe") else "PAI/MAE",
                "text": content.strip().replace("\n", " ")
            })

    report_path = ROOT_DIR / "relatorios" / "RELATORIO_FINAL_PRECISO_15_05.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"=== RELATORIO DE AUDITORIA FINAL - BUSCA ATIVA 15/05/2026 ===\n")
        f.write(f"Metodo: Busca Individual por Contato (Deep Scan)\n")
        f.write(f"Contatos com atividade hoje: {len(conversations)}\n")
        f.write("-" * 60 + "\n\n")
        
        # Ordenar por nome do aluno para facilitar a leitura
        sorted_jids = sorted(conversations.keys(), key=lambda j: name_map.get(j, "Z-Desconhecido"))
        
        for jid in sorted_jids:
            msgs = conversations[jid]
            msgs.sort(key=lambda x: x["time"])
            
            student_name = name_map.get(jid, "Desconhecido")
            has_resp = any(m["sender"] == "PAI/MAE" for m in msgs)
            
            f.write(f"[{'V' if has_resp else ' '}] ALUNO: {student_name}\n")
            f.write(f"    JID: {jid}\n")
            for m in msgs:
                f.write(f"    {m['time']} | {m['sender']}: {m['text']}\n")
            f.write("-" * 50 + "\n")

    print(f"RELATORIO CONCLUIDO: {report_path}")

if __name__ == "__main__":
    run()
