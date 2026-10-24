from config import _load_agent_seed
from uagents_core.identity import Identity


def test_seed_loader_rejects_empty_and_repository_placeholders():
    assert _load_agent_seed({}) is None
    assert _load_agent_seed({"LIFELINE_SEED": "replace-with-a-long-random-private-seed"}) is None
    assert _load_agent_seed({"LIFELINE_SEED": "paste_your_generated_secret_here"}) is None


def test_seed_loader_preserves_a_private_seed_value():
    seed = "private-seed-value-from-the-environment-1234567890"
    assert _load_agent_seed({"LIFELINE_SEED": seed}) == seed
    # uAgents derives keys by hashing arbitrary seed strings; this is not a
    # mnemonic parser and accepts an opaque high-entropy value.
    assert Identity.from_seed(seed, 0).address.startswith("agent1")
