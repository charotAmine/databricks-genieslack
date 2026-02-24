# Databricks Genie Slack Bot

A Slack bot that connects to a [Databricks Genie](https://docs.databricks.com/aws/en/genie/conversation-api) space, letting users ask natural-language questions about their data directly from Slack.

## Features

- **Natural-language queries** — ask questions in plain English; Genie generates and runs SQL behind the scenes.
- **Threaded conversations** — follow-up questions in the same Slack thread share context, just like in the Genie UI.
- **Query result tables** — structured results are rendered as formatted tables inside Slack.
- **Feedback buttons** — thumbs-up / thumbs-down on every answer, forwarded back to the Genie space for curation.
- **Channel & DM support** — works via direct messages or @mentions in channels.

## Architecture

```
┌────────────┐       Socket Mode       ┌──────────────┐      REST API       ┌─────────────────┐
│   Slack    │  ◄──────────────────►   │  slack_bot.py │  ──────────────►   │  Databricks     │
│  workspace │                          │               │                    │  Genie Space    │
└────────────┘                          │  app.py       │   ◄────────────   │                 │
                                        │  config.py    │   (poll results)  │  genie_client.py│
                                        └──────────────┘                    └─────────────────┘
```

| File | Purpose |
|---|---|
| `app.py` | Entry point — validates config, wires components, starts the bot. |
| `config.py` | Reads environment variables (`.env` locally, `app.yaml` in Databricks Apps). |
| `genie_client.py` | **Standalone Genie REST client.** Uses plain `requests` + PAT token. Edit this to change how Genie is called, how responses are parsed, or to add new API methods. |
| `slack_bot.py` | Slack event handlers (mentions, DMs, feedback buttons) and message formatting. |
| `app.yaml` | Databricks Apps deployment descriptor. |
| `requirements.txt` | Python dependencies. |
| `.env` | Local credentials (git-ignored). |

## Prerequisites

1. **Python 3.10+**
2. **Databricks workspace** with an existing Genie space.
3. **Slack workspace** with admin access to create an app.

## Slack App Setup

1. Go to <https://api.slack.com/apps> → **Create New App** → **From scratch**.
2. Name it (e.g. *Genie Bot*) and pick your workspace.

### OAuth & Permissions

Add these **Bot Token Scopes** under *OAuth & Permissions*:

| Scope | Why |
|---|---|
| `app_mentions:read` | React to @mentions in channels |
| `chat:write` | Post messages and results |
| `im:history` | Read DM history for context |
| `im:read` | Receive DM events |
| `im:write` | Send DMs |

### Socket Mode

1. Navigate to **Socket Mode** → enable it.
2. Generate an **App-Level Token** with the `connections:write` scope.
3. Save the token (starts with `xapp-`).

### Event Subscriptions

Under **Event Subscriptions** → enable, then subscribe to these **bot events**:

- `app_mention`
- `message.im`

### App Home

1. Go to **App Home** → **Show Tabs**.
2. Enable the **Messages Tab**.
3. Check **"Allow users to send Slash commands and messages from the messages tab"**.

### Install to Workspace

1. Go to **Install App** → **Install to Workspace** → authorize.
2. Copy the **Bot User OAuth Token** (`xoxb-...`).
3. From **Basic Information** → **App Credentials**, copy the **Signing Secret**.

## Configuration

Create a `.env` file in the project root (or set the variables in `app.yaml` for Databricks Apps deployment):

```env
# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_APP_TOKEN=xapp-...

# Databricks
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=dapi...
DATABRICKS_GENIE_SPACE_ID=your-space-id

# Optional tuning
LOG_LEVEL=INFO
GENIE_POLL_INTERVAL=2   # seconds between status polls
GENIE_MAX_WAIT=90        # max seconds to wait for a Genie answer
```

| Variable | Required | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | Yes | Bot User OAuth Token (`xoxb-`). |
| `SLACK_SIGNING_SECRET` | Yes | Signing secret from *Basic Information*. |
| `SLACK_APP_TOKEN` | Yes | App-Level Token with `connections:write` (`xapp-`). |
| `DATABRICKS_HOST` | Yes | Full URL of your Databricks workspace. |
| `DATABRICKS_TOKEN` | Yes | Personal Access Token (PAT) for the workspace. |
| `DATABRICKS_GENIE_SPACE_ID` | Yes | ID of the Genie space (found in its Settings tab or URL). |
| `LOG_LEVEL` | No | Python log level. Default `INFO`. |
| `GENIE_POLL_INTERVAL` | No | Seconds between polls when waiting for Genie. Default `2`. |
| `GENIE_MAX_WAIT` | No | Timeout in seconds for a single question. Default `90`. |

## Run Locally

```bash
# Create a virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start the bot
python app.py
```

You should see:

```
Configuration OK
Genie client ready  (https://..., space ...)
Starting Slack socket-mode handler ...
⚡️ Bolt app is running!
```

## Deploy to Databricks Apps

1. In your Databricks workspace go to **Compute** → **Apps** → **Create custom app**.
2. Name the app (e.g. `genie-slack-bot`), wait for it to be ready.
3. Note the auto-created **Service Principal** from the *Authorization* tab.
4. Grant the service principal:
   - **CAN RUN** on the Genie space.
   - **CAN USE** on the SQL warehouse the space uses.
   - **SELECT** on the Unity Catalog tables/views referenced by the space.
5. Fill in the Slack tokens in `app.yaml`.
6. Upload all project files to a workspace folder.
7. Deploy the app from that folder.

> When deployed to Databricks Apps you can alternatively use the service principal's OAuth credentials instead of a PAT. Set `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` in `app.yaml` and remove `DATABRICKS_TOKEN`. The `requests`-based client in `genie_client.py` would need a small change to support OAuth token exchange — see the Databricks SDK for reference.

## Usage

### Direct Messages

Open a DM with the bot and type your question:

> *Show me total sales by region for last quarter*

### Channel Mentions

Invite the bot to a channel (`/invite @GeniBot`) then mention it:

> *@GeniBot what are the top 10 customers by revenue?*

### Threaded Conversations

Reply in the same thread to ask follow-up questions — the bot keeps the Genie conversation context:

> *Break that down by month*

### Feedback

Every answer includes **Helpful** / **Not Helpful** buttons. Clicking them sends feedback to the Genie space so the space author can review and improve it.

## Editing the Genie Client

The `genie_client.py` module is intentionally self-contained. It uses plain `requests` (no SDK magic) so every API call is visible and editable.

Common customisations:

| What | Where in `genie_client.py` |
|---|---|
| Change polling timing | `__init__` params `poll_interval` / `max_wait` |
| Alter how text is extracted from attachments | `_parse_response()` |
| Add a new API call (e.g. list conversations) | Add a method following the `start_conversation` pattern |
| Switch to OAuth M2M auth | Replace the `Bearer` token header with an OAuth token exchange flow |
| Customise error handling | `_request()` method |

## API Endpoints Used

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/2.0/genie/spaces/{sid}/start-conversation` | Start a new conversation |
| `POST` | `/api/2.0/genie/spaces/{sid}/conversations/{cid}/messages` | Send a follow-up message |
| `GET` | `/api/2.0/genie/spaces/{sid}/conversations/{cid}/messages/{mid}` | Poll message status |
| `GET` | `/api/2.0/genie/spaces/{sid}/conversations/{cid}/messages/{mid}/attachments/{aid}/query-result` | Fetch query result rows |
| `POST` | `/api/2.0/genie/spaces/{sid}/conversations/{cid}/messages/{mid}/feedback` | Submit feedback |

Full reference: <https://docs.databricks.com/api/workspace/genie>
