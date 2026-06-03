"""Ad-hoc smoke test: run the parser over fresh sentences and print results.

Uses entities deliberately different from the original 10-sentence test set so
we measure generalization, not memorization of the few-shot examples.
Delete this file after use.
"""

from lifegraph.config import load_config
from lifegraph.ollama_client import OllamaClient
from lifegraph.parser import InputParser

SENTENCES = [
    "I want to improve my public speaking before the TEDx event in October.",
    "I'm building a budgeting tool with Next.js, MongoDB, and Ollama running Gemma 2.",
    "I have to redo the lasagna recipe for Marco - the sauce came out too watery, probably too many tomatoes.",
    "I'm applying to the Robotics PhD at ETH Zurich on a recommendation from Professor Klein.",
    "I want to build a home lab on my old ThinkStation with a Quadro P2000 and 64GB RAM.",
    "My current Valorant goal is mastering Jett dashes and I grind it on the practice range.",
    "I shipped the Bistro Verde website with Svelte, Supabase, and a Cloudinary image pipeline - it's live.",
    "I'd like to study graph neural networks and how they apply to recommendation systems.",
    "One of my goals this week is to clear all the high-priority bugs in Linear.",
    "I'm debating whether Qwen 2.5 7B beats Gemma 2 9B for summarization in my app.",
]


def main() -> None:
    cfg = load_config()
    client = OllamaClient("http://127.0.0.1:11434", cfg.model, cfg.timeout)
    parser = InputParser(client)

    for i, sentence in enumerate(SENTENCES, 1):
        print("=" * 78)
        print(f"[{i}] {sentence}")
        try:
            g = parser.parse(sentence)
        except Exception as exc:  # noqa: BLE001 - smoke test, surface anything
            print(f"  ERROR: {type(exc).__name__}: {exc}")
            continue
        print("  NODES:")
        for n in g.nodes:
            attrs = f"  {n.attributes}" if n.attributes else ""
            print(f"    - {n.type.value:<13}{n.label}{attrs}")
        print("  EDGES:")
        for e in g.edges:
            print(
                f"    - {e.source_label} ({e.source_type.value}) "
                f"--[{e.type.value}]--> {e.target_label} ({e.target_type.value})"
            )


if __name__ == "__main__":
    main()
