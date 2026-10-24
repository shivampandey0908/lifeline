"""LifeLine uAgents entry point implementing the official ASI:One Chat Protocol."""
import logging
import secrets
from datetime import datetime, timezone
from uuid import uuid4

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement, ChatMessage, EndSessionContent, StartSessionContent,
    TextContent, chat_protocol_spec,
)

from config import settings
from database import db
from dialogue_service import respond_text

if __name__ == "__main__" and not settings.seed:
    raise SystemExit(
        "Set LIFELINE_SEED in .env to a private, stable value before starting "
        "the mailbox agent; do not reuse a public or example seed."
    )

logging.basicConfig(level=logging.INFO)
db.seed_demo(settings.provider_token)
# When imported by tests without a configured seed, use an in-memory throwaway
# identity instead of letting uAgents persist an unnamed generated key locally.
# The __main__ guard below prevents this fallback from running as the service.
agent = Agent(name=settings.agent_name, seed=settings.seed or secrets.token_urlsafe(32), port=settings.agent_port,
              mailbox=True, publish_agent_details=True, readme_path="README.md")
chat_proto = Protocol(spec=chat_protocol_spec)


def create_text_chat(text: str, end_session: bool = False) -> ChatMessage:
    content = [TextContent(type="text", text=text)]
    if end_session:
        content.append(EndSessionContent(type="end-session"))
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content)


def handle_text(conversation_key: str, text: str, message_id: str) -> str:
    """Retain the ACP entrypoint API while sharing workflows with local chat."""
    return respond_text(conversation_key, text, message_id)


@chat_proto.on_message(ChatMessage)
async def handle_message(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
    conversation_key = f"{sender}:{ctx.session}"
    start_session = any(isinstance(item, StartSessionContent) for item in msg.content)
    end_session = any(isinstance(item, EndSessionContent) for item in msg.content)
    if start_session:
        db.save_conversation(conversation_key, {})
    # A session-start-only envelope is valid ACP traffic. It has no user text
    # to process, but its acknowledgement above confirms receipt.
    texts = [item.text for item in msg.content if isinstance(item, TextContent)]
    if not texts:
        if end_session:
            db.save_conversation(conversation_key, {})
        return
    try:
        reply = handle_text(conversation_key, "\n".join(texts), str(msg.msg_id))
    except Exception:
        ctx.logger.exception("LifeLine message handling failed")
        reply = "I hit a processing problem. Please try again, or contact the service provider directly if this is urgent."
    await ctx.send(sender, create_text_chat(reply, end_session=end_session))
    if end_session:
        # The final turn can still use the existing context, then discard it.
        db.save_conversation(conversation_key, {})


@chat_proto.on_message(ChatAcknowledgement)
async def handle_acknowledgement(ctx: Context, sender: str, msg: ChatAcknowledgement):
    """Acknowledge the second interaction declared by AgentChatProtocol 0.3.0."""
    ctx.logger.debug(
        "Received chat acknowledgement for message %s",
        msg.acknowledged_msg_id,
    )


agent.include(chat_proto, publish_manifest=True)


if __name__ == "__main__":
    print(f"Starting {settings.agent_name}; address={agent.address}")
    agent.run()
