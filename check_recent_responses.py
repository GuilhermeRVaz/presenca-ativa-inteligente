#!/usr/bin/env python3
"""
Script para verificar mensagens processadas recentemente.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.core.config import settings
from app.infrastructure.supabase.repositories import SupabaseRepository

def check_recent_responses():
    print("Verificando respostas processadas recentemente...")
    try:
        repo = SupabaseRepository()

        # Buscar últimas 10 respostas
        response = repo.client.schema("busca_ativa_v2").table("responses").select("*").order("received_at", desc=True).limit(10).execute()

        if not response.data:
            print("Nenhuma resposta recente encontrada.")
            return

        print(f"Encontradas {len(response.data)} respostas recentes:")
        for resp in response.data:
            reason = resp.get('reason', 'NULL')
            confidence = resp.get('identity_confidence', 'N/A')
            print(f"- ID: {resp['id'][:8]}..., Body: {resp['body'][:50]}..., Reason: {reason}, Confidence: {confidence}")

    except Exception as e:
        print(f"Erro ao verificar respostas recentes: {e}")

if __name__ == "__main__":
    check_recent_responses()