import asyncio
import logging
from uuid import uuid4

from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement, ChatMessage, EndSessionContent, StartSessionContent,
    TextContent,
)

import lifeline_agent as life


class FakeContext:
    def __init__(self):
        self.session = uuid4()
        self.logger = logging.getLogger("lifeline-test")
        self.sent = []

    async def send(self, target, message):
        self.sent.append(message)


def _message(text):
    return ChatMessage(content=[TextContent(type="text", text=text)])


def test_chat_protocol_declared_models_all_have_handlers():
    assert life.chat_proto.name == "AgentChatProtocol"
    assert life.chat_proto.version == "0.3.0"
    assert life.chat_proto.verify()
    assert {model.__name__ for model in life.chat_proto.models.values()} == {
        "ChatMessage", "ChatAcknowledgement"
    }
    manifest = life.chat_proto.manifest()
    assert manifest["metadata"]["digest"] == life.chat_proto.digest
    assert life.chat_proto.digest in life.agent.protocols
    message_digests = {model.__name__: digest for digest, model in life.chat_proto.models.items()}
    interactions = {row["request"]: row["responses"] for row in manifest["interactions"]}
    assert interactions[message_digests["ChatMessage"]] == [message_digests["ChatAcknowledgement"]]
    assert interactions[message_digests["ChatAcknowledgement"]] == []


def test_chat_message_handler_preserves_roadside_and_blood_flows():
    async def run():
        ctx = FakeContext()
        sender = "agent1test"

        async def send(text):
            await life.handle_message(ctx, sender, _message(text))
            return ctx.sent[-1]

        discovery = await send(
            "My car broke down near Yamuna Expressway, close to Greater Noida. Engine wont start."
        )
        assert "SIMULATED" in discovery.text()
        assert "Choose an option" in discovery.text()

        selection = await send("1")
        assert "Reply YES" in selection.text()

        pending = await send("YES")
        assert "PENDING" in pending.text()
        assert "only the provider can accept or reject it" in pending.text()

        blood_ctx = FakeContext()
        await life.handle_message(
            blood_ctx,
            sender,
            _message("I need two units of O-positive blood near Greater Noida"),
        )
        blood_reply = blood_ctx.sent[-1].text()
        assert "SIMULATED" in blood_reply
        assert "not available from a verified live source" in blood_reply

    asyncio.run(run())


def test_chat_acknowledgement_handler_accepts_protocol_ack():
    async def run():
        await life.handle_acknowledgement(
            FakeContext(), "agent1test", ChatAcknowledgement(acknowledged_msg_id=uuid4())
        )

    asyncio.run(run())


def test_chat_session_start_and_end_reset_context():
    async def run():
        ctx = FakeContext()
        sender = f"agent-session-{uuid4()}"
        key = f"{sender}:{ctx.session}"

        await life.handle_message(
            ctx, sender,
            ChatMessage(content=[StartSessionContent(type="start-session")]),
        )
        assert isinstance(ctx.sent[-1], ChatAcknowledgement)

        await life.handle_message(ctx, sender, _message("My car broke down"))
        assert "Where is the vehicle" in ctx.sent[-1].text()
        assert life.db.get_conversation(key)["workflow"] == "mechanic"

        final = ChatMessage(content=[
            TextContent(type="text", text="I need roadside help"),
            EndSessionContent(type="end-session"),
        ])
        await life.handle_message(ctx, sender, final)
        response = ctx.sent[-1]
        assert isinstance(response, ChatMessage)
        assert any(isinstance(item, EndSessionContent) for item in response.content)
        assert life.db.get_conversation(key) == {}

        # A location in a later turn cannot continue the ended mechanic flow.
        await life.handle_message(ctx, sender, _message("Yamuna Expressway"))
        assert "SIMULATED DIRECTORY" not in ctx.sent[-1].text()

    asyncio.run(run())


def test_chat_without_text_is_acknowledged_without_fake_reply():
    async def run():
        ctx = FakeContext()
        message = ChatMessage(content=[StartSessionContent(type="start-session")])
        await life.handle_message(ctx, "agent-invalid-content", message)
        assert len(ctx.sent) == 1
        assert isinstance(ctx.sent[0], ChatAcknowledgement)
        assert ctx.sent[0].acknowledged_msg_id == message.msg_id

    asyncio.run(run())
