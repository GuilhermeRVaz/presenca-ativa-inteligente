from pathlib import Path
import os

from dotenv import load_dotenv


load_dotenv()


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
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()

    # Feature Flags
    use_session_correlation: bool = os.getenv("USE_SESSION_CORRELATION", "true").lower() == "true"


settings = Settings()
