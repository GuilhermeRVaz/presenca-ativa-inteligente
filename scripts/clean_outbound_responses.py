import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")

from app.infrastructure.supabase.repositories import SupabaseRepository

def clean_fake_outbound_responses():
    repo = SupabaseRepository()
    client = repo.client.schema("busca_ativa_v2")

    print("=== INICIANDO LIMPEZA DE RESPOSTAS FALSAS DE OUTBOUND ===")
    
    initial_template_markers = [
        "aqui e da", "aqui é da", "para justificar, responda",
        "esteve ausente", "faltou nos dias", "ausencia de", "ausência de",
        "poderia nos informar o motivo", "codigo do aluno:", "código do aluno:"
    ]

    # Buscar respostas que começam com 'outbound-'
    resps = client.table("responses").select("id, raw_message_id, body, sender_jid, student_id").like("raw_message_id", "outbound-%").execute().data or []
    
    print(f"Total de respostas 'outbound-' encontradas: {len(resps)}")

    deleted_count = 0
    for r in resps:
        body_lower = (r.get("body") or "").lower()
        if any(marker in body_lower for marker in initial_template_markers):
            row_id = r.get("id")
            try:
                client.table("responses").delete().eq("id", row_id).execute()
                deleted_count += 1
                print(f" [DELETADO] ID {row_id} - Raw: {r.get('raw_message_id')} - Texto: {r.get('body')[:60]}...")
            except Exception as e:
                print(f" [ERRO DELETAR] ID {row_id}: {e}")

    print(f"=== LIMPEZA CONCLUÍDA: {deleted_count} registros falsos deletados ===")

if __name__ == "__main__":
    clean_fake_outbound_responses()
