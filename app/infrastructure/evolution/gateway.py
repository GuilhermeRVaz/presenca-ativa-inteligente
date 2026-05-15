from typing import Any

import httpx

from app.core.config import settings
from app.domain.models import SendResult


class EvolutionGateway:
    def send_text(self, *, to_jid: str, text: str, dry_run: bool = False) -> SendResult:
        if to_jid.endswith("@lid"):
            phone = to_jid
        else:
            phone = to_jid.split("@", 1)[0]

        if dry_run:
            return SendResult(success=True, provider_message_id=None, mock=True)

        self._validate_config()
        payload = {"number": phone, "text": text}
        try:
            with httpx.Client(timeout=settings.evolution_timeout_seconds) as client:
                response = client.post(
                    self._send_url(),
                    headers=self._headers(),
                    json=payload,
                )
        except httpx.HTTPError as exc:
            return SendResult(success=False, error=str(exc))

        data = self._json(response)
        if response.status_code not in (200, 201) or "error" in response.text.lower():
            return SendResult(success=False, error=response.text)
        return SendResult(
            success=True,
            provider_message_id=self._extract_provider_message_id(data),
        )

    def send_button_message(
        self, *, to_jid: str, title: str = "", description: str = "", buttons: list[dict[str, str]], dry_run: bool = False
    ) -> SendResult:
        if to_jid.endswith("@lid"):
            phone = to_jid
        else:
            phone = to_jid.split("@", 1)[0]

        if dry_run:
            return SendResult(success=True, provider_message_id=None, mock=True)

        self._validate_config()
        
        # Format buttons for Evolution API
        formatted_buttons = []
        for i, btn in enumerate(buttons):
            formatted_buttons.append({
                "buttonId": btn.get("id", f"BTN_{i}"),
                "buttonText": {"displayText": btn.get("text", "")},
                "type": "reply"
            })

        payload = {
            "number": phone,
            "title": title,
            "description": description,
            "buttons": formatted_buttons
        }
        
        try:
            with httpx.Client(timeout=settings.evolution_timeout_seconds) as client:
                response = client.post(
                    self._send_url("message/sendButtons"),
                    headers=self._headers(),
                    json=payload,
                )
        except httpx.HTTPError as exc:
            return SendResult(success=False, error=str(exc))

        data = self._json(response)
        if response.status_code not in (200, 201) or "error" in response.text.lower():
            return SendResult(success=False, error=response.text)
            
        return SendResult(
            success=True,
            provider_message_id=self._extract_provider_message_id(data),
        )

    def _validate_config(self) -> None:
        missing = [
            name
            for name, value in {
                "EVOLUTION_API_URL": settings.evolution_api_url,
                "EVOLUTION_API_KEY": settings.evolution_api_key,
                "EVOLUTION_API_INSTANCE": settings.evolution_api_instance,
            }.items()
            if not value
        ]
        if missing:
            raise ValueError("Missing Evolution configuration: " + ", ".join(missing))

    def _send_url(self, endpoint_path: str = "message/sendText") -> str:
        return (
            f"{settings.evolution_api_url.rstrip('/')}/"
            f"{endpoint_path}/{settings.evolution_api_instance}"
        )

    @staticmethod
    def _headers() -> dict[str, str]:
        return {"apikey": settings.evolution_api_key, "Content-Type": "application/json"}

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {}

    @staticmethod
    def _extract_provider_message_id(data: Any) -> str | None:
        if not isinstance(data, dict):
            return None
        value = data.get("key", {}).get("id") or data.get("id") or data.get("messageId")
        return str(value) if value else None
