import os

file_path = "app/infrastructure/supabase/repositories.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace(
    "    StudentRecord,\n)",
    "    StudentRecord,\n    ConversationSessionRecord,\n)"
)

methods = """
    def find_active_session(
        self,
        *,
        school_id: str,
        sender_jid: str,
    ) -> ConversationSessionRecord | None:
        def operation():
            return (
                self.client.schema("busca_ativa_v2")
                .table("conversation_sessions")
                .select("*")
                .eq("school_id", school_id)
                .eq("sender_jid", sender_jid)
                .limit(1)
                .execute()
            )

        rows = (
            self._execute_with_retry(operation, operation="find_active_session").data
            or []
        )
        return self._session(rows[0]) if rows else None

    def upsert_session(
        self,
        *,
        school_id: str,
        sender_jid: str,
        push_name: str | None = None,
        guardian_id: str | None = None,
        student_id: str | None = None,
        campaign_id: str | None = None,
        last_message_id: str | None = None,
        resolved: bool | None = None,
        resolution_source: str | None = None,
    ) -> ConversationSessionRecord:
        row: dict[str, Any] = {
            "school_id": school_id,
            "sender_jid": sender_jid,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }
        if push_name is not None:
            row["push_name"] = push_name
        if guardian_id is not None:
            row["guardian_id"] = guardian_id
        if student_id is not None:
            row["student_id"] = student_id
        if campaign_id is not None:
            row["campaign_id"] = campaign_id
        if last_message_id is not None:
            row["last_message_id"] = last_message_id
        if resolved is not None:
            row["resolved"] = resolved
        if resolution_source is not None:
            row["resolution_source"] = resolution_source

        def operation():
            return (
                self.client.schema("busca_ativa_v2")
                .table("conversation_sessions")
                .upsert(row, on_conflict="school_id,sender_jid")
                .select("*")
                .execute()
            )

        response = self._execute_with_retry(operation, operation="upsert_session")
        data = self._require_data(response, "upsert_session")
        return self._session(data[0])

    def _session(self, row: dict[str, Any]) -> ConversationSessionRecord:
        return ConversationSessionRecord(
            id=str(row.get("id")),
            school_id=str(row.get("school_id")),
            sender_jid=str(row.get("sender_jid")),
            push_name=row.get("push_name"),
            guardian_id=row.get("guardian_id"),
            student_id=row.get("student_id"),
            campaign_id=row.get("campaign_id"),
            last_message_id=row.get("last_message_id"),
            last_seen_at=self._parse_datetime(row.get("last_seen_at")),
            created_at=self._parse_datetime(row.get("created_at")),
            resolved=bool(row.get("resolved")),
            resolution_source=row.get("resolution_source"),
        )
"""

content = content.replace(
    '        return IdentityMapRecord(\n            guardian=guardian,\n            confidence=str(row.get("confidence") or ""),\n        )',
    '        return IdentityMapRecord(\n            guardian=guardian,\n            confidence=str(row.get("confidence") or ""),\n        )\n' + methods
)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Done")
