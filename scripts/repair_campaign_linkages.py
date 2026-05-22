import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.infrastructure.supabase.repositories import SupabaseRepository

def main():
    r = SupabaseRepository()
    client = r.client.schema('busca_ativa_v2')
    c_id = '8df45b2c-6973-4138-b705-ee6e15639f0d' # Busca Ativa — Faltas dia 15/05/2026
    
    # Buscar respostas vinculadas a esta campanha que foram recebidas antes de 15/05/2026
    resps = client.table('responses').select('id, received_at, body').eq('campaign_id', c_id).lt('received_at', '2026-05-15T00:00:00+00:00').execute().data or []
    print(f"Encontradas {len(resps)} respostas antigas (de abril/outros dias) vinculadas incorretamente à campanha de 15/05/2026.")
    
    if not resps:
        print("Nenhuma resposta antiga encontrada para reparar.")
        return
        
    print("Iniciando a limpeza de vínculos incorretos...")
    for i, resp in enumerate(resps, 1):
        client.table('responses').update({'campaign_id': None}).eq('id', resp['id']).execute()
        if i % 50 == 0 or i == len(resps):
            print(f"  -> {i}/{len(resps)} atualizadas...")
            
    print("Reparação concluída com sucesso! Os dados de estatística agora estarão corretos.")

if __name__ == '__main__':
    main()
