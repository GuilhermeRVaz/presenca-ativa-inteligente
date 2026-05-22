import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.infrastructure.supabase.repositories import SupabaseRepository
from app.application.inbound_service import InboundService

class MockEvolutionGateway:
    def send_text(self, to_jid: str, text: str) -> dict:
        return {"status": "success"}

def main():
    r = SupabaseRepository()
    svc = InboundService(repository=r)
    
    # Mock external operations to avoid side effects and timeouts
    svc.evolution_gateway = MockEvolutionGateway()
    svc._trigger_n8n_triagem = lambda *args, **kwargs: False
    
    print("Buscando mensagens raw_inbound nao processadas...")
    rows = r.list_unprocessed_raw_inbound(limit=200)
    total = len(rows)
    print(f"Total a processar: {total}")
    
    processed_count = 0
    failed_count = 0
    
    def process_single(index, rec):
        payload = rec.get("payload") or {}
        message_id = rec.get("message_id")
        school_id = rec.get("school_id") or None
        
        try:
            result = svc.process_recorded(payload=payload, school_id=school_id)
            print(f"[{index}/{total}] -> {message_id} Status: {result.status} | Confidence: {getattr(result, 'identity_confidence', 'NONE')}")
            return True, result.status == "processed"
        except Exception as e:
            print(f"[{index}/{total}] -> {message_id} ERRO: {e}")
            return False, False

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_single, i, row): row for i, row in enumerate(rows, 1)}
        for future in as_completed(futures):
            success, is_processed = future.result()
            if success and is_processed:
                processed_count += 1
            else:
                failed_count += 1
            
    print("\nResumo do Reprocessamento:")
    print(f"  Processados com sucesso: {processed_count}")
    print(f"  Falhas/Ignorados: {failed_count}")

if __name__ == "__main__":
    main()
