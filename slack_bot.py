"""
Slack bot that forwards natural-language questions to Databricks Genie
and posts the answers back in threads.
"""

import logging
import re
from typing import Dict, Any, Optional

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

from genie_client import GenieClient

logger = logging.getLogger(__name__)


class SlackGenieBot:

    def __init__(self, slack_bot_token: str, slack_signing_secret: str,
                 slack_app_token: str, genie: GenieClient):
        self.app = App(token=slack_bot_token, signing_secret=slack_signing_secret)
        self.slack_app_token = slack_app_token
        self.genie = genie
        self.client = WebClient(token=slack_bot_token)

        # slack thread_ts  →  genie conversation_id
        self.thread_conversations: Dict[str, str] = {}
        # slack message ts  →  (conversation_id, message_id) for feedback
        self.feedback_map: Dict[str, tuple] = {}

        self._register_handlers()

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def _register_handlers(self):

        @self.app.event("app_mention")
        def on_mention(event, say, client):
            self._handle_question(event, say, client)

        @self.app.event("message")
        def on_message(event, say, client):
            if event.get("channel_type") == "im" or event.get("thread_ts"):
                self._handle_question(event, say, client)

        @self.app.action("feedback_positive")
        def on_positive(ack, body, client):
            ack()
            self._handle_feedback(body, "POSITIVE", client)

        @self.app.action("feedback_negative")
        def on_negative(ack, body, client):
            ack()
            self._handle_feedback(body, "NEGATIVE", client)

    # ------------------------------------------------------------------
    # Core question → Genie → Slack flow
    # ------------------------------------------------------------------

    def _handle_question(self, event: Dict[str, Any], say, client):
        if event.get("bot_id"):
            return

        text = self._strip_mention(event.get("text", ""))
        channel = event["channel"]
        thread_ts = event.get("thread_ts") or event["ts"]

        if not text.strip():
            say("Please ask me a question about your data!", thread_ts=thread_ts)
            return

        client.chat_postMessage(channel=channel, text="Thinking...",
                                thread_ts=thread_ts)

        conversation_id = self.thread_conversations.get(thread_ts)

        result = self.genie.ask(text, conversation_id=conversation_id)

        if result.get("conversation_id"):
            self.thread_conversations[thread_ts] = result["conversation_id"]

        # Main answer text
        answer = self._format_answer(result)
        say(answer, thread_ts=thread_ts)

        # Query result table
        if result.get("result_data"):
            table_msg = self._format_query_result(result["result_data"])
            if table_msg:
                say(table_msg, thread_ts=thread_ts)

        # Feedback buttons
        if result.get("success") and result.get("conversation_id") and result.get("message_id"):
            fb_resp = self._send_feedback_buttons(channel, thread_ts, client)
            if fb_resp:
                self.feedback_map[fb_resp["ts"]] = (
                    result["conversation_id"], result["message_id"])

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_mention(text: str) -> str:
        return re.sub(r"<@[A-Z0-9]+>", "", text).strip()

    @staticmethod
    def _format_answer(result: Dict[str, Any]) -> str:
        if not result.get("success"):
            return f"Sorry, something went wrong: {result.get('error', 'unknown error')}"
        return result.get("text") or "Query executed successfully."

    @staticmethod
    def _format_query_result(result_data: Dict[str, Any], max_rows: int = 15) -> Optional[str]:
        """Turn Genie query-result JSON into a Slack code-block table."""
        columns_meta = result_data.get("manifest", {}).get("schema", {}).get("columns", [])
        data_section = result_data.get("result", {})
        rows = data_section.get("data_array", [])

        if not rows or not columns_meta:
            return None

        col_names = [c.get("name", f"col_{i}") for i, c in enumerate(columns_meta)]

        widths = [len(n) for n in col_names]
        display_rows = rows[:max_rows]
        for row in display_rows:
            for i, val in enumerate(row):
                widths[i] = max(widths[i], len(str(val) if val is not None else ""))
        widths = [min(w, 30) for w in widths]

        def fmt_row(values):
            parts = []
            for v, w in zip(values, widths):
                s = str(v) if v is not None else ""
                parts.append(s[:w].ljust(w))
            return " | ".join(parts)

        lines = [fmt_row(col_names),
                 "-+-".join("-" * w for w in widths)]
        for row in display_rows:
            lines.append(fmt_row(row))

        total = data_section.get("row_count", len(rows))
        footer = ""
        if total > max_rows:
            footer = f"\n_Showing {max_rows} of {total} rows_"

        return f"*Query Results:*\n```\n" + "\n".join(lines) + "\n```" + footer

    # ------------------------------------------------------------------
    # Feedback buttons
    # ------------------------------------------------------------------

    def _send_feedback_buttons(self, channel: str, thread_ts: str,
                               client) -> Optional[Dict]:
        try:
            return client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="Was this response helpful?",
                blocks=[
                    {"type": "section", "text": {
                        "type": "mrkdwn",
                        "text": "*Was this response helpful?*"}},
                    {"type": "actions", "elements": [
                        {"type": "button",
                         "text": {"type": "plain_text", "text": "Helpful", "emoji": True},
                         "action_id": "feedback_positive"},
                        {"type": "button",
                         "text": {"type": "plain_text", "text": "Not Helpful", "emoji": True},
                         "action_id": "feedback_negative"},
                    ]},
                ],
            )
        except Exception as exc:
            logger.error("Failed to send feedback buttons: %s", exc)
            return None

    def _handle_feedback(self, body: Dict[str, Any], rating: str, client):
        msg_ts = body.get("message", {}).get("ts")
        channel = body.get("channel", {}).get("id")
        info = self.feedback_map.get(msg_ts)

        if not info:
            logger.warning("No feedback mapping for ts=%s", msg_ts)
            return

        conversation_id, message_id = info
        success = self.genie.send_feedback(conversation_id, message_id, rating)

        label = "Thanks for your feedback!" if success else "Failed to submit feedback."
        try:
            client.chat_update(
                channel=channel, ts=msg_ts, text=label,
                blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": f"_{label}_"}}],
            )
        except Exception as exc:
            logger.error("Failed to update feedback message: %s", exc)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def start(self):
        handler = SocketModeHandler(self.app, self.slack_app_token)
        logger.info("Starting Slack bot in socket mode ...")
        handler.start()
