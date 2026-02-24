"""
Configuration management for the Databricks Genie Slack App.
Reads from environment variables (set via .env locally or app.yaml in Databricks Apps).
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Slack
    SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
    SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
    SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")

    # Databricks
    DATABRICKS_HOST = os.getenv("DATABRICKS_HOST")
    DATABRICKS_TOKEN = os.getenv("DATABRICKS_TOKEN")
    DATABRICKS_GENIE_SPACE_ID = os.getenv("DATABRICKS_GENIE_SPACE_ID")

    # App
    PORT = int(os.getenv("PORT", "3000"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    # Genie polling
    GENIE_POLL_INTERVAL = int(os.getenv("GENIE_POLL_INTERVAL", "2"))
    GENIE_MAX_WAIT = int(os.getenv("GENIE_MAX_WAIT", "90"))

    @classmethod
    def validate(cls):
        required = {
            "SLACK_BOT_TOKEN": cls.SLACK_BOT_TOKEN,
            "SLACK_SIGNING_SECRET": cls.SLACK_SIGNING_SECRET,
            "SLACK_APP_TOKEN": cls.SLACK_APP_TOKEN,
            "DATABRICKS_HOST": cls.DATABRICKS_HOST,
            "DATABRICKS_TOKEN": cls.DATABRICKS_TOKEN,
            "DATABRICKS_GENIE_SPACE_ID": cls.DATABRICKS_GENIE_SPACE_ID,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        return True
