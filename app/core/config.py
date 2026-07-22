from pathlib import Path
import os

from dotenv import load_dotenv


load_dotenv()

# Bypass Cisco Umbrella / OpenDNS block on cpniwvghxlkposaeyboa.supabase.co
import socket
_original_getaddrinfo = socket.getaddrinfo

def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if host == "cpniwvghxlkposaeyboa.supabase.co":
        results = []
        for ip in ["104.18.38.10", "172.64.149.246"]:
            try:
                results.extend(_original_getaddrinfo(ip, port, family, type, proto, flags))
            except Exception:
                pass
        if results:
            return results
    return _original_getaddrinfo(host, port, family, type, proto, flags)

socket.getaddrinfo = _patched_getaddrinfo


class Settings:
    app_name: str = os.getenv("APP_NAME", "busca-ativa-v2")
    debug: bool = os.getenv("DEBUG", "true").lower() == "true"
    school_name: str = os.getenv("SCHOOL_NAME", "Escola").strip() or "Escola"
    default_school_id: str = os.getenv("DEFAULT_SCHOOL_ID", "").strip()

    supabase_url: str = os.getenv("SUPABASE_URL", "").strip()
    supabase_key: str = os.getenv("SUPABASE_KEY", "").strip()

    evolution_api_url: str = os.getenv("EVOLUTION_API_URL", "").strip()
    evolution_api_key: str = os.getenv("EVOLUTION_API_KEY", "").strip()
    evolution_api_instance: str = os.getenv("EVOLUTION_API_INSTANCE", "").strip()
    evolution_timeout_seconds: float = float(os.getenv("EVOLUTION_TIMEOUT_SECONDS", "30"))

    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    project_root: Path = Path(__file__).resolve().parents[2]
    consolidated_report_path: str = os.getenv("CONSOLIDATED_REPORT_PATH", "relatorios/Relatorio_Consolidado_BuscaAtiva.xlsx").strip()
    n8n_webhook_url: str = os.getenv("N8N_WEBHOOK_URL", "http://localhost:5678/webhook/triagem").strip()
    n8n_chat_webhook_url: str = os.getenv("N8N_CHAT_WEBHOOK_URL", "http://localhost:5678/webhook/chat-interaction").strip()
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()

    # Feature Flags
    use_session_correlation: bool = os.getenv("USE_SESSION_CORRELATION", "true").lower() == "true"
    enable_conversational_agent: bool = os.getenv("ENABLE_CONVERSATIONAL_AGENT", "true").lower() == "true"
    allow_unresolved_conversational_agent: bool = os.getenv("ALLOW_UNRESOLVED_CONVERSATIONAL_AGENT", "true").lower() == "true"



settings = Settings()
