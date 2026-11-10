"""Offline conversational CLI. Requires a locally running Ollama server."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from companion_core import CompanionCore
from companion_core.semantic import LocalOllamaEmbeddings, SemanticMemoryRetriever
from companion_core.local_chat import (
    LocalChatSession, LocalModelError, LocalOllama, load_character_card,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen2.5:14b")
    parser.add_argument("--semantic-model", default=None, help="e.g. bge-m3; optional offline semantic retrieval")
    parser.add_argument("--card", default="characters/breaktail.json")
    parser.add_argument("--events", default="data/conversation.jsonl")
    args = parser.parse_args()

    card = load_character_card(args.card)
    core = CompanionCore(event_path=args.events)
    semantic = SemanticMemoryRetriever(LocalOllamaEmbeddings(args.semantic_model)) if args.semantic_model else None
    chat = LocalChatSession(core, LocalOllama(args.model), card, semantic=semantic)
    print(f"Breaktail: local mode ({args.model}). /exit to quit. /diag for local diagnostics.")
    while True:
        try:
            line = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("/exit", "/quit"):
            break
        if line == "/diag":
            import json
            print(json.dumps(core.diagnostics(), ensure_ascii=False, indent=2))
            continue
        try:
            print("Breaktail>", chat.reply(line))
        except LocalModelError as exc:
            print("Error:", exc)
        except Exception as exc:
            print(f"Error ({type(exc).__name__}): {exc}")


if __name__ == "__main__":
    main()
