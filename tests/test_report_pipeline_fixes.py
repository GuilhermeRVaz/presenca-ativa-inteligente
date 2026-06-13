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


class _FakeRepository:
    def __init__(self, client):
        self.client = client

    def _execute_with_retry(self, func, operation=None):
        return func()


def test_campaign_analytics_response_rate_is_fraction_not_percent() -> None:
    analytics = CampaignAnalytics.__new__(CampaignAnalytics)
    analytics.client = _FakeClient()
    analytics.repository = _FakeRepository(analytics.client)
    analytics.reconciler = SimpleNamespace(reconcile_unresolved_responses=lambda *args, **kwargs: {})
    analytics.builder = SimpleNamespace(
        build_conversations=lambda school_id, campaign_id: [
            SimpleNamespace(student_id=f"student-{idx}", sender_jid=f"jid-{idx}", campaign_id="campaign-1")
            for idx in range(7)
        ]
    )
    analytics.summarizer = SimpleNamespace(
        summarize=lambda thread: SimpleNamespace(
            status=OccurrenceStatus.JUSTIFICADO,
            risk_level=RiskLevel.BAIXO,
            needs_followup=False,
            has_medical_document=False,
            student_id=thread.student_id,
            sender_jid=thread.sender_jid,
            campaign_id=thread.campaign_id,
            model_dump=lambda: {},
        )
    )

    report = analytics.generate_report("school-1", "campaign-1")

    # In our _FakeQuery for messages, we mock 32 messages for students f"student-{idx}" where idx is 0 to 31.
    # Therefore, students student-0 to student-6 are in the targeted set, so total_targeted = 32.
    assert report.operational.total_students_targeted == 32
    assert report.operational.messages_sent_success == 32
    assert report.operational.responses_received == 7
    assert report.operational.response_rate == 7 / 32


def test_reconciler_expands_lid_to_mapped_whatsapp_jid() -> None:
    fake_client = _FakeIdentityClient()
    fake_repo = _FakeRepository(fake_client)
    reconciler = ConversationReconciler(fake_repo)

    candidates = reconciler._candidate_jids_for_sender("123@lid")

    assert "123@lid" in candidates
    assert "5514999999999@s.whatsapp.net" in candidates


def _fake_occurrence():
    return SimpleNamespace(
        status=OccurrenceStatus.JUSTIFICADO,
        risk_level=RiskLevel.BAIXO,
        needs_followup=False,
        has_medical_document=False,
        student_id="student-0",
        sender_jid="5514999999999@s.whatsapp.net",
        campaign_id="campaign-1",
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

    def in_(self, *args, **kwargs):
        return self

    def or_(self, *args, **kwargs):
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
            return SimpleNamespace(data=[{"id": "campaign-1", "name": "Campanha Teste", "absence_days": "10/06/2026", "campaign_type": "primary"}])
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


def test_regression_june_10_campaign_group() -> None:
    # Set up client and query mocks simulating the real stats from June 10, 2026:
    # 25 unique students targeted.
    # 20 responses received.
    # 17 occurrences classified as JUSTIFICADO.
    # 5 without response.
    
    class _June10FakeQuery:
        def __init__(self, table_name):
            self.table_name = table_name

        def select(self, *args, **kwargs):
            return self

        def eq(self, *args, **kwargs):
            return self

        def in_(self, *args, **kwargs):
            return self

        def or_(self, *args, **kwargs):
            return self

        def single(self):
            return self

        def execute(self):
            if self.table_name == "campaigns":
                return SimpleNamespace(data=[
                    {"id": "e7f55644-c831-4c7e-8ba0-b063e1b6149c", "name": "Principal June 10", "absence_days": "10/06/2026", "campaign_type": "primary", "school_id": "school-decic"},
                    {"id": "1235cd45-ad69-4e4c-8ef2-a87b80e2b48a", "name": "Follow-up June 10", "absence_days": "10/06/2026", "campaign_type": "followup", "school_id": "school-decic", "parent_campaign_id": "e7f55644-c831-4c7e-8ba0-b063e1b6149c"}
                ])
            if self.table_name == "messages":
                # 25 students total
                msgs = []
                for idx in range(25):
                    msgs.append({
                        "id": f"msg-p-{idx}",
                        "status": "sent",
                        "student_id": f"student-{idx}",
                        "last_error": None,
                        "wa_jid": f"55149999999{idx}@s.whatsapp.net",
                        "campaign_id": "e7f55644-c831-4c7e-8ba0-b063e1b6149c",
                        "students": {"ra": f"ra-{idx}"}
                    })
                    if idx >= 15:
                        msgs.append({
                            "id": f"msg-f-{idx}",
                            "status": "sent",
                            "student_id": f"student-{idx}",
                            "last_error": None,
                            "wa_jid": f"55149999999{idx}@s.whatsapp.net",
                            "campaign_id": "1235cd45-ad69-4e4c-8ef2-a87b80e2b48a",
                            "students": {"ra": f"ra-{idx}"}
                        })
                return SimpleNamespace(data=msgs)
            if self.table_name == "responses":
                # 20 students responded.
                resps = []
                for idx in range(20):
                    body = "Meu filho acordou com febre e gripe" if idx < 17 else "Ok"
                    reason = "ILLNESS" if idx < 17 else "OUTROS"
                    resps.append({
                        "id": f"resp-{idx}",
                        "sender_jid": f"55149999999{idx}@s.whatsapp.net",
                        "student_id": f"student-{idx}",
                        "guardian_id": f"guardian-{idx}",
                        "campaign_id": "e7f55644-c831-4c7e-8ba0-b063e1b6149c" if idx < 15 else "1235cd45-ad69-4e4c-8ef2-a87b80e2b48a",
                        "identity_confidence": "HIGH",
                        "body": body,
                        "reason": reason,
                        "received_at": "2026-06-10T14:00:00+00:00"
                    })
                return SimpleNamespace(data=resps)
            return SimpleNamespace(data=[])

    class _June10FakeClient:
        def schema(self, name):
            return self

        def table(self, name):
            return _June10FakeQuery(name)

    analytics = CampaignAnalytics.__new__(CampaignAnalytics)
    analytics.client = _June10FakeClient()
    analytics.repository = _FakeRepository(analytics.client)
    analytics.reconciler = SimpleNamespace(reconcile_unresolved_responses=lambda *args, **kwargs: {})
    
    fake_threads = []
    for idx in range(20):
        fake_threads.append(SimpleNamespace(
            student_id=f"student-{idx}",
            sender_jid=f"55149999999{idx}@s.whatsapp.net",
            campaign_id="e7f55644-c831-4c7e-8ba0-b063e1b6149c" if idx < 15 else "1235cd45-ad69-4e4c-8ef2-a87b80e2b48a"
        ))
        
    analytics.builder = SimpleNamespace(
        build_conversations=lambda school_id, campaign_id: fake_threads
    )
    
    def mock_summarize(thread):
        idx = int(thread.student_id.split("-")[1])
        status = OccurrenceStatus.JUSTIFICADO if idx < 17 else OccurrenceStatus.CRITICO
        risk_level = RiskLevel.BAIXO if idx < 17 else RiskLevel.ALTO
        return SimpleNamespace(
            status=status,
            risk_level=risk_level,
            needs_followup=status != OccurrenceStatus.JUSTIFICADO,
            has_medical_document=False,
            student_id=thread.student_id,
            sender_jid=thread.sender_jid,
            campaign_id=thread.campaign_id,
            model_dump=lambda: {},
        )
        
    analytics.summarizer = SimpleNamespace(summarize=mock_summarize)

    report = analytics.generate_report("school-decic", "e7f55644-c831-4c7e-8ba0-b063e1b6149c")

    assert "e7f55644-c831-4c7e-8ba0-b063e1b6149c" in report.campaign_id
    assert "1235cd45-ad69-4e4c-8ef2-a87b80e2b48a" in report.campaign_id
    
    assert report.operational.total_students_targeted == 25
    assert report.operational.messages_sent_success == 25
    assert report.operational.responses_received == 20
    assert report.operational.response_rate == 20 / 25
    
    assert report.justifications.health_issues == 17
    assert report.justifications.unresponsive == 5
    
    assert report.risk.low_risk == 17
    assert report.risk.high_risk == 8


