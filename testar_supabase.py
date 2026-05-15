#!/usr/bin/env python3
"""
Script para testar conectividade com Supabase e verificar tabelas.
"""
import sys
import os
from pathlib import Path

# Adicionar o diretório raiz do projeto ao sys.path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.core.config import settings
from app.infrastructure.supabase.repositories import SupabaseRepository

def test_supabase_connection():
    print("Testando conexao com Supabase...")
    print(f"URL: {settings.supabase_url}")
    print(f"Key: {'*' * len(settings.supabase_key) if settings.supabase_key else 'Vazia'}")

    if not settings.supabase_url or not settings.supabase_key:
        print("Credenciais Supabase nao configuradas!")
        return False

    try:
        repo = SupabaseRepository()
        # Testar conexão básica - tentar pegar uma campanha ativa
        campaign_id = repo.get_active_campaign_for_today(school_id=settings.default_school_id or "school-1")
        print(f"Conexao OK. Campanha ativa hoje: {campaign_id}")

        # Testar se consegue ler da tabela responses
        try:
            response = repo.client.schema("busca_ativa_v2").table("responses").select("*").limit(1).execute()
            print(f"Tabela responses acessivel. {len(response.data)} registros encontrados (limite 1).")
        except Exception as e:
            print(f"Erro ao acessar tabela responses: {e}")

        # Testar se consegue contar registros
        try:
            count_response = repo.client.schema("busca_ativa_v2").table("responses").select("*", count="exact").limit(1).execute()
            total = count_response.count
            print(f"Total de registros em responses: {total}")
        except Exception as e:
            print(f"Erro ao contar registros: {e}")

        return True
    except Exception as e:
        print(f"Falha na conexao: {e}")
        return False

if __name__ == "__main__":
    success = test_supabase_connection()
    sys.exit(0 if success else 1)