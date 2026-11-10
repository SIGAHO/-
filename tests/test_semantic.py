import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from companion_core import CompanionCore, SourceType
from companion_core.semantic import SemanticMemoryRetriever, cosine_vector
from companion_core.local_chat import LocalChatSession


class FixedEmbedder:
    def embed(self, text):
        mapping = {
            "脱進機の設計はどこまで進んだ？": [1.0, 0.0],
            "時計のがんぎ車を製作中": [0.98, 0.02],
            "今日はカレーを食べた": [0.0, 1.0],
            "別の話題": [0.0, 1.0],
        }
        return mapping.get(text, [0.0, 1.0])


class FakeModel:
    model = "fake:local"
    def __init__(self):
        self.messages = None

    def chat(self, messages):
        self.messages = messages
        return "返答"


class SemanticTests(unittest.TestCase):
    def test_vector_similarity_is_deterministic(self):
        self.assertAlmostEqual(cosine_vector([2.0, 0], [1.0, 0]), 1)
        self.assertAlmostEqual(cosine_vector([1.0, 0], [0.0, 1]), 0)
        self.assertEqual(cosine_vector([], []), 0)
        self.assertEqual(cosine_vector([1], [1, 2]), 0)

    def test_semantic_search_paraphrase_vs_unrelated(self):
        core = CompanionCore()
        core.memory.add("時計のがんぎ車を製作中", SourceType.USER_STATEMENT)
        core.memory.add("今日はカレーを食べた", SourceType.USER_STATEMENT)
        retriever = SemanticMemoryRetriever(FixedEmbedder(), minimum_similarity=0.3)
        hits = retriever.retrieve("脱進機の設計はどこまで進んだ？", core.memory.items)
        self.assertEqual([x["text"] for x in hits], ["時計のがんぎ車を製作中"])
        self.assertGreater(hits[0]["score"], 0.80)

    def test_no_semantic_recall_from_ai_outputs(self):
        core = CompanionCore()
        core.record_assistant_output("時計のがんぎ車を製作中")
        retriever = SemanticMemoryRetriever(FixedEmbedder())
        self.assertEqual(retriever.retrieve("脱進機の設計はどこまで進んだ？", core.memory.items), [])

    def test_character_chat_uses_semantic_memory_without_duplicate_current_turn(self):
        core = CompanionCore()
        core.handle("時計のがんぎ車を製作中")
        model = FakeModel()
        semantic = SemanticMemoryRetriever(FixedEmbedder(), minimum_similarity=0.3)
        chat = LocalChatSession(core, model, {"name": "Breaktail"}, semantic)
        chat.reply("脱進機の設計はどこまで進んだ？")
        system = model.messages[0]["content"]
        self.assertIn("時計のがんぎ車を製作中", system)
        self.assertEqual(model.messages[-1]["content"], "脱進機の設計はどこまで進んだ？")


if __name__ == "__main__":
    unittest.main()
