import datetime
from typing import Any, Dict

from app.core.logging import logger
from app.infrastructure.supabase.repositories import SupabaseRepository


class ConversationReconciler:
    """
    Fecha retrospectivamente respostas sem identidade/campanha usando o historico
    recente de mensagens outbound e o mapa LID <-> WhatsApp.
    """

    def __init__(self, repository: SupabaseRepository):
        self.repository = repository
        self.client = repository.client

    def reconcile_unresolved_responses(
        self,
        window_hours: int = 48,
        *,
        school_id: str | None = None,
        campaign_id: str | None = None,
    ) -> Dict[str, Any]:
        metrics = {
            "unresolved_found": 0,
            "reconciled_success": 0,
            "reconciled_failed": 0,
            "skipped_ambiguous": 0,
        }

        try:
            logger.info("reconciler_start", window_hours=window_hours)
            responses_query = (
                self.client.schema("busca_ativa_v2")
                .table("responses")
                .select("*")
                .or_("identity_confidence.eq.UNRESOLVED,student_id.is.null")
            )
            if school_id:
                responses_query = responses_query.eq("school_id", school_id)
            if campaign_id:
                responses_query = responses_query.eq("campaign_id", campaign_id)
            responses_query = responses_query.execute()

            unresolved = responses_query.data or []
            metrics["unresolved_found"] = len(unresolved)

            if not unresolved:
                logger.info("reconciler_no_pending_responses")
                return metrics

            now = datetime.datetime.now(datetime.timezone.utc)
            window_start = (now - datetime.timedelta(hours=window_hours)).isoformat()
            outbound_cache: dict[tuple[Any, ...], dict[str, Any] | str | None] = {}

            for resp in unresolved:
                sender_jid = str(resp.get("sender_jid") or "").strip()
                if not sender_jid:
                    continue

                school_id = resp.get("school_id")
                campaign_id = resp.get("campaign_id")
                guardian_id = resp.get("guardian_id")
                cache_key = (sender_jid, school_id, campaign_id, guardian_id)

                if cache_key not in outbound_cache:
                    outbound_cache[cache_key] = self._find_recent_outbound(
                        sender_jid=sender_jid,
                        school_id=school_id,
                        campaign_id=campaign_id,
                        guardian_id=guardian_id,
                        window_start=window_start,
                    )

                last_outbound = outbound_cache.get(cache_key)

                if last_outbound == "AMBIGUOUS":
                    metrics["skipped_ambiguous"] += 1
                    logger.warning("reconciler_ambiguous_outbound_skipped", sender_jid=sender_jid)
                    continue

                if not last_outbound:
                    metrics["reconciled_failed"] += 1
                    logger.info("reconciler_no_outbound_match", sender_jid=sender_jid)
                    continue

                student_id = last_outbound.get("student_id")
                guardian_id = last_outbound.get("guardian_id")
                campaign_id = last_outbound.get("campaign_id")
                school_id = last_outbound.get("school_id")
                message_id = last_outbound.get("id")

                if not student_id:
                    metrics["reconciled_failed"] += 1
                    logger.info("reconciler_outbound_without_student", sender_jid=sender_jid)
                    continue

                update_data = {
                    "student_id": student_id,
                    "guardian_id": guardian_id,
                    "campaign_id": campaign_id,
                    "message_id": message_id,
                    "identity_confidence": "HIGH",
                }

                (
                    self.client.schema("busca_ativa_v2")
                    .table("responses")
                    .update(update_data)
                    .eq("id", resp["id"])
                    .execute()
                )

                try:
                    phone_e164 = str(last_outbound.get("wa_jid") or sender_jid).replace(
                        "@s.whatsapp.net", ""
                    )
                    lid_jid = sender_jid if sender_jid.endswith("@lid") else None
                    wa_jid = last_outbound.get("wa_jid") or sender_jid
                    self.repository.upsert_phone_identity(
                        school_id=school_id,
                        lid_jid=lid_jid,
                        wa_jid=wa_jid,
                        phone_e164=phone_e164,
                        guardian_id=guardian_id,
                        confidence="HIGH",
                        source="reconciler",
                    )
                except Exception as e:
                    logger.error(
                        "reconciler_phone_identity_update_error",
                        error=str(e),
                        wa_jid=sender_jid,
                    )

                metrics["reconciled_success"] += 1
                logger.info(
                    "reconciled_response",
                    response_id=resp["id"],
                    wa_jid=sender_jid,
                    student_id=student_id,
                    campaign_id=campaign_id,
                )

            logger.info("reconciler_finished", metrics=metrics)
            return metrics

        except Exception as e:
            logger.error("reconciliation_pipeline_failed", error=str(e))
            raise e

    def _find_recent_outbound(
        self,
        *,
        sender_jid: str,
        school_id: str | None,
        campaign_id: str | None,
        guardian_id: str | None,
        window_start: str,
    ) -> dict[str, Any] | str | None:
        candidate_jids = self._candidate_jids_for_sender(sender_jid)
        query = (
            self.client.schema("busca_ativa_v2")
            .table("messages")
            .select("id, school_id, campaign_id, student_id, guardian_id, wa_jid, created_at")
        )
        if school_id:
            query = query.eq("school_id", school_id)
        if campaign_id:
            query = query.eq("campaign_id", campaign_id)
        if guardian_id:
            query = query.eq("guardian_id", guardian_id)
        else:
            query = query.in_("wa_jid", candidate_jids)

        result = (
            query.gte("created_at", window_start)
            .order("created_at", desc=True)
            .limit(3)
            .execute()
        )
        outbounds = result.data or []
        if not outbounds:
            return None

        student_ids = {row.get("student_id") for row in outbounds if row.get("student_id")}
        if len(student_ids) > 1:
            return "AMBIGUOUS"
        return outbounds[0]

    def _candidate_jids_for_sender(self, sender_jid: str) -> list[str]:
        candidates = {sender_jid}
        try:
            identity_rows = (
                self.client.schema("busca_ativa_v2")
                .table("phone_identity_map")
                .select("wa_jid, lid_jid")
                .or_(f"lid_jid.eq.{sender_jid},wa_jid.eq.{sender_jid}")
                .execute()
                .data
                or []
            )
            for row in identity_rows:
                if row.get("wa_jid"):
                    candidates.add(row["wa_jid"])
                if row.get("lid_jid"):
                    candidates.add(row["lid_jid"])
        except Exception as exc:
            logger.warning(
                "reconciler_identity_map_lookup_failed",
                sender_jid=sender_jid,
                error=str(exc),
            )

        if sender_jid.endswith("@lid"):
            phone_part = sender_jid.split("@", 1)[0]
            if phone_part.isdigit() and len(phone_part) >= 10:
                candidates.add(f"{phone_part}@s.whatsapp.net")

        return sorted(candidates)
