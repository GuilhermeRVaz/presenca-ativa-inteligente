"""
Script de importação de dados legados para o sistema de identificação por sessão.

Lê todos os responsáveis (guardians) e seus telefones/JIDs cadastrados
e popula/atualiza a tabela phone_identity_map para garantir que o sistema
de correlação tenha uma base sólida de dados históricos.

Uso:
    python scripts/import_legacy_data.py [--dry-run]
"""

import argparse
import logging
import sys
from pathlib import Path

# Adiciona o diretório raiz ao PYTHONPATH
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.infrastructure.supabase.repositories import SupabaseRepository  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("import_legacy")


def normalize_phone(phone: str | None) -> str | None:
    """Remove caracteres não numéricos e aplica formato E.164 básico."""
    if not phone:
        return None
    digits = "".join(c for c in phone if c.isdigit())
    if not digits:
        return None
    # Garante prefixo 55 (Brasil)
    if not digits.startswith("55") and len(digits) <= 11:
        digits = "55" + digits
    return "+" + digits


def phone_to_jid(phone_e164: str | None) -> str | None:
    """Converte um telefone E.164 para JID WhatsApp padrão."""
    if not phone_e164:
        return None
    digits = phone_e164.lstrip("+")
    return f"{digits}@s.whatsapp.net"


def run(dry_run: bool = False) -> None:
    if not settings.supabase_url or not settings.supabase_key:
        logger.error("SUPABASE_URL e SUPABASE_KEY precisam estar definidos.")
        sys.exit(1)

    repo = SupabaseRepository()
    logger.info("Conectado ao Supabase. Iniciando importação de dados legados...")

    # 1. Buscar todos os guardians com telefone e/ou JID cadastrado
    try:
        result = (
            repo.client.schema("busca_ativa_v2")
            .table("guardians")
            .select("id, name, phone_e164, wa_jid, school_id")
            .execute()
        )
        guardians = result.data or []
    except Exception as e:
        logger.error(f"Erro ao buscar guardians: {e}")
        sys.exit(1)

    logger.info(f"Encontrados {len(guardians)} responsáveis para processar.")

    upserted = 0
    skipped = 0
    errors = 0

    for g in guardians:
        guardian_id = g["id"]
        school_id = g.get("school_id")
        name = g.get("name", "")

        phone_raw = g.get("phone_e164")
        wa_jid = g.get("wa_jid")

        phone_e164 = normalize_phone(phone_raw)
        derived_jid = phone_to_jid(phone_e164)

        # Usa o JID cadastrado diretamente se disponível, caso contrário deriva do telefone
        canonical_jid = wa_jid or derived_jid

        if not canonical_jid:
            logger.debug(f"[SKIP] Guardian {guardian_id} ({name}) sem telefone ou JID.")
            skipped += 1
            continue

        logger.info(
            f"[{'DRY-RUN' if dry_run else 'UPSERT'}] "
            f"Guardian {guardian_id} ({name}) → jid={canonical_jid}, phone={phone_e164}"
        )

        if dry_run:
            upserted += 1
            continue

        try:
            # Registra o mapa canônico phone -> guardian
            repo.client.schema("busca_ativa_v2").rpc(
                "upsert_phone_identity",
                {
                    "p_school_id": school_id,
                    "p_phone_e164": phone_e164,
                    "p_wa_jid": canonical_jid,
                    "p_guardian_id": guardian_id,
                    "p_confidence": "HIGH",
                    "p_source": "legacy_import",
                },
            ).execute()

            # Se o guardian tiver wa_jid diferente do derivado, registra os dois
            if wa_jid and wa_jid != canonical_jid:
                repo.client.schema("busca_ativa_v2").rpc(
                    "upsert_phone_identity",
                    {
                        "p_school_id": school_id,
                        "p_phone_e164": phone_e164,
                        "p_wa_jid": wa_jid,
                        "p_guardian_id": guardian_id,
                        "p_confidence": "HIGH",
                        "p_source": "legacy_import_wa_jid",
                    },
                ).execute()

            upserted += 1

        except Exception as e:
            logger.error(f"Erro ao upsert guardian {guardian_id}: {e}")
            errors += 1

    logger.info(
        f"\n{'=' * 50}\n"
        f"Importação concluída!\n"
        f"  Processados : {upserted}\n"
        f"  Pulados     : {skipped}\n"
        f"  Erros       : {errors}\n"
        f"{'=' * 50}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Importa dados legados de guardians para phone_identity_map.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Apenas lista o que seria feito sem gravar no banco.",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run)
