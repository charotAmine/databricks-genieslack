"""
Entry point for the Databricks Genie Slack Bot.
"""

import logging
import sys

from config import Config
from genie_client import GenieClient
from slack_bot import SlackGenieBot


def main():
    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s  %(name)-28s  %(levelname)-8s  %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logger = logging.getLogger(__name__)

    try:
        Config.validate()
        logger.info("Configuration OK")

        genie = GenieClient(
            host=Config.DATABRICKS_HOST,
            token=Config.DATABRICKS_TOKEN,
            space_id=Config.DATABRICKS_GENIE_SPACE_ID,
            poll_interval=Config.GENIE_POLL_INTERVAL,
            max_wait=Config.GENIE_MAX_WAIT,
        )
        logger.info("Genie client ready  (%s, space %s)",
                     Config.DATABRICKS_HOST, Config.DATABRICKS_GENIE_SPACE_ID)

        bot = SlackGenieBot(
            slack_bot_token=Config.SLACK_BOT_TOKEN,
            slack_signing_secret=Config.SLACK_SIGNING_SECRET,
            slack_app_token=Config.SLACK_APP_TOKEN,
            genie=genie,
        )
        logger.info("Starting Slack socket-mode handler ...")
        bot.start()

    except ValueError as exc:
        logger.error("Config error: %s", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Shutting down ...")
    except Exception as exc:
        logger.error("Fatal: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
