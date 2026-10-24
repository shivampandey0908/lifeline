# LifeLine — emergency assistance agent

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

LifeLine is a Python uAgents agent built for the Fetch-A-Thon 3.0 ASI:One challenge. It uses the official ASI:One Agent Chat Protocol, persists its demo workflows in SQLite, and provides an authenticated provider response API. Its complete roadside flow asks for location, lists registered mechanics, requires a provider selection and explicit user confirmation, creates a `PENDING` booking, and changes the status only after a provider response is submitted.

All seeded mechanics and blood centre records are **simulated**. No real roadside service is dispatched. The separate provider API is the demo interface that records a provider's accept or reject response. Do not use these demo contacts in an emergency.

## Architecture and protocol

- `lifeline_agent.py`: uAgents runtime with the standard `chat_protocol_spec`, ACP `ChatMessage` acknowledgement, and text replies.
- `intent_router.py`: typed prompt classification and extraction for mechanic help, blood assistance, general questions, emergencies, and unknown requests.
- `dialogue_service.py`: follow-up conversation state and shared mechanic/blood workflows used by both ACP and the local browser chat.
- `mechanic_service.py`, `blood_service.py`: matching and workflow helpers.
- `database.py`: SQLite providers, conversations, and booking lifecycle transitions.
- `provider_api.py`: local chat web/API plus the authenticated provider inbox and response endpoints.
- `static/index.html`: responsive chat page served by the local FastAPI app.
- `demo.py`: deterministic acceptance walkthrough without network dependencies.
- `tests/`: core matching, idempotency, authorization, lifecycle, and blood-data tests.

The current official [ASI:One ACP tutorial](https://docs.asi1.ai/documentation/tutorials/agent-chat-protocol) specifies uAgents and `uagents_core.contrib.protocols.chat` models. A running agent publishes the chat manifest with `agent.include(chat_proto, publish_manifest=True)`. Fetch.ai's current [uAgent creation guide](https://innovationlab.fetch.ai/resources/docs/agent-creation/uagent-creation) describes connecting an existing local agent through Agentverse Mailbox and notes that `mailbox=True` requires uAgents 0.25.3 or newer. The [Planner Mode docs](https://docs.asi1.ai/documentation/build-with-asi-one/planner) describe discovery and invocation of agents listed in Agentverse; direct ASI:One invocation can also mention the registered agent address. The [Fetch-A-Thon 3.0 hackpack](https://www.fetch.ai/events/hackathons/fetch-a-thon-3/hackpack) requires Agentverse registration, ACP interaction, direct ASI:One usability, a meaningful executable workflow, a public GitHub repository, a shared chat URL, and demo video.

## Setup

Python 3.10+ is required (the official tutorial lists 3.10+).

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and replace the seed and token placeholders with private values. `LIFELINE_SEED` must remain stable for the registered agent identity; the uAgents SDK hashes an arbitrary string seed and does not require a mnemonic. The app refuses the repository's example placeholder at agent startup. Keep both values secret. `LIFELINE_DB_PATH` defaults to `lifeline.db`.

### Test in a local browser (Agentverse is not required)

Start the local web chat and provider API:

```bash
python seed_demo_data.py
uvicorn provider_api:app --host 127.0.0.1 --port 8001
```

Open **http://127.0.0.1:8001**. Enter a prompt or choose a suggestion. The page keeps the current chat history in browser storage and sends each message to `/api/chat`; the server uses `dialogue_service.py`, SQLite, and the existing provider services. Start a new conversation with the button in the header.

Prompt understanding uses typed local rules and needs no external model API key. It extracts the service category, location, vehicle problem/type, blood group, units, and urgency when it can, then asks follow-up questions for missing details. User input is bounded and service selection is validated before a booking can be created. Provider data and all blood-centre records remain simulated.

For the ACP/Agentverse integration, start the separate agent process:

```bash
python lifeline_agent.py
```

The local browser chat does not import or start the uAgents runtime, require mailbox setup, or need Almanac funds. The provider API remains available at the same time on port 8001; the ACP agent uses port 8000.

Provider API docs are available at `http://127.0.0.1:8001/docs`. `PROVIDER_API_TOKEN` is a shared local master secret used to derive distinct demo provider credentials (`<master-token>:<provider-id>`). For example, a demo provider polls with `Bearer <master-token>:demo-mech-01`. Production deployment must provision individual high-entropy provider credentials and deliver each only to its provider; the shared-secret derivation is for deterministic local demonstration.

## Demo through ACP and provider interface

In ASI:One, after registration, mention the agent address and start with:

> My car has broken down near the Yamuna Expressway, close to Greater Noida. The engine won't start.

Choose one listed simulated mechanic, then answer `YES` when LifeLine asks to confirm. It returns a unique `PENDING` request ID. It does not claim acceptance. The provider can view its pending requests:

```bash
curl -H 'Authorization: Bearer <master-token>:demo-mech-01' \
  http://127.0.0.1:8001/provider/requests
```

The selected provider submits its response (use the actual request ID):

```bash
curl -X POST http://127.0.0.1:8001/provider/requests/<request-id>/response \
  -H 'Authorization: Bearer <master-token>:demo-mech-01' \
  -H 'Content-Type: application/json' \
  -d '{"provider_id":"demo-mech-01","status":"ACCEPTED","response":"Demo provider accepted; this is simulated.","eta_minutes":25}'
```

Return to the same ASI:One conversation and ask `status <request-id>`. LifeLine reads the persisted provider response. A second response or a response from a different provider is rejected. A provider can instead submit `REJECTED`, then the user can start a fresh request with another mechanic.

The scripted local demonstration exercises the full path, including an explicitly labelled provider simulator acceptance:

```bash
python demo.py
```

## Blood assistance and data limits

Ask, for example, `I need O-positive blood near Greater Noida. Find blood banks that may have stock.` The seeded directory records are labelled simulated, do not contain stock, and never imply that a unit or donor is confirmed. LifeLine asks users to call the centre and contact the treating hospital or emergency services for emergencies.

India's [official e-RaktKosh portal](https://eraktkosh.mohfw.gov.in/) provides a public, human-facing blood availability search. Its [stock availability page](https://eraktkosh.mohfw.gov.in/BLDAHIMS/bloodbank/stockAvailability.cnt) displays blood bank, availability, and last-updated fields. Its [FAQ](https://eraktkosh.mohfw.gov.in/BLDAHIMS/bloodbank/eraktkoshfaq.cnt) explains that users can inspect the `LIVE` or last-updated status. I found no documented public API or authorized programmatic access instructions during implementation, so LifeLine does not scrape the portal or represent the data as integrated. `ERAKTKOSH_API_BASE` is reserved for a future authorized source.

## Booking states and timeout

Valid states are `CREATED`, `PENDING`, `ACCEPTED`, `REJECTED`, `EXPIRED`, and `CANCELLED`. A confirmed user request moves from `CREATED` to `PENDING`. Only the authenticated selected provider can move a pending booking to `ACCEPTED` or `REJECTED`. Duplicate chat retries with the same conversation key reuse the same booking. A pending request is marked `EXPIRED` on status lookup once it is older than `BOOKING_TIMEOUT_MINUTES` (default 30). ETA is shown only when supplied by the provider.

## Tests

```bash
pytest -q
```

The tests are local and deterministic. They do not verify Agentverse publication, ASI:One routing, a live mechanic, or live blood stock.

## Agentverse registration, deployment, and ASI:One

This project is an existing **uAgents Mailbox Agent**. Keep that architecture for the shortest supported Agentverse path. It is not an A2A SDK agent and does not need the `agentverse_sdk.a2a` setup or an External Integration entry for a third-party framework. Agentverse's current uAgents guide describes running the agent locally with `mailbox=True`, opening its Inspector URL, and connecting it through **Mailbox**. The Inspector registration is an account action and cannot be completed from this repository.

### Start the local mailbox agent

Create a private stable seed once, put it in `.env` as `LIFELINE_SEED`, and do not change it after registering this agent. The same seed always identifies the same uAgent; changing it creates a different address. Set `PROVIDER_API_TOKEN` too if you want to use the separate provider API with a repeatable credential.

```bash
cp .env.example .env
openssl rand -hex 32
# Paste the generated value into LIFELINE_SEED in .env.
openssl rand -hex 32
# Paste this second generated value into PROVIDER_API_TOKEN in .env.
python -m pip install -r requirements.txt
python lifeline_agent.py
```

Keep the process running. Open the **Agent Inspector URL** printed at startup, sign into Agentverse, select **Connect → Mailbox**, and finish the UI flow. If Chrome asks to allow local network access, allow it so Inspector can reach the local agent. Then verify the mailbox is connected and the profile/manifest are visible. In ASI:One, start from the Agentverse profile's chat action or address and test the mechanic and blood prompts above. Agentverse/ASI:One account access is required. Do not share the seed or mailbox token.

Mailbox relay is the right selection here: the agent is designed to receive through Agentverse's relay and does not expose a public inbound uAgent endpoint. **Public endpoint** applies when a server with a reachable public URL is configured to receive agent messages directly. Local mailbox mode still requires this computer and process to remain online. A cloud-hosted uAgent is the same Python process run on a VM/container with the same stable seed and mailbox configuration; you manage its uptime, secrets, and persistent database. If using Inspector for a remote machine, follow Agentverse's port-forwarding guidance.

### Keep the four deployment pieces distinct

1. **Mailbox-enabled local uAgent:** this repository's selected route; Python runs on your computer, messages relay through Agentverse.
2. **Cloud-hosted uAgent connected to Agentverse:** the same application deployed to infrastructure you manage, with secrets and durable storage configured there. This repo does not include a provider-specific deployment manifest because hosting targets differ.
3. **Agentverse Hosted Agent:** code runs in Agentverse's hosted editor/runtime. The platform does not automatically run this arbitrary repository; using it would require porting the modules and validating its dependency and storage support.
4. **FastAPI Provider API:** a separate local browser chat and provider inbox/response service (`provider_api.py`). The uAgent currently calls `dialogue_service.py` and the Python services directly; it does **not** call the Provider API, so `PROVIDER_API_URL` is not needed. The local API and agent use the same SQLite path when run on one machine. If you split them across cloud hosts, configure shared durable storage or redesign the provider API around a remote database before relying on cross-service booking updates. Expose the provider API publicly over HTTPS only if remote providers need it, and configure authentication secrets in the host; never point a deployed process at `127.0.0.1` expecting to reach another service.

The supported `uagents==0.25.5` and `uagents-core==0.4.12` versions provide the installed `AgentChatProtocol 0.3.0` and mailbox API used here. `lifeline_agent.py` acknowledges inbound chat with the received `msg_id`, processes `TextContent` through the existing mechanic/blood workflow, resets conversational state on `start-session`, and returns the final response with `end-session` when requested. The manifest is published through `agent.include(chat_proto, publish_manifest=True)`. No verification switch or alternate chat implementation is used.

The prior `Agent mailbox not found` log means the account-side Mailbox connection still needs to be created in Inspector. This is not fixed by adding an A2A agent name. Almanac API registration, on-chain Almanac registration, and Agentverse mailbox connection are separate log/status steps: do not infer that one succeeded from another. Current Fetch.ai docs show the mailbox flow and also show Almanac contract registration in agent startup; if startup reports insufficient funds or registration errors, preserve those logs and verify the Agentverse/Almanac status with Fetch.ai before treating the address as discoverable in ASI:One. This project does not bypass registration or claim it has succeeded.

### Commands

```bash
python -m pip install -r requirements.txt
python -m pytest
python lifeline_agent.py
```

For the local browser and provider API, run this separately:

```bash
uvicorn provider_api:app --host 127.0.0.1 --port 8001
```

See the current official [uAgent creation and mailbox guide](https://innovationlab.fetch.ai/resources/docs/agent-creation/uagent-creation), [ASI:One Agent Chat Protocol tutorial](https://docs.asi1.ai/documentation/tutorials/agent-chat-protocol), and [ASI:One-compatible uAgent guide](https://innovationlab.fetch.ai/resources/docs/examples/chat-protocol/asi-compatible-uagents). Local tests do not verify Agentverse publication, ASI:One routing, a real provider, or real blood stock. Registration and a live ASI:One conversation must be confirmed in your account.

## Limitations

- Mechanic inventory and provider accept/reject actions are a deterministic simulated directory and provider API. There is no real roadside dispatch integration.
- Blood centre contacts are simulated and blood stock is unavailable. No live e-RaktKosh API was identified or connected.
- The lightweight intent/entity extraction uses deterministic text matching. Ambiguous location or service requests may need clarification.
- Local browser chat, ACP handler, and workflow tests verify application logic. Agentverse publication and real ASI:One invocation require mailbox registration and remain unverified until tested from an Agentverse account.
