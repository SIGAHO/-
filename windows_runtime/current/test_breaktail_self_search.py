import unittest

from breaktail_self import SelfRuntime, build_self_context, ground_self_reply


class SearchSelfTests(unittest.TestCase):
    def test_default_route_blocks_fake_search_result(self):
        ctx = build_self_context()
        r = ground_self_reply(
            "今の最新価格ネットで調べて教えて",
            "ネットで調べたら980円だった",
            ctx,
        )
        self.assertEqual(r["decision"], "replace")
        self.assertEqual(r["reason"], "web_search_adapter_unavailable")
        self.assertNotIn("980", r["reply"])

    def test_pure_clarification_is_allowed(self):
        ctx = build_self_context()
        draft = "何の価格？商品名教えて。"
        r = ground_self_reply("最新価格調べたい", draft, ctx)
        self.assertEqual(r["decision"], "use")
        self.assertEqual(r["reply"], draft)

    def test_fake_future_search_promise_is_blocked(self):
        ctx = build_self_context()
        r = ground_self_reply(
            "最新価格調べたい",
            "商品名くれれば検索するよ",
            ctx,
        )
        self.assertEqual(r["decision"], "replace")
        self.assertEqual(r["reason"], "web_search_adapter_unavailable")

    def test_honest_unavailable_reply_is_preserved(self):
        ctx = build_self_context()
        draft = "今はネット検索できないよ。"
        r = ground_self_reply(
            "最新価格ネットで調べて",
            draft,
            ctx,
        )
        self.assertEqual(r["decision"], "use")
        self.assertEqual(r["reply"], draft)

    def test_normal_price_chat_is_not_search_request(self):
        ctx = build_self_context()
        draft = "それはちょっと高いなｗ"
        r = ground_self_reply("この時計1万円だったわ", draft, ctx)
        self.assertEqual(r["decision"], "use")
        self.assertEqual(r["reply"], draft)

    def test_successful_trusted_search_preserves_model_draft(self):
        ctx = build_self_context(SelfRuntime(
            web_search_available=True,
            search_state="success",
            search_observation="商品A: 980円",
        ))
        draft = "検索結果では980円だった。"
        r = ground_self_reply("最新価格ネットで調べて", draft, ctx)
        self.assertEqual(r["decision"], "use")
        self.assertEqual(r["reply"], draft)

    def test_no_result_is_explicit(self):
        ctx = build_self_context(SelfRuntime(
            web_search_available=True,
            search_state="no_result",
        ))
        r = ground_self_reply("ネットで最新価格調べて", "何の商品？", ctx)
        self.assertEqual(r["decision"], "replace")
        self.assertEqual(r["reason"], "web_search_no_result")

    def test_error_is_explicit(self):
        ctx = build_self_context(SelfRuntime(
            web_search_available=True,
            search_state="error",
        ))
        r = ground_self_reply("ネットで最新価格調べて", "何の商品？", ctx)
        self.assertEqual(r["decision"], "replace")
        self.assertEqual(r["reason"], "web_search_error")

    def test_connected_not_attempted_fake_result_is_blocked(self):
        ctx = build_self_context(SelfRuntime(web_search_available=True))
        r = ground_self_reply(
            "ネットで最新価格調べて",
            "検索結果では1200円だった",
            ctx,
        )
        self.assertEqual(r["decision"], "replace")
        self.assertEqual(r["reason"], "web_search_not_attempted")

    def test_connected_not_attempted_clarification_is_allowed(self):
        ctx = build_self_context(SelfRuntime(web_search_available=True))
        draft = "何の価格？"
        r = ground_self_reply("最新価格調べたい", draft, ctx)
        self.assertEqual(r["decision"], "use")
        self.assertEqual(r["reply"], draft)

    def test_invalid_state_rejected(self):
        with self.assertRaises(ValueError):
            build_self_context(SelfRuntime(search_state="mystery"))

    def test_success_requires_observation(self):
        with self.assertRaises(ValueError):
            build_self_context(SelfRuntime(
                web_search_available=True,
                search_state="success",
                search_observation="",
            ))


if __name__ == "__main__":
    unittest.main()
