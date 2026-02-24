"""
Databricks Genie REST API Client.

This module is intentionally kept separate so you can modify the Genie interaction
logic (polling, response parsing, result formatting) without touching the Slack layer.

API reference: https://docs.databricks.com/api/workspace/genie
"""

import time
import logging
from typing import Optional, Dict, Any, List

import requests

logger = logging.getLogger(__name__)


class GenieClient:
    """
    Thin wrapper around the Databricks Genie Conversation REST API.

    All HTTP calls go through ``requests`` with a PAT token so the logic
    is fully transparent and easy to customise.
    """

    def __init__(self, host: str, token: str, space_id: str,
                 poll_interval: int = 2, max_wait: int = 90):
        self.host = host.rstrip("/")
        self.space_id = space_id
        self.poll_interval = poll_interval
        self.max_wait = max_wait
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.host}{path}"

    def _request(self, method: str, path: str, **kwargs) -> Optional[Dict[str, Any]]:
        """Execute an authenticated request and return the JSON body."""
        url = self._url(path)
        try:
            resp = self.session.request(method, url, **kwargs)
            resp.raise_for_status()
            if resp.content:
                return resp.json()
            return {}
        except requests.HTTPError as exc:
            logger.error("HTTP %s %s → %s: %s", method, path, exc.response.status_code,
                         exc.response.text[:500])
            return None
        except Exception as exc:
            logger.error("Request failed %s %s: %s", method, path, exc)
            return None

    # ------------------------------------------------------------------
    # Conversation lifecycle
    # ------------------------------------------------------------------

    def start_conversation(self, question: str) -> Optional[Dict[str, Any]]:
        """
        Start a brand-new conversation with an initial question.

        POST /api/2.0/genie/spaces/{space_id}/start-conversation
        Body: {"content": "<question>"}

        Returns the raw API response containing ``conversation`` and ``message`` keys.
        """
        path = f"/api/2.0/genie/spaces/{self.space_id}/start-conversation"
        return self._request("POST", path, json={"content": question})

    def create_message(self, conversation_id: str, question: str) -> Optional[Dict[str, Any]]:
        """
        Send a follow-up message inside an existing conversation.

        POST /api/2.0/genie/spaces/{space_id}/conversations/{cid}/messages
        Body: {"content": "<question>"}
        """
        path = (f"/api/2.0/genie/spaces/{self.space_id}"
                f"/conversations/{conversation_id}/messages")
        return self._request("POST", path, json={"content": question})

    def get_message(self, conversation_id: str, message_id: str) -> Optional[Dict[str, Any]]:
        """
        Poll for the status / result of a message.

        GET /api/2.0/genie/spaces/{space_id}/conversations/{cid}/messages/{mid}
        """
        path = (f"/api/2.0/genie/spaces/{self.space_id}"
                f"/conversations/{conversation_id}/messages/{message_id}")
        return self._request("GET", path)

    def get_query_result(self, conversation_id: str, message_id: str,
                         attachment_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve the SQL query result rows for an attachment.

        GET /api/2.0/genie/spaces/{space_id}/conversations/{cid}/messages/{mid}
              /attachments/{aid}/query-result
        """
        path = (f"/api/2.0/genie/spaces/{self.space_id}"
                f"/conversations/{conversation_id}/messages/{message_id}"
                f"/attachments/{attachment_id}/query-result")
        return self._request("GET", path)

    def send_feedback(self, conversation_id: str, message_id: str,
                      rating: str, feedback_text: Optional[str] = None) -> bool:
        """
        Submit thumbs-up / thumbs-down feedback on a Genie answer.
        ``rating`` should be ``"POSITIVE"`` or ``"NEGATIVE"``.
        """
        path = (f"/api/2.0/genie/spaces/{self.space_id}"
                f"/conversations/{conversation_id}/messages/{message_id}/feedback")
        payload: Dict[str, Any] = {"rating": rating.upper()}
        if feedback_text:
            payload["feedback_text"] = feedback_text
        result = self._request("POST", path, json=payload)
        return result is not None

    # ------------------------------------------------------------------
    # High-level: ask and wait
    # ------------------------------------------------------------------

    def _poll_until_done(self, conversation_id: str,
                         message_id: str) -> Optional[Dict[str, Any]]:
        """Poll ``get_message`` until status is COMPLETED / FAILED or timeout."""
        deadline = time.time() + self.max_wait
        while time.time() < deadline:
            msg = self.get_message(conversation_id, message_id)
            if msg is None:
                return None
            status = msg.get("status")
            if status == "COMPLETED":
                return msg
            if status in ("FAILED", "CANCELLED"):
                logger.warning("Message %s finished with status %s", message_id, status)
                return msg
            time.sleep(self.poll_interval)
        logger.warning("Timed out waiting for message %s", message_id)
        return None

    def _parse_response(self, conversation_id: str, message_id: str,
                        msg: Dict[str, Any]) -> Dict[str, Any]:
        """
        Turn the raw completed-message payload into a friendlier dict.

        Returns
        -------
        {
            "success": bool,
            "conversation_id": str,
            "message_id": str,
            "text": str,            # natural-language answer
            "sql": str | None,      # generated SQL (if any)
            "result_data": {...},    # query result rows & schema
            "attachments": [...],
            "error": str | None,
        }
        """
        if msg.get("status") != "COMPLETED":
            error_detail = msg.get("error", {})
            error_msg = error_detail.get("message", "Unknown error") if isinstance(error_detail, dict) else str(error_detail)
            return {
                "success": False,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "error": error_msg,
            }

        attachments = msg.get("attachments") or []
        text_parts: List[str] = []
        sql_text: Optional[str] = None
        result_data: Optional[Dict[str, Any]] = None

        for att in attachments:
            if "text" in att:
                content = att["text"].get("content", "")
                if content:
                    text_parts.append(content)
            if "query" in att:
                query_info = att["query"]
                description = query_info.get("description", "")
                if description:
                    text_parts.append(description)
                sql_text = query_info.get("query")
                attachment_id = att.get("attachment_id")
                if attachment_id:
                    qr = self.get_query_result(conversation_id, message_id, attachment_id)
                    if qr:
                        result_data = qr

        response_text = "\n\n".join(text_parts) or msg.get("content", "")

        return {
            "success": True,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "text": response_text.strip(),
            "sql": sql_text,
            "result_data": result_data,
            "attachments": attachments,
            "error": None,
        }

    def ask(self, question: str,
            conversation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        High-level: send a question and block until the answer is ready.

        Parameters
        ----------
        question : str
            Natural-language question.
        conversation_id : str, optional
            Pass an existing conversation ID to continue a thread.
            ``None`` starts a new conversation.

        Returns
        -------
        dict  with keys ``success``, ``conversation_id``, ``message_id``,
              ``text``, ``sql``, ``result_data``, ``attachments``, ``error``.
        """
        if conversation_id:
            raw = self.create_message(conversation_id, question)
        else:
            raw = self.start_conversation(question)

        if raw is None:
            return {"success": False, "conversation_id": conversation_id,
                    "error": "Failed to send message to Genie"}

        # The start-conversation response nests under "message"
        message_data = raw.get("message", raw)
        conv_data = raw.get("conversation", {})

        cid = message_data.get("conversation_id") or conv_data.get("id") or conversation_id
        mid = message_data.get("id") or raw.get("id")

        if not cid or not mid:
            return {"success": False, "conversation_id": conversation_id,
                    "error": "Could not extract conversation/message IDs from response"}

        completed = self._poll_until_done(cid, mid)
        if completed is None:
            return {"success": False, "conversation_id": cid, "message_id": mid,
                    "error": "Timed out waiting for Genie response"}

        return self._parse_response(cid, mid, completed)
