"""
Worker de reprocessamento de mensagens UNRESOLVED.

Varre a tabela `responses` buscando registros com baixa confiança de identidade
e tenta reclassificá-los usando o motor de correlação atualizado (sessões + outbound).

Uso:
    python scripts/reprocess_unresolved_worker.py [--limit 100] [--dry-run]
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.infrastructure.supabase.repositories import SupabaseRepository  # noqa: E402
from app.application.session_service import ConversationSessionService  # noqa: E402
from app.application.identity_resolver import IdentityResolver  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("reprocess_worker")


def run(limit: int = 200, dry_run: bool = False) -> None:
    if not settings.supabase_url or not settings.supabase_key:
        logger.error("SUPABASE_URL e SUPABASE_KEY precisam estar definidos.")
        sys.exit(1)

    repo = SupabaseRepository()
    session_service = ConversationSessionService(repo)
    resolver = IdentityResolver(repo, session_service)

    logger.info(f"Buscando até {limit} respostas UNRESOLVED/LOW...")

    try:
        result = (
            repo.client.schema("busca_ativa_v2")
            .table("responses")
            .select("id, sender_jid, school_id, raw_message_id, body, identity_confidence, guardian_id, student_id, campaign_id")
            .in_("identity_confidence", ["UNRESOLVED", "LOW"])
            .limit(limit)
            .execute()
        )
        unresolved = result.data or []
    except Exception as e:
        logger.error(f"Erro ao buscar respostas: {e}")
        sys.exit(1)

    if not unresolved:
        logger.info("Nenhuma mensagem UNRESOLVED encontrada. Tudo ok!")
        return

    logger.info(f"Encontradas {len(unresolved)} mensagens para reprocessar.\n")

    total = len(unresolved)
    sucessos = 0
    permanece = 0
    erros = 0

    for i, resp in enumerate(unresolved, 1):
        resp_id = resp["id"]
        sender_jid = resp["sender_jid"]
        school_id = resp["school_id"]
        raw_msg_id = resp.get("raw_message_id")

        logger.info(f"[{i}/{total}] Reprocessando {resp_id} | sender={sender_jid}")

        # Buscar payload original no raw_inbound para obter stanza_id e push_name
        stanza_id = None
        push_name = None

        if raw_msg_id:
            try:
                raw_res = (
                    repo.client.schema("busca_ativa_v2")
                    .table("raw_inbound")
                    .select("payload")
                    .eq("message_id", raw_msg_id)
                    .limit(1)
                    .execute()
                )
                raw_rows = raw_res.data or []
                if raw_rows and raw_rows[0].get("payload"):
                    payload = raw_rows[0]["payload"]
                    data = payload.get("data", {})
                    push_name = data.get("pushName")
                    msg = data.get("message", {})
                    ctx = (
                        msg.get("extendedTextMessage", {}).get("contextInfo", {})
                        or msg.get("imageMessage", {}).get("contextInfo", {})
                        or {}
                    )
                    stanza_id = ctx.get("stanzaId")
            except Exception as e:
                logger.warning(f"  ⚠ Não foi possível buscar raw_inbound: {e}")

        # Resolver identidade com o motor atualizado
        try:
            identity = resolver.resolve_identity(
                sender_jid=sender_jid,
                stanza_id=stanza_id,
                school_id=school_id,
                push_name=push_name,
                message_text=resp.get("body"),
            )
        except Exception as e:
            logger.error(f"  ✗ Erro ao resolver identidade: {e}")
            erros += 1
            continue

        logger.info(f"  → Confiança: {identity.confidence} | guardian_id: {getattr(identity.guardian, 'id', None)}")

        if identity.confidence in ("HIGH", "MEDIUM"):
            if dry_run:
                logger.info(f"  [DRY-RUN] Seria atualizado para {identity.confidence}.")
                sucessos += 1
                continue

            guardian_id = identity.guardian.id if identity.guardian else None
            # A identidade resolvida pode trazer o message (outbound) associado
            message = getattr(identity, "message", None)
            campaign_id = message.campaign_id if message else None
            student_id = message.student_id if message else None

            update_payload: dict = {"identity_confidence": identity.confidence}
            if guardian_id:
                update_payload["guardian_id"] = guardian_id
            if campaign_id:
                update_payload["campaign_id"] = campaign_id
            if student_id:
                update_payload["student_id"] = student_id
            if message:
                update_payload["message_id"] = message.id

            try:
                repo.client.schema("busca_ativa_v2").table("responses").update(
                    update_payload
                ).eq("id", resp_id).execute()
                logger.info(f"  ✓ Atualizado com sucesso.")
                sucessos += 1
            except Exception as e:
                logger.error(f"  ✗ Erro ao persistir atualização: {e}")
                erros += 1
        else:
            logger.info(f"  ~ Permanece UNRESOLVED.")
            permanece += 1

    logger.info(
        f"\n{'=' * 55}\n"
        f"Reprocessamento concluído!\n"
        f"  ✓ Resolvidos   : {sucessos}/{total}\n"
        f"  ~ Não resolvidos: {permanece}/{total}\n"
        f"  ✗ Erros        : {erros}/{total}\n"
        f"{'=' * 55}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reprocessa mensagens com identidade não resolvida.")
    parser.add_argument("--limit", type=int, default=200, help="Número máximo de registros a processar (padrão: 200).")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Simula o reprocessamento sem gravar.")
    args = parser.parse_args()
    run(limit=args.limit, dry_run=args.dry_run)
