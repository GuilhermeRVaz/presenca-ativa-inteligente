#!/usr/bin/env python3
"""
Script para verificar mensagens raw_inbound não processadas.
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.core.config import settings
from app.infrastructure.supabase.repositories import SupabaseRepository

def check_raw_inbound():
    print("Verificando mensagens raw_inbound nao processadas...")
    try:
        repo = SupabaseRepository()
        unprocessed = repo.list_unprocessed_raw_inbound(limit=10)

        if not unprocessed:
            print("Nenhuma mensagem raw_inbound nao processada encontrada.")
            return

        print(f"Encontradas {len(unprocessed)} mensagens nao processadas:")
        for msg in unprocessed:
            print(f"- ID: {msg['id']}, Message ID: {msg['message_id']}, Sender: {msg['sender_jid']}")

    except Exception as e:
        print(f"Erro ao verificar raw_inbound: {e}")

if __name__ == "__main__":
    check_raw_inbound()