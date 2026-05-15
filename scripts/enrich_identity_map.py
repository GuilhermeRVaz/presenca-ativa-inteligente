import os
import sys
import logging
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
load_dotenv()

from app.infrastructure.supabase.repositories import SupabaseRepository

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

def main():
    repo = SupabaseRepository()
    
    # Busca todas as respostas com HIGH confidence
    logger.info("Buscando responses com identity_confidence = 'HIGH'...")
    responses_res = repo.client.schema("busca_ativa_v2").table("responses").select(
        "id, school_id, sender_jid, student_id, guardian_id, identity_confidence"
    ).eq("identity_confidence", "HIGH").execute()
    
    if not responses_res.data:
        logger.info("Nenhuma response HIGH encontrada.")
        return
        
    logger.info(f"Encontradas {len(responses_res.data)} responses HIGH. Processando...")
    
    new_lids = 0
    updated_responses = 0
    
    for resp in responses_res.data:
        school_id = resp.get("school_id")
        sender_jid = resp.get("sender_jid")
        student_id = resp.get("student_id")
        guardian_id = resp.get("guardian_id")
        
        # Se tem student_id mas não tem guardian_id, vamos tentar descobrir o guardian_id primário
        if student_id and not guardian_id:
            sg_res = repo.client.schema("busca_ativa_v2").table("student_guardians").select(
                "guardian_id"
            ).eq("student_id", student_id).eq("is_primary", True).execute()
            
            if sg_res.data:
                guardian_id = sg_res.data[0]["guardian_id"]
                # Atualiza a response para ter o guardian_id
                repo.client.schema("busca_ativa_v2").table("responses").update(
                    {"guardian_id": guardian_id}
                ).eq("id", resp["id"]).execute()
                updated_responses += 1
                logger.info(f"Atualizado guardian_id para response {resp['id']}")
        
        # Se temos o guardian_id, vamos popular o phone_identity_map
        if guardian_id and sender_jid:
            lid_jid = sender_jid if "@lid" in sender_jid else None
            wa_jid = sender_jid if "@s.whatsapp.net" in sender_jid else None
            
            try:
                repo.upsert_phone_identity(
                    school_id=school_id,
                    lid_jid=lid_jid,
                    wa_jid=wa_jid,
                    phone_e164=None,
                    guardian_id=guardian_id,
                    confidence="HIGH",
                    source="inbound"
                )
                new_lids += 1
            except Exception as e:
                logger.error(f"Erro ao upsert phone identity para {sender_jid}: {e}")
                
    logger.info("--- MÉTRICAS DIÁRIAS (Enriquecimento) ---")
    logger.info(f"Responses HIGH processadas: {len(responses_res.data)}")
    logger.info(f"Responses corrigidas com guardian_id: {updated_responses}")
    logger.info(f"Novos @lid aprendidos / atualizados no mapa: {new_lids}")
    logger.info("-----------------------------------------")

if __name__ == "__main__":
    main()
