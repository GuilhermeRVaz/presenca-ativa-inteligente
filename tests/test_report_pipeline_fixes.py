from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.application.analytics.campaign_analytics import CampaignAnalytics
from app.application.analytics.conversation_reconciler import ConversationReconciler
from app.application.analytics.conversation_summarizer import OccurrenceStatus, RiskLevel
from scripts.consolidate_campaign_report import (
    ChatEvent,
    _parse_db_timestamp,
    _parse_evo_timestamp,
)


def test_evolution_and_db_timestamps_are_both_timezone_aware() -> None:
    evo_dt = _parse_evo_timestamp(1716300000)
    db_dt = _parse_db_timestamp("2026-05-21T14:20:00+00:00")

    assert evo_dt is not None
    assert evo_dt.tzinfo is not None
    assert db_dt.tzinfo is not None

    events = [
        ChatEvent(timestamp=db_dt, sender="Responsavel", body="ok", type="INBOUND"),
        ChatEvent(timestamp=evo_dt, sender="Escola", body="msg", type="OUTBOUND_INITIAL"),
    ]

    sorted(events, key=lambda event: event.timestamp)


def test_campaign_analytics_response_rate_is_fraction_not_percent() -> None:
    analytics = CampaignAnalytics.__new__(CampaignAnalytics)
    analytics.client = _FakeClient()
    analytics.reconciler = SimpleNamespace(reconcile_unresolved_responses=lambda *args, **kwargs: {})
    analytics.builder = SimpleNamespace(
        build_conversations=lambda school_id, campaign_id: [object() for _ in range(7)]
    )
    analytics.summarizer = SimpleNamespace(summarize=lambda thread: _fake_occurrence())

    report = analytics.generate_report("school-1", "campaign-1")

    assert report.operational.messages_sent_success == 32
    assert report.operational.responses_received == 7
    assert report.operational.response_rate == 7 / 32


def test_reconciler_expands_lid_to_mapped_whatsapp_jid() -> None:
    reconciler = ConversationReconciler(SimpleNamespace(client=_FakeIdentityClient()))

    candidates = reconciler._candidate_jids_for_sender("123@lid")

    assert "123@lid" in candidates
    assert "5514999999999@s.whatsapp.net" in candidates


def _fake_occurrence():
    return SimpleNamespace(
        status=OccurrenceStatus.JUSTIFICADO,
        risk_level=RiskLevel.BAIXO,
        needs_followup=False,
        has_medical_document=False,
        model_dump=lambda: {},
    )


class _FakeClient:
    def schema(self, name):
        return self

    def table(self, name):
        return _FakeQuery(name)


class _FakeQuery:
    def __init__(self, table_name):
        self.table_name = table_name

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def single(self):
        return self

    def execute(self):
        if self.table_name == "messages":
            return SimpleNamespace(
                data=[
                    {"status": "sent", "student_id": f"student-{idx}", "last_error": None}
                    for idx in range(32)
                ]
            )
        if self.table_name == "campaigns":
            return SimpleNamespace(data={"name": "Campanha Teste"})
        return SimpleNamespace(data=[])


class _FakeIdentityClient:
    def schema(self, name):
        return self

    def table(self, name):
        return self

    def select(self, *args, **kwargs):
        return self

    def or_(self, *args, **kwargs):
        return self

    def execute(self):
        return SimpleNamespace(
            data=[
                {
                    "lid_jid": "123@lid",
                    "wa_jid": "5514999999999@s.whatsapp.net",
                }
            ]
        )
