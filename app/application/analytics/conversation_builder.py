from datetime import datetime
from typing import List, Dict, Optional
from pydantic import BaseModel
from app.infrastructure.supabase.repositories import SupabaseRepository
import logging

logger = logging.getLogger(__name__)

class MessageNode(BaseModel):
    id: str
    sender_jid: str
    body: str
    received_at: datetime
    is_outbound: bool = False
    
class ConversationThread(BaseModel):
    sender_jid: str
    campaign_id: Optional[str]
    student_id: Optional[str]
    guardian_id: Optional[str]
    messages: List[MessageNode]
    start_time: datetime
    end_time: datetime
    duration_seconds: int
    message_count: int

class ConversationBuilder:
    """
    Camada Python responsável por reconstruir o histórico de diálogos a partir das respostas.
    - responses -> group by sender_jid -> order by received_at -> monta conversa
    """
    def __init__(self, repository: SupabaseRepository):
        self.repository = repository
        self.client = repository.client
        
    def _is_noise(self, text: str) -> bool:
        if not text:
            return True
        t = text.strip().lower()
        if not t:
            return True
        # Filtros de ruído para ignorar mensagens curtas sem contexto de justificativa
        noise_words = {
            "ok", "ok.", "ok!", "obrigado", "obrigada", "obg",
            "bom dia", "boa tarde", "boa noite",
            "joia", "sim", "nao", "não", "ta", "tá", "👍"
        }
        if t in noise_words:
            return True
        return False

    def build_conversations(self, school_id: str, campaign_id: Optional[str] = None) -> List[ConversationThread]:
        """
        Reconstrói o histórico de diálogos a partir de busca_ativa_v2.responses.
        """
        query = self.client.schema("busca_ativa_v2").table("responses").select(
            "id, sender_jid, body, received_at, campaign_id, student_id, guardian_id"
        ).eq("school_id", school_id)
        
        if campaign_id:
            if isinstance(campaign_id, list):
                query = query.in_("campaign_id", campaign_id)
            elif isinstance(campaign_id, str) and "," in campaign_id:
                campaign_ids = [c.strip() for c in campaign_id.split(",")]
                query = query.in_("campaign_id", campaign_ids)
            else:
                query = query.eq("campaign_id", campaign_id)
            
        # Busca todas as respostas
        res = query.order("received_at", desc=False).execute()
        
        # Agrupar por sender_jid (ou (sender_jid, campaign_id))
        groups: Dict[str, List[dict]] = {}
        for row in res.data:
            if self._is_noise(row.get("body", "")):
                continue
                
            jid = row.get("sender_jid")
            if not jid:
                continue
            if jid not in groups:
                groups[jid] = []
            groups[jid].append(row)
            
        conversations = []
        for jid, msgs in groups.items():
            if not msgs:
                continue
                
            nodes = []
            for m in msgs:
                received_at_str = m.get("received_at")
                if received_at_str:
                    try:
                        received_at = datetime.fromisoformat(received_at_str.replace("Z", "+00:00"))
                    except Exception:
                        received_at = datetime.now()
                else:
                    received_at = datetime.now()
                    
                nodes.append(MessageNode(
                    id=m.get("id", ""),
                    sender_jid=jid,
                    body=m.get("body", ""),
                    received_at=received_at,
                    is_outbound=False
                ))
            
            # Garantir ordenação
            nodes.sort(key=lambda x: x.received_at)
            
            # Utiliza os metadados vinculados à última mensagem recebida (maior contexto)
            last_msg = msgs[-1]
            c_id = last_msg.get("campaign_id")
            s_id = last_msg.get("student_id")
            g_id = last_msg.get("guardian_id")
            
            start_time = nodes[0].received_at
            end_time = nodes[-1].received_at
            duration = int((end_time - start_time).total_seconds())
            
            conversations.append(ConversationThread(
                sender_jid=jid,
                campaign_id=c_id,
                student_id=s_id,
                guardian_id=g_id,
                messages=nodes,
                start_time=start_time,
                end_time=end_time,
                duration_seconds=duration,
                message_count=len(nodes)
            ))
            
        return conversations
