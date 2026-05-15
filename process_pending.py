#!/usr/bin/env python3
"""
Script para processar mensagens raw_inbound pendentes.
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.application.inbound_service import InboundService
from app.infrastructure.supabase.repositories import SupabaseRepository
from app.core.config import settings

def process_pending_messages():
    print("Processando mensagens raw_inbound pendentes...")
    try:
        repo = SupabaseRepository()
        service = InboundService(repository=repo)

        # Pegar mensagens não processadas
        unprocessed = repo.list_unprocessed_raw_inbound(limit=1)
        if not unprocessed:
            print("Nenhuma mensagem pendente encontrada.")
            return

        processed_count = 0
        for msg in unprocessed:
            print(f"Processando mensagem: {msg['id']}")

            # Simular o payload do webhook
            payload = msg['payload']

            try:
                # Processar
                result = service.process_recorded(payload=payload, school_id=msg['school_id'])

                print(f"Resultado: {result.status}")
                if result.response_id:
                    print(f"Response ID: {result.response_id}")
                    processed_count += 1
            except Exception as e:
                print(f"Erro ao processar {msg['id']}: {e}")

        print(f"Total processadas com sucesso: {processed_count}/{len(unprocessed)}")

    except Exception as e:
        print(f"Erro geral: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    process_pending_messages()