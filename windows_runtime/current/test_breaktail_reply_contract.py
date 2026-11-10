import json
import unittest
from test_model_isolation import ModelIsolatedCase
from unittest.mock import patch
import breaktail_v02 as tail
from breaktail_working_state import new_working_state,update_working_state
from breaktail_reply_contract import build_contract,violations,sentences,repetition,remove_unrequested_sentences,decode_retry


class ReplyContractTests(ModelIsolatedCase):
    def test_reported_speech_ending_is_not_imperative(self):
        contract=build_contract(new_working_state(),'その話を聞いた。助言はいらない。')
        self.assertNotIn('imperative_mood',violations('歩いた方が速かったんだって。',contract))
    def test_concrete_sharing_needs_more_than_bare_acknowledgement(self):
        contract=build_contract(new_working_state(),'ずっと探していた鍵が、今朝かばんの一番小さいポケットから出てきた。')
        self.assertIn('bare_acknowledgement_to_concrete_sharing',violations('へえ、そうなんだ。',contract))
        self.assertNotIn('bare_acknowledgement_to_concrete_sharing',violations('一番小さいポケットが盲点だったね。',contract))
        self.assertNotIn('bare_acknowledgement_to_concrete_sharing',violations('了解。',build_contract(new_working_state(),'短く話して。')))
    def test_requested_greeting_cannot_degenerate_to_acknowledgement(self):
        contract=build_contract(new_working_state(),'時計係にひとこと挨拶して。')
        self.assertIn('acknowledgement_instead_of_requested_response',violations('うん。',contract))
        self.assertIn('missing_requested_greeting',violations('おはよう。',contract))
        self.assertNotIn('missing_requested_greeting',violations('時計係、おはよう。',contract))

    def test_no_advice_variants_apply_to_current_turn(self):
        for wording in ('助言なしで。','解決策はいらない。','アドバイスなしで。'):
            self.assertTrue(build_contract(new_working_state(),wording)['no_advice'])

    def test_foreign_contamination_is_regenerated_instead_of_silently_deleted(self):
        responses=iter(['時計が急に止まったね。Follow rules.部屋が静かだね。',
                        json.dumps({'sentences':['時計まで一息ついてるみたいだね。']},ensure_ascii=False)])
        def model(*a,**kw):return {'message':{'content':next(responses)},'done_reason':'stop'}
        with patch.object(tail,'call_ollama',side_effect=model),patch.object(tail,'log_turn'):
            reply,complete=tail.generate_reply([],'机の時計が急に止まった。')
        self.assertTrue(complete)
        self.assertEqual(reply,'時計まで一息ついてるみたいだね。')

    def test_current_detailed_request_overrides_persistent_brief_preference(self):
        c=build_contract(self.state(),'仕組みを詳しく、全部説明して。')
        self.assertIsNone(c['max_sentences'])
        self.assertIsNone(c['max_chars'])

    def test_problem_statement_count_is_not_a_reply_format(self):
        text='三文で、正しいのはちょうど二つ。答えは一つに決まる？理由も短く。'
        self.assertIsNone(build_contract(new_working_state(),text)['exact_sentences'])
        self.assertEqual(build_contract(new_working_state(),'二文で説明して。')['exact_sentences'],2)
        self.assertEqual(build_contract(new_working_state(),'二文だけの短編を作って。')['exact_sentences'],2)

    def test_plain_sharing_does_not_invite_remedies_but_requested_advice_does(self):
        self.assertTrue(build_contract(new_working_state(),'買ったばかりの手袋を片方なくした。')['no_advice'])
        self.assertFalse(build_contract(new_working_state(),'手袋をなくした時はどうしたらいい？')['no_advice'])
        state=new_working_state();state['mode']['active']=True
        self.assertFalse(build_contract(state,'友達とご飯へ行く。')['no_advice'])

    def state(self):
        state=new_working_state()
        update_working_state(state,'アドバイスより、短く雑談して。敬語なし。')
        return state

    def test_sentence_count_does_not_consume_every_other_boundary(self):
        self.assertEqual(len(sentences('一つ。二つ。三つ。')),3)
        self.assertEqual(len(sentences('「本当？」と聞いた。『そう。』と答えた。')),2)

    def test_measured_bad_advice_is_rejected(self):
        contract=build_contract(self.state(),'袋の底でパンがつぶれてた。')
        for bad in ['次はもっと気をつけて袋に余裕を持たせようね。',
                    '次の機会に気をつけて買えば大丈夫だよ。',
                    '寂しいときは誰かと話すのもいいよね。',
                    '寂しい気持ちは無理しないでいいよ。',
                    '寂しい気持ちは否定しちゃダメだよ。',
                    'パンも人も休む日が必要だしね。',
                    '運がいいって思え。',
                    '今日はゆっくり休んだほうがいいよ。']:
            self.assertIn('unrequested_advice_or_reassurance',violations(bad,contract))

    def test_explicit_advice_overrides_general_preference(self):
        self.assertNotIn('unrequested_advice_or_reassurance',violations(
            '早めに休んだほうがいいよ。',build_contract(self.state(),'今はアドバイスして。')))

    def test_unlisted_imperative_inflection_is_repaired_not_deleted(self):
        c=build_contract(self.state(),'パンがつぶれてた。')
        self.assertIn('imperative_mood',violations('次のパンは柔らかいうちに食べちゃえよ。',c))
        self.assertNotIn('imperative_mood',violations('お疲れ、それはそれで面白いね。',c))

    def test_brief_social_reply_does_not_append_interview(self):
        hits=violations('何があったの？',build_contract(self.state(),'今日は疲れた。'))
        self.assertIn('unrequested_question',hits)

    def test_planning_request_is_not_satisfied_by_an_acknowledgement(self):
        contract=build_contract(self.state(),'週末の予定を一緒に考えたい。海へ行く。')
        self.assertIn('missing_concrete_plan_proposal',violations('うん。',contract))
        self.assertEqual(violations('人混みを避けて、朝の海へ行く案はよさそう。',contract),[])
        state=self.state()
        update_working_state(state,'土曜に海へ、予算は二人で6000円。')
        c=build_contract(state,'予定を考えたい。')
        self.assertIn('proposal_changed_confirmed_destination',violations('海以外の予定なら公園を候補にするよ。',c))
        self.assertIn('proposal_changed_confirmed_destination',violations('海に行くより美術館を候補にするよ。',c))

    def test_persistent_and_temporary_question_constraints(self):
        state=new_working_state()
        update_working_state(state,'質問不要。')
        state=json.loads(json.dumps(state))
        self.assertTrue(build_contract(state,'次の話だね。')['no_questions'])
        update_working_state(state,'質問していいよ。')
        self.assertFalse(build_contract(state,'質問していいよ。')['no_questions'])
        other=new_working_state()
        update_working_state(other,'今回は質問不要。')
        self.assertFalse(build_contract(other,'次の話。')['no_questions'])

    def test_one_requested_question_temporarily_overrides_no_questions(self):
        state=self.state()
        update_working_state(state,'質問不要。')
        text='いまだけ私に質問を一つして。次の返事からは、また質問なしに戻して。'
        update_working_state(state,text)
        c=build_contract(state,text)
        self.assertFalse(c['no_questions'])
        self.assertEqual(violations('今日はどんな予定があるの',c),[])
        self.assertIn('requested_question_count',violations('了解だよ。',c))
        self.assertTrue(build_contract(state,'答えは読書。')['no_questions'])

    def test_temporary_advice_request_does_not_erase_persistent_preference(self):
        state=self.state()
        update_working_state(state,'今回だけアドバイスして。')
        self.assertFalse(build_contract(state,'今回だけアドバイスして。')['no_advice'])
        self.assertTrue(build_contract(state,'次の話だよ。')['no_advice'])

    def test_structured_sentence_does_not_duplicate_period(self):
        reply=decode_retry(json.dumps({'sentences':['紙が落ちた.','猫が会議を止めた。']},ensure_ascii=False),{})
        self.assertEqual(reply,'紙が落ちた。猫が会議を止めた。')
        reply=decode_retry(json.dumps({'sentences':['紙が落ちた;。','猫が会議を止めた;']},ensure_ascii=False),{})
        self.assertEqual(reply,'紙が落ちた。猫が会議を止めた。')

    def test_one_sentence_is_checked_after_grounding(self):
        c=build_contract(self.state(),'今は解決策も質問もいらない。ひとことだけ。')
        self.assertIn('sentence_count',violations('寂しかったね。聞いてるよ。',c))
        self.assertEqual(violations('平気な顔の裏で、けっこう寂しかったんだね。',c),[])

    def test_code_and_translations_are_not_style_rewritten(self):
        c=build_contract(self.state(),'このコードをそのまま出して')
        self.assertNotIn('register_drift',violations('```python\nprint("です。")\n```',c))

    def test_creative_action_must_be_included(self):
        c=build_contract(self.state(),'『ぺちゃんこのパン』と『会議を止める猫』を入れて二文だけの小話を作って。')
        self.assertIn('missing_required_action:会議を止める猫',violations('ぺちゃんこのパンが落ちた。猫は逃げた。',c))
        self.assertIn('missing_required_action:会議を止める猫',violations('会議を止める猫に会った。ぺちゃんこのパンを渡した。',c))
        self.assertEqual(violations('会議を止める猫が机に飛び乗り、会議は中断した。ぺちゃんこのパンだけが議事録の上に残った。',c),[])
        self.assertEqual(violations('ぺちゃんこのパンが机に落ちた。黒い猫が飛び乗って会議を止めた。',c),[])

    def test_repetition_is_detected_without_rejecting_short_laughter(self):
        self.assertTrue(repetition('abcdefghijklmnop'*30))
        self.assertFalse(repetition('ははは、パンまでくたくただね。'))

    def test_unrequested_foreign_asides_are_not_a_japanese_reply(self):
        c=build_contract(self.state(),'猫がキーボードを占領した。ひとこと。')
        self.assertIn('unrequested_foreign_phrase',violations('Keyboard制覇だねlaughs。',c))
        self.assertEqual(violations('会議より先にキーボードの席を取られたね。',c),[])
        self.assertIn('unrequested_chinese_fragment',violations('猫も业务回避上手いな。',c))
        self.assertIn('unrequested_chinese_fragment',violations('運がいいって思え呗。',c))

    def test_register_drift_does_not_read_quoted_speech_as_persona(self):
        c=build_contract(self.state(),'今日はどんな感じ？')
        self.assertIn('register_drift',violations('落ち着いています。',c))
        self.assertNotIn('register_drift',violations('「お疲れ様です」と書いてあったよ。',c))
        self.assertIn('register_drift',violations('そう思いますよ。',c))

    def test_bad_final_reply_is_regenerated_and_rechecked(self):
        state=self.state()
        bad={'message':{'content':'休んだほうがいいよ。何があったの？'},'done_reason':'stop'}
        good={'message':{'content':json.dumps({'sentences':['パンまで一日分の疲れが出てるね。']},ensure_ascii=False)},'done_reason':'stop'}
        with patch.object(tail,'call_ollama',side_effect=[bad,good]) as model,patch.object(tail,'log_turn'):
            reply,complete=tail.generate_reply([],'袋の底でパンがつぶれてた。',working_state=state)
        self.assertTrue(complete)
        self.assertEqual(reply,'パンまで一日分の疲れが出てるね。')
        self.assertEqual(model.call_count,2)

    def test_whole_unrequested_addon_is_removed_without_harming_main_response(self):
        c=build_contract(self.state(),'駅で一段だけ踏み外した。')
        reply,removed=remove_unrequested_sentences('何もなかった顔だけは上手くなるね。次からは気をつけておけよ。',c)
        self.assertEqual(reply,'何もなかった顔だけは上手くなるね。')
        self.assertEqual(len(removed),1)
        mixed='何もなかった顔でも、次から気をつけよう。'
        self.assertEqual(remove_unrequested_sentences(mixed,c),(mixed,[]))

    def test_substantive_number_is_never_deleted_as_social_cleanup(self):
        c=build_contract(self.state(),'予算を短く教えて。')
        draft='残金1200円だよ。あと1000円用意したほうがいいよ。'
        self.assertEqual(remove_unrequested_sentences(draft,c),(draft,[]))

    def test_future_social_invitation_is_not_emotional_reflection(self):
        c=build_contract(self.state(),'寂しかった。ひとことだけ。')
        self.assertIn('unrequested_advice_or_reassurance',violations('寂しい気持ちは分かるよ、次回機会があればまた話そうね。',c))
        self.assertNotIn('unrequested_advice_or_reassurance',violations('また寂しい気持ちになったんだね。',c))
        self.assertIn('malformed_japanese',violations('寂しいって感じるのは自然さよ。',c))

    def test_exhausted_retries_do_not_claim_completion(self):
        state=self.state()
        bad={'message':{'content':json.dumps({'sentences':['休んだほうがいいよ。']},ensure_ascii=False)},'done_reason':'stop'}
        with patch.object(tail,'call_ollama',return_value=bad),patch.object(tail,'log_turn'):
            _,complete=tail.generate_reply([],'ひとことだけ返して。',working_state=state)
        self.assertFalse(complete)

    def test_exhausted_advice_drafts_recover_explicit_feeling(self):
        state=self.state()
        bad={'message':{'content':json.dumps({'sentences':['休んだほうがいいよ。']},ensure_ascii=False)},'done_reason':'stop'}
        with patch.object(tail,'call_ollama',return_value=bad),patch.object(tail,'log_turn'):
            reply,complete=tail.generate_reply([],'友達に断られて寂しかった。質問も助言も不要、一言だけ。',working_state=state)
        self.assertTrue(complete)
        self.assertEqual(reply,'寂しかったんだね。')

    def test_reflection_does_not_invent_speaker_or_emotion(self):
        from breaktail_reply_contract import grounded_reflection
        c=build_contract(self.state(),'ひとことだけ。')
        for text in ('友達が寂しかった。','寂しかったわけではない。','もし寂しかったら。','「寂しかった」と友達は言った。','寂しかった理由は？'):
            self.assertIsNone(grounded_reflection(text,c),text)

    def test_style_acknowledgement_recovers_without_advising_user(self):
        from breaktail_reply_contract import grounded_reflection
        c=build_contract(self.state(),'次からそんな感じで。')
        self.assertEqual(grounded_reflection('次からそんな感じで。',c)['reply'],'分かった、その口調で返すね。')
        self.assertIsNone(grounded_reflection('次から海へ行く。',c))

    def test_reflection_separates_feeling_from_preferred_reply(self):
        from breaktail_reply_contract import grounded_reflection
        c=build_contract(self.state(),'疲れてる。短く雑談してくれるほうが嬉しい。')
        c['no_questions']=False
        self.assertEqual(grounded_reflection('疲れてる。短く雑談してくれるほうが嬉しい。',c)['reply'],'疲れてるんだね。')
        self.assertIn('empty_social_reaction',violations('笑笑',c))
        self.assertIn('malformed_japanese',violations('意外と冷静なよね。',c))

    def test_explicit_single_question_can_recover_without_advice(self):
        from breaktail_reply_contract import grounded_reflection
        text='いまだけ私に質問を一つして。次の返事からは、また質問なしに戻して。'
        c=build_contract(self.state(),text)
        recovered=grounded_reflection(text,c)
        self.assertEqual(recovered['reply'],'今日はどんな一日だった？')
        self.assertEqual(violations(recovered['reply'],c),[])
        self.assertIsNone(grounded_reflection('猫について質問を一つして。',c))

    def test_recalled_event_cannot_move_to_an_unsupported_day(self):
        history=[{'role':'user','content':'今日は階段でつまずいた。'},
                 {'role':'user','content':'昨日の映画は楽しかった。'}]
        c=build_contract(self.state(),'さっきの階段の話に軽く返して。',history)
        self.assertEqual(c['event_time'],'今日')
        self.assertIn('unsupported_event_time_change',violations('昨日の階段が頭に残ってるね。',c))
        self.assertNotIn('unsupported_event_time_change',violations('最後の一段だけ強敵だったね。',c))

    def test_ambiguous_dates_and_creative_requests_do_not_force_one_time(self):
        c=build_contract(self.state(),'昨日の話を今日は整理したい。')
        self.assertIsNone(c['event_time'])
        self.assertIsNone(build_contract(self.state(),'今日と昨日の創作をして。')['event_time'])

    def test_requested_empathy_does_not_turn_into_teasing(self):
        bad={'message':{'content':'素振りはちゃっかり出してるね。'},'done_reason':'stop'}
        with patch.object(tail,'call_ollama',return_value=bad),patch.object(tail,'log_turn'):
            reply,complete=tail.generate_reply([],'友達に断られて、平気なふりしたけど寂しかった。解決策も質問もいらない。ひとことだけ。',working_state=self.state())
        self.assertTrue(complete)
        self.assertEqual(reply,'寂しかったんだね。')

    def test_opt_out_of_positive_wrapup_persists_and_removes_only_whole_wish(self):
        state=self.state()
        tail.update_working_state(state,'前向きなまとめはいらない。次からそんな感じで。')
        state=json.loads(json.dumps(state))
        c=build_contract(state,'袋の中でパンがつぶれた。')
        draft='パンまで残業した顔してるな。明日は楽な一日になりますように。'
        self.assertIn('unrequested_optimistic_wrapup',violations(draft,c))
        self.assertEqual(remove_unrequested_sentences(draft,c)[0],'パンまで残業した顔してるな。')
        self.assertNotIn('unrequested_optimistic_wrapup',violations('「明日は楽な一日になりますように」と書いてあった。',c))

    def test_requested_encouragement_overrides_wrapup_opt_out(self):
        state=self.state()
        tail.update_working_state(state,'前向きなまとめはいらない。')
        self.assertFalse(build_contract(state,'今回だけ励まして。')['no_optimistic_wrapup'])

    def test_self_deprecating_object_story_is_not_unstated_distress(self):
        c=build_contract(self.state(),'鞄のレシートがくしゃくしゃ。今週の俺みたいで笑った。')
        self.assertTrue(c['humorous_self_comparison'])
        self.assertIn('unsupported_distress_interpretation',violations('気分が落ち込んでるんだね。',c))
        self.assertNotIn('unsupported_distress_interpretation',violations('レシートまで一週間を乗り切った顔してるな。',c))

    def test_explicit_feeling_and_resignation_are_not_forced_into_jokes(self):
        c=build_contract(self.state(),'鞄のレシートが今週の俺みたいで笑った。でも寂しかった。')
        self.assertNotIn('unsupported_distress_interpretation',violations('寂しい気持ちだったんだね。',c))
        self.assertFalse(build_contract(self.state(),'レシートが今の俺みたいで笑うしかない。')['humorous_self_comparison'])

    def test_quoted_feelings_and_denials_do_not_authorize_a_diagnosis(self):
        for denial in ('落ち込んでない','落ち込んではいない','落ち込んでるわけじゃない'):
            c=build_contract(self.state(),'レシートが今週の俺みたいで笑った。「落ち込んでる」と言われたけど'+denial+'。')
            self.assertIn('unsupported_distress_interpretation',violations('気分が落ち込んでるんだね。',c))

    def test_wrong_mental_state_draft_is_rewritten_as_the_actual_topic(self):
        bad={'message':{'content':'気分が落ち込んでる時に当たっちゃうよね。'},'done_reason':'stop'}
        good={'message':{'content':json.dumps({'sentences':['レシートまで一週間を乗り切った顔してるな。']},ensure_ascii=False)},'done_reason':'stop'}
        with patch.object(tail,'call_ollama',side_effect=[bad,good]),patch.object(tail,'log_turn'):
            reply,complete=tail.generate_reply([],'鞄のレシートがくしゃくしゃ。今週の俺みたいで笑った。',working_state=self.state())
        self.assertTrue(complete)
        self.assertEqual(reply,'レシートまで一週間を乗り切った顔してるな。')

    def test_style_preferences_only_do_not_invent_weather(self):
        bad={'message':{'content':'今日も天気いいね、外に出たくなるね。'},'done_reason':'stop'}
        with patch.object(tail,'call_ollama',return_value=bad),patch.object(tail,'log_turn'):
            reply,complete=tail.generate_reply([],'短く雑談して。敬語なし、質問不要、助言はいらない。',working_state=self.state())
        self.assertTrue(complete)
        self.assertEqual(reply,'分かった、短く話すね。')

    def test_style_acknowledgement_does_not_replace_an_actual_story(self):
        self.assertFalse(build_contract(self.state(),'短く雑談して。今日はパンがつぶれてた。')['style_preferences_only'])
        self.assertFalse(build_contract(self.state(),'敬語なし。今日の天気について話して。')['style_preferences_only'])

    def test_unsolicited_only_option_remedy_is_a_complete_addon(self):
        c=build_contract(self.state(),'スマホの電池が3％。今の俺と同じで笑う。')
        draft='スマホも限界かよ、笑。でも充電するしかないよね。'
        self.assertIn('unrequested_advice_or_reassurance',violations(draft,c))
        self.assertEqual(remove_unrequested_sentences(draft,c)[0],'スマホも限界かよ、笑。')
        self.assertNotIn('unrequested_advice_or_reassurance',violations('残金は1200円しかない。',c))
