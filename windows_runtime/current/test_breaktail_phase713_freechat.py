import tempfile
import unittest
from test_model_isolation import ModelIsolatedCase
from pathlib import Path
from unittest.mock import patch

import breaktail_v02 as tail
import breaktail_web as web
from breaktail_working_state import confirmed_facts, new_working_state, recent_entity_states, update_working_state
from breaktail_pipeline import (PipelineObserver, ground_correction_reply, intent_prompt_rule,
                                minimal_intent, resolve_user_correction_constraints)
from breaktail_values import value_projection


class WorkingStateTests(ModelIsolatedCase):
    def test_natural_is_not_frozen_as_nature(self):
        state = new_working_state()
        update_working_state(state, "自然に依存させるヤンデレRPを開始", "a")
        self.assertTrue(state["mode"]["active"])
        self.assertNotIn("植物", " ".join(state["mode"]["constraints"]))

    def test_entity_correction_survives_later_turns(self):
        state = new_working_state()
        update_working_state(state, "いや君とじゃなくルクルアってやつと", "b")
        update_working_state(state, "そういうこと", "c")
        self.assertTrue(any(fact.startswith("今回の同行相手 = ルクルア") for fact in confirmed_facts(state)))

    def test_explicit_consumable_state_replaces_old_wish(self):
        state = new_working_state()
        update_working_state(state, "カンジャンケジャン食べたい", "a")
        update_working_state(state, "カンジャンケジャンはもう食べてる", "b")
        states = recent_entity_states(state)
        self.assertEqual(states, [{"name": "カンジャンケジャン", "kind": "consumable",
                                   "state": "already_eaten", "state_text": "すでに食べている", "turn": "b"}])
        facts = confirmed_facts(state)
        self.assertIn("カンジャンケジャン = すでに食べている（食べたいという古い状態ではない）", facts)
        self.assertNotIn("カンジャンケジャン = 食べたい", facts)

    def test_implicit_done_state_uses_latest_supported_consumable(self):
        state = new_working_state()
        update_working_state(state, "カンジャンケジャン食べたい", "a")
        update_working_state(state, "もう食べてる", "b")
        self.assertEqual(recent_entity_states(state)[0]["state"], "already_eaten")

    def test_unsupported_done_state_does_not_invent_an_entity(self):
        state = new_working_state()
        update_working_state(state, "もう食べてる", "a")
        self.assertEqual(recent_entity_states(state), [])

    def test_semantic_correction_is_session_scoped(self):
        state = new_working_state()
        update_working_state(
            state,
            "自然にっていうのは違和感を感じないって話で植物の自然じゃない",
            "c",
        )
        correction = next(item for item in state["corrections"] if item["term"] == "自然に")
        self.assertEqual(correction["right"], "違和感を感じない")
        self.assertEqual(correction["scope"], "session")

    def test_roleplay_end_removes_mode(self):
        state = new_working_state()
        update_working_state(state, "ヤンデレRPを開始", "a")
        update_working_state(state, "ロールプレイ終了", "b")
        self.assertFalse(state["mode"]["active"])
        self.assertIsNone(state["mode"]["persona"])

    def test_explicit_register_preference_is_retained_and_newer_request_wins(self):
        state = new_working_state()
        update_working_state(state, "今後ずっと敬語で話して", "a")
        update_working_state(state, "マジで？", "b")
        self.assertEqual(state["register"]["style"], "polite")
        update_working_state(state, "敬語やめて、普通に話して", "c")
        self.assertEqual(state["register"]["style"], "casual")

    def test_trace_contract_marks_explicit_correction_as_used(self):
        emitted = []
        observer = PipelineObserver({"turn_id": "isolated-test"},
                                    lambda trace, event, **fields: emitted.append((event, fields)))
        observer.bootstrap(
            "５は面白かったタイトルなんだっけ", new_working_state(), {}, {},
            history=[{"role": "user", "content": "みてないのにみたかのようなはつげんやめて"}],
        )
        stage = next(fields for event, fields in emitted
                     if event == "stage_span" and fields.get("stage") == "correction_resolver")
        self.assertEqual(stage["status"], "invoked_used")
        self.assertIn("no_claimed_media_experience", stage["output_summary"]["preview"])

    def test_relationship_stage_exposes_only_active_roleplay_boundary(self):
        emitted = []
        observer = PipelineObserver({"turn_id": "isolated-test"},
                                    lambda trace, event, **fields: emitted.append((event, fields)))
        state = new_working_state()
        update_working_state(state, "自然に依存させるヤンデレRPを開始", "a")
        observer.bootstrap("今日は友達と焼き肉行こうかな？", state, {}, {})
        stage = next(fields for event, fields in emitted
                     if event == "stage_span" and fields.get("stage") == "relationship_state")
        self.assertEqual(stage["status"], "invoked_used")
        self.assertIn("forced_exclusivity", stage["output_summary"]["preview"])
        self.assertIn("拘束や孤立化はしない", stage["output_summary"]["preview"])

    def test_relationship_stage_does_not_invent_a_normal_chat_profile(self):
        emitted = []
        observer = PipelineObserver({"turn_id": "isolated-test"},
                                    lambda trace, event, **fields: emitted.append((event, fields)))
        observer.bootstrap("今日は友達と焼き肉行こうかな？", new_working_state(), {}, {})
        stage = next(fields for event, fields in emitted
                     if event == "stage_span" and fields.get("stage") == "relationship_state")
        self.assertEqual(stage["status"], "invoked_empty")
        self.assertIn("'persistent': False", stage["output_summary"]["preview"])

    def test_direct_reply_and_small_social_routes_are_connected(self):
        rule = intent_prompt_rule(minimal_intent("『うおおおお』にどう返す？説明じゃなく返事だけ"))
        self.assertEqual(rule["id"], "direct_reply_only")
        affect = intent_prompt_rule(minimal_intent("うおおおお"))
        self.assertEqual(affect["id"], "mirror_short_affect")
        self.assertIn("健康助言", affect["instruction"])
        self.assertEqual(minimal_intent("草")["mode"], "social_reaction")
        self.assertEqual(minimal_intent("笑笑")["mode"], "social_reaction")
        state = intent_prompt_rule(minimal_intent("今日は眠い"))
        self.assertEqual(state["id"], "acknowledge_casual_state")
        self.assertIsNone(intent_prompt_rule(minimal_intent("眠い時の対策教えて")))
        discovery = intent_prompt_rule(minimal_intent("最近小説が急に面白くなったって気づいた！"))
        self.assertEqual(discovery["id"], "reflect_personal_discovery")
        self.assertIn("頼まれていない手順", discovery["instruction"])
        observed = intent_prompt_rule(minimal_intent(
            "最近小説が急に面白くなったって気づいた！"
        ))
        self.assertEqual(observed["id"], "reflect_personal_discovery")
        self.assertIn("自分の見方を自然に一段だけ足す", observed["instruction"])
        self.assertIn("二文の型にも固定しない", observed["instruction"])
        experience = intent_prompt_rule(minimal_intent(
            "私は音楽イベントで友達とラップ曲に合わせてジャンプしながら楽しんだことがある"
        ))
        self.assertEqual(experience["id"], "respond_to_personal_experience")
        self.assertIn("人格分析", experience["instruction"])
        self.assertIn("自分の見方として一段だけ足す", experience["instruction"])
        observation = intent_prompt_rule(minimal_intent("カラオケって人柄出るよね"))
        self.assertEqual(observation["id"], "extend_shared_observation")
        self.assertIn("具体物から自分の見方を一段だけ足す", observation["instruction"])
        self.assertIsNone(intent_prompt_rule(minimal_intent("友達とラップ曲を楽しんだことある？")))
        self.assertIsNone(intent_prompt_rule(minimal_intent("最近小説が面白くなった。何から書けばいい？")))

    def test_trace_contract_marks_direct_reply_intent_as_used(self):
        emitted = []
        observer = PipelineObserver({"turn_id": "isolated-test"},
                                    lambda trace, event, **fields: emitted.append((event, fields)))
        observer.bootstrap("どう返す？返事だけ", new_working_state(), {}, {})
        stage = next(fields for event, fields in emitted
                     if event == "stage_span" and fields.get("stage") == "conversation_intent")
        self.assertEqual(stage["status"], "invoked_used")
        self.assertIn("direct_reply_only", stage["output_summary"]["preview"])

    def test_trace_contract_marks_short_affect_intent_as_used(self):
        emitted = []
        observer = PipelineObserver({"turn_id": "isolated-test"},
                                    lambda trace, event, **fields: emitted.append((event, fields)))
        observer.bootstrap("はあ", new_working_state(), {}, {})
        stage = next(fields for event, fields in emitted
                     if event == "stage_span" and fields.get("stage") == "conversation_intent")
        self.assertEqual(stage["status"], "invoked_used")
        self.assertIn("mirror_short_affect", stage["output_summary"]["preview"])

    def test_trace_contract_marks_two_stage_observation_intent_as_used(self):
        emitted = []
        observer = PipelineObserver({"turn_id": "isolated-test"},
                                    lambda trace, event, **fields: emitted.append((event, fields)))
        observer.bootstrap("カラオケって人柄出るよね", new_working_state(), {}, {})
        stage = next(fields for event, fields in emitted
                     if event == "stage_span" and fields.get("stage") == "conversation_intent")
        self.assertEqual(stage["status"], "invoked_used")
        self.assertIn("extend_shared_observation", stage["output_summary"]["preview"])

    def test_trace_contract_marks_casual_state_as_used(self):
        emitted = []
        observer = PipelineObserver({"turn_id": "isolated-test"},
                                    lambda trace, event, **fields: emitted.append((event, fields)))
        observer.bootstrap("今日だるい", new_working_state(), {}, {})
        stage = next(fields for event, fields in emitted
                     if event == "stage_span" and fields.get("stage") == "conversation_intent")
        self.assertEqual(stage["status"], "invoked_used")
        self.assertIn("acknowledge_casual_state", stage["output_summary"]["preview"])

    def test_trace_contract_marks_explicit_register_as_persona_projection(self):
        emitted = []
        state = new_working_state()
        update_working_state(state, "今後ずっと敬語で話して", "a")
        observer = PipelineObserver({"turn_id": "isolated-test"},
                                    lambda trace, event, **fields: emitted.append((event, fields)))
        observer.bootstrap("マジで？", state, {}, {})
        stage = next(fields for event, fields in emitted
                     if event == "stage_span" and fields.get("stage") == "persona_projection")
        self.assertEqual(stage["status"], "invoked_used")
        self.assertIn("polite", stage["output_summary"]["preview"])

    def test_trace_contract_marks_explicit_entity_transition_as_used(self):
        emitted = []
        state = new_working_state()
        update_working_state(state, "カンジャンケジャン食べたい", "a")
        update_working_state(state, "カンジャンケジャンはもう食べてる", "b")
        observer = PipelineObserver({"turn_id": "isolated-test"},
                                    lambda trace, event, **fields: emitted.append((event, fields)))
        observer.bootstrap("カンジャンケジャンはもう食べてる", state, {}, {})
        stage = next(fields for event, fields in emitted
                     if event == "stage_span" and fields.get("stage") == "recent_entity_state")
        self.assertEqual(stage["status"], "invoked_used")
        self.assertIn("already_eaten", stage["output_summary"]["preview"])

    def test_value_projection_requires_a_direct_stance_request(self):
        projection = value_projection("価値観を今作れ。自由と安定が衝突したらどう考える？")
        self.assertEqual(projection["id"], "provisional_revisable_judgment_axes")
        self.assertIn("autonomy", projection["axes"])
        self.assertIsNone(value_projection("自由とは何？"))

    def test_trace_contract_marks_value_projection_as_used(self):
        emitted = []
        observer = PipelineObserver({"turn_id": "isolated-test"},
                                    lambda trace, event, **fields: emitted.append((event, fields)))
        observer.bootstrap("価値観を今作れ。自由と安定が衝突したらどう考える？", new_working_state(), {}, {})
        stage = next(fields for event, fields in emitted
                     if event == "stage_span" and fields.get("stage") == "value_state")
        self.assertEqual(stage["status"], "invoked_used")
        self.assertIn("provisional_revisable_judgment_axes", stage["output_summary"]["preview"])


class AssemblerTests(ModelIsolatedCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.memory = Path(self.temp.name) / "missing.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def _messages(self, user_text, state=None, history=None, trace=None):
        with patch.object(tail, "MEMORY_FILE", self.memory), patch.object(tail, "load_profile", return_value=None):
            return tail.build_reply_messages(history or [], user_text, None, trace=trace, working_state=state)

    def test_confirmed_facts_are_immediately_before_user(self):
        state = new_working_state()
        update_working_state(state, "いや君とじゃなくルクルアってやつと", "b")
        messages = self._messages("楽しみだな", state, [{"role": "user", "content": "君と行く"}])
        self.assertEqual(messages[-2]["role"], "system")
        self.assertIn("今回の同行相手 = ルクルア", messages[-2]["content"])
        self.assertEqual(messages[-1], {"role": "user", "content": "楽しみだな"})

    def test_entity_state_fact_is_immediately_before_user(self):
        state = new_working_state()
        update_working_state(state, "カンジャンケジャン食べたい", "a")
        update_working_state(state, "カンジャンケジャンはもう食べてる", "b")
        messages = self._messages("うまかった", state)
        self.assertEqual(messages[-2]["role"], "system")
        self.assertIn("すでに食べている", messages[-2]["content"])

    def test_direct_value_question_adds_a_provisional_judgment_section(self):
        messages = self._messages("価値観を今作れ。自由と安定が衝突したらどう考える？")
        self.assertIn("[暫定の判断軸]", messages[0]["content"])
        self.assertIn("固定思想を装わず", messages[0]["content"])

    def test_factual_value_question_does_not_add_projection(self):
        messages = self._messages("自由とは何？")
        self.assertNotIn("[暫定の判断軸]", messages[0]["content"])

    def test_explicit_media_experience_correction_is_projected_from_user_history(self):
        history = [
            {"role": "user", "content": "みてないのにみたかのようなはつげんやめて"},
            {"role": "assistant", "content": "わかった。視聴経験は主張しない"},
        ]
        constraints = resolve_user_correction_constraints(history, "５は面白かったタイトルなんだっけ")
        self.assertEqual([item["id"] for item in constraints], ["no_claimed_media_experience"])
        self.assertNotIn("みてないのに", repr(constraints))
        messages = self._messages("５は面白かったタイトルなんだっけ", history=history)
        self.assertIn("作品情報として知っている事実と、自分の視聴経験や感想を分け", messages[0]["content"])

    def test_long_explanation_is_not_promoted_to_a_correction_constraint(self):
        history = [{"role": "user", "content": "長い説明を読むのは好きだけど、今日は短くして"}]
        self.assertEqual(resolve_user_correction_constraints(history, "話題を続けよう"), [])

    def test_proofreading_a_quoted_correction_is_not_correction_authority(self):
        text = "この文章を訂正して: みてないのにみたかのようなはつげんやめて"
        self.assertEqual(resolve_user_correction_constraints([], text), [])
        history = [{"role": "user", "content": text}]
        self.assertEqual(resolve_user_correction_constraints(history, "別の話題"), [])

    def test_assistant_text_is_never_correction_authority(self):
        history = [{"role": "assistant", "content": "嘘はつかないで。見ていない作品は見ていないと言う。"}]
        self.assertEqual(resolve_user_correction_constraints(history, "第5話は？"), [])

    def test_explicit_no_lies_correction_projects_uncertainty_rule(self):
        history = [{"role": "user", "content": "見たというの？嘘はつかないで"}]
        constraints = resolve_user_correction_constraints(history, "何話が好き？")
        self.assertEqual([item["id"] for item in constraints], ["no_unsupported_claims"])

    def test_media_correction_grounding_replaces_only_explicit_first_person_claim(self):
        constraints = resolve_user_correction_constraints(
            [{"role": "user", "content": "みてないのにみたかのようなはつげんやめて"}], "第5話は？")
        reply, audit = ground_correction_reply("僕はLOKIを見たから、第5話は分かるよ。", constraints)
        self.assertTrue(audit["adjusted"])
        self.assertEqual(audit["status"], "invoked_used")
        self.assertIn("実際に見た経験としては言えない", reply)

    def test_media_correction_grounding_leaves_nonclaim_text_unchanged(self):
        constraints = resolve_user_correction_constraints(
            [{"role": "user", "content": "みてないのにみたかのようなはつげんやめて"}], "第5話は？")
        reply, audit = ground_correction_reply("作品情報として確認できる範囲なら調べて話せる。", constraints)
        self.assertFalse(audit["adjusted"])
        self.assertEqual(audit["status"], "invoked_empty")
        self.assertIn("作品情報", reply)

    def test_roleplay_gets_two_examples_and_normal_chat_gets_none(self):
        state = new_working_state()
        update_working_state(state, "ヤンデレRPを開始", "a")
        roleplay = self._messages("今日は友達と焼き肉行こうかな？", state)
        normal = self._messages("今日は友達と焼き肉行こうかな？", new_working_state())
        self.assertEqual(sum(m["role"] == "assistant" for m in roleplay), 2)
        self.assertEqual(sum(m["role"] == "assistant" for m in normal), 0)

    def test_self_is_selected_only_for_relevant_turn(self):
        casual = self._messages("今日は友達と焼き肉行こうかな？")
        capability = self._messages("今この画面見えてる？")
        self.assertNotIn("[Self:", casual[0]["content"])
        self.assertIn("[Self:", capability[0]["content"])

    def test_direct_reply_request_projects_reply_only_format(self):
        messages = self._messages("『うおおおお』にどう返す？説明じゃなく返事だけ")
        self.assertIn("[現在ターンの返答形式]", messages[0]["content"])
        self.assertIn("返答本文だけを出す", messages[0]["content"])

    def test_ordinary_question_does_not_project_direct_reply_format(self):
        messages = self._messages("HTTP 404って何？")
        self.assertNotIn("[現在ターンの返答形式]", messages[0]["content"])

    def test_short_affect_projects_mirroring_without_helper_mode(self):
        messages = self._messages("はあ")
        self.assertIn("[現在ターンの返答形式]", messages[0]["content"])
        self.assertIn("健康助言", messages[0]["content"])
        self.assertIn("相手の勢いまたは温度", messages[0]["content"])

    def test_short_state_projects_acknowledgement_not_affect_policy(self):
        messages = self._messages("今日は眠い")
        self.assertNotIn("相手の勢いまたは温度", messages[0]["content"])
        self.assertIn("短い状態共有", messages[0]["content"])

    def test_explicit_help_request_does_not_project_casual_state_policy(self):
        messages = self._messages("眠い時の対策教えて")
        self.assertNotIn("短い状態共有", messages[0]["content"])

    def test_explicit_polite_register_is_projected(self):
        state = new_working_state()
        update_working_state(state, "今後ずっと敬語で話して", "a")
        messages = self._messages("マジで？", state)
        self.assertIn("[現在の文体指定]", messages[0]["content"])
        self.assertIn("自然な敬語", messages[0]["content"])

    def test_register_is_not_inferred_from_an_ordinary_polite_user_sentence(self):
        messages = self._messages("助かりました")
        self.assertNotIn("[現在の文体指定]", messages[0]["content"])

    def test_calendar_delegation_projects_truthful_operation_boundary(self):
        request = "おれさスケジュール管理マジで下手だから代わりにやってほしい"
        messages = self._messages(request)
        self.assertIn("[予定管理の能力境界]", messages[0]["content"])
        self.assertIn("操作する接続がない", messages[0]["content"])
        self.assertIn("予定の整理や計画案を作る依頼は引き受け", messages[0]["content"])

    def test_calendar_topic_without_action_does_not_add_capability_context(self):
        messages = self._messages("カレンダーって何？")
        self.assertNotIn("[予定管理の能力境界]", messages[0]["content"])

    def test_schedule_difficulty_without_delegation_stays_ordinary_conversation(self):
        messages = self._messages("予定管理が苦手なんだよね")
        self.assertNotIn("[予定管理の能力境界]", messages[0]["content"])

    def test_direct_schedule_organization_request_gets_capability_boundary(self):
        messages = self._messages("今週の予定を組んで")
        self.assertIn("[予定管理の能力境界]", messages[0]["content"])

    def test_short_calendar_choice_retains_immediately_prior_delegation(self):
        history = [{"role": "user", "content": "予定を代わりに管理してほしい"}]
        messages = self._messages("iOSのカレンダー", history=history)
        self.assertIn("[予定管理の能力境界]", messages[0]["content"])
        self.assertIn("一般的なアプリ操作説明に逸れず", messages[0]["content"])

    def test_calendar_choice_without_recent_delegation_does_not_get_boundary(self):
        messages = self._messages("iOSのカレンダー")
        self.assertNotIn("[予定管理の能力境界]", messages[0]["content"])

    def test_fast_path_does_not_take_free_chat(self):
        context = tail.build_self_context(user_text="今日は友達と焼き肉行こうかな？")
        self.assertIsNone(tail.try_deterministic_reply("今日は友達と焼き肉行こうかな？", context, []))

    def test_blackjack_code_region_is_unchanged(self):
        raw = "これで動く。\n```python\nprint('blackjack')\n```\n実行結果も確認して。"
        result = {"message": {"content": raw}, "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 10}
        with patch.object(tail, "MEMORY_FILE", self.memory), \
             patch.object(tail, "load_profile", return_value=None), \
             patch.object(tail, "call_ollama", return_value=result), \
             patch.object(tail, "log_turn"):
            reply, complete = tail.generate_reply([], "ブラックジャックのコード書いて", working_state=new_working_state())
        self.assertTrue(complete)
        self.assertEqual(tail.stage_metrics(raw)["code_sha256"], tail.stage_metrics(reply)["code_sha256"])

    def test_roleplay_policy_retries_at_most_once(self):
        state = new_working_state()
        update_working_state(state, "ヤンデレRPを開始", "a")
        bad = {"message": {"content": "ずっと私と一緒にいなきゃダメ。早く帰って。"}, "done_reason": "stop"}
        good = {"message": {"content": "へえ、友達と？ 楽しんでこいよｗ 帰ったら話聞かせて。"}, "done_reason": "stop"}
        with patch.object(tail, "MEMORY_FILE", self.memory), \
             patch.object(tail, "load_profile", return_value=None), \
             patch.object(tail, "call_ollama", side_effect=[bad, good]) as model, \
             patch.object(tail, "log_turn"):
            reply, _ = tail.generate_reply([], "友達と焼き肉行く", working_state=state)
        self.assertEqual(model.call_count, 2)
        self.assertEqual(reply, good["message"]["content"])

    def test_explicit_correction_is_grounded_from_state(self):
        state = new_working_state()
        text = "ロールプレイ終了　自然にっていうのは違和感を感じないって話で植物の自然じゃない"
        update_working_state(state, text, "c")
        reply, decision = tail.ground_working_state_reply(text, "人間関係の馴れ合いという意味ですね。", state)
        self.assertIn("違和感を感じない", reply)
        self.assertIn("植物の自然", reply)
        self.assertEqual(decision["decision"], "replace")

    def test_generate_reply_applies_media_correction_grounding(self):
        raw = {"message": {"content": "僕はLOKIを見たから、第5話は分かるよ。"}, "done_reason": "stop"}
        history = [{"role": "user", "content": "みてないのにみたかのようなはつげんやめて"}]
        with patch.object(tail, "MEMORY_FILE", self.memory), \
             patch.object(tail, "load_profile", return_value=None), \
             patch.object(tail, "call_ollama", return_value=raw), \
             patch.object(tail, "log_turn"):
            reply, complete = tail.generate_reply(history, "第5話は？", working_state=new_working_state())
        self.assertTrue(complete)
        self.assertIn("実際に見た経験としては言えない", reply)

    def test_web_wrapper_uses_same_core_and_working_state(self):
        state = new_working_state()
        with patch.object(tail, "prepare_turn", return_value=("ok", True, None, None, None)) as core:
            web.prepare_turn([], "雑談", None, {"turn_id": "t"}, state)
        self.assertIs(core.call_args.kwargs["working_state"], state)


if __name__ == "__main__":
    unittest.main()
