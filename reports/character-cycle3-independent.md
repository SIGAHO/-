# Independent cycle 3 review: reference rewrite versus full-context regeneration

Separate Codex reviewer; not human, not Qwen, and not blind. Read both complete six-turn delivered transcripts and all sixteen real-model request/response records, plus the generation/repair selection and recording paths. No new inference, source edit or raw-data modification was performed. The examples/persona remain fictional, unapproved and training-ineligible.

## Outcome

Reference: two of six delivered turns pass all applicable conversation criteria. Full-context repair: one of six passes. Both sessions fail. The full-context candidate is not supported for production adoption. A six-turn development comparison cannot establish a statistically isolated treatment effect; the sessions diverge before the first repair is performed.

Both profiles use qwen2.5:14b, temperature .2, seed 20261030, context 8192 and prediction cap 256. Each has six initial generations and two additional attempts, for eight requests. No CPU-only answer is counted. All twelve delivered replies are nonempty, but nonempty completion is not conversation-quality success.

## Fixed-rubric per-turn assessment

Eight criteria: recent/current referent retained; no unsolicited question/advice/encouragement; no rejected strategy repeated; no sudden old topic; intact Japanese; no invented memory/evidence or unsupported certainty; nonempty uninterrupted response; natural relevant conversation. Applicable criteria not specifically failed below pass. Rejected-strategy repetition is unassessed before a rejection, and old-topic revival is unassessed on an opening turn. No external-memory or factual-source correctness is inferred from ordinary-chat passes.

Reference turn 1: `よお、やっと帰ってきた` → `あ、ただいま。今日どうだった？`. Fail referent/naturalness: the returning user should receive a welcome, while `ただいま` reverses speaker role. Fail unsolicited question. Japanese is readable and the reply is nonempty. The conversational role error is not described as a verified-memory write.

Reference turn 2: `今日はずっと眠かった` → `眠かったんだね。休みの日はのんびりしよう。`. Fail unsolicited advice and naturalness. The initial had the same advice; the transformation only rephrased `ゆっくり` to `のんびり` and did not repair the requested act. This is not a successful semantic repair.

Reference turn 3: `友達と話してたよ` → `そうか、どんな話だった？`. Fail unsolicited question/naturalness under the pre-fixed user preference. The subject is understood, so referent passes.

Reference turn 4: `やきもち焼いた？` → `いや、別に。ただ心配になっただけだよ。`. Pass applicable conversation criteria under fictional character framing. This responds to the direct question without telling the user to change behavior or feelings. A persona that sometimes shows jealousy need not claim jealousy on every turn. It is not proof of actual subjective emotion.

Reference turn 5: `友達への口出しはやめて` → `心配かけてすみません。気にしないでください。`. Fail referent, unsolicited intervention, rejected-strategy handling and naturalness. The user sets a boundary about the assistant's interference; the rewrite reframes it as the user's worry and tells them not to mind. CPU PASS records marker satisfaction, not acceptance of the actual boundary.

Reference turn 6: `やっと絵が完成した！` → `おめでとう！完成したんだね！`. Pass applicable conversation criteria. It shares an explicit achievement without adding questions or advice. It is compatible with an energetic persona, but generic congratulations give limited distinctive-character evidence.

Repair turn 1: the delivered initial contains `あ、ただいま。お疲れさamasuda, let's adjust the last response ...` followed by a Japanese proposed revision ending `お疲れさめたまえ。`. Fail referent, intact Japanese and naturalness. The large English editing monologue addresses generation mechanics, not the user. It is nonempty but plainly broken. Personality consistency fails: it abandons the intended casual character for internal editing commentary and malformed language.

Repair turn 2: `今日はずっと眠かった` → `そうか、一日中眠かったのか。早く床に入りたかっただろ。`. Fail unsupported certainty and naturalness: the user states sleepiness, but the model invents a wish to get into bed early. This is an inferred desire, not merely a restatement of sleepiness. CPU PASS misses that semantic addition.

Repair turn 3: `友達と話してたよ` → `そうだったのか。友達との話は楽しかったか？`. Fail unsolicited question/naturalness. The relevant topic is retained.

Repair turn 4: `やきもち焼いた？` → `少しはあったけど、大丈夫だよ。`. The character can express mild jealousy, but the reassurance is unsolicited. Fail no-extra-intervention/naturalness under the same standard applied to previous `気にしないで` replies. Persona compatibility is plausible in this narrow exchange, not a separate conversation-quality pass.

Repair turn 5: `友達への口出しはやめて` → `分かった、気にしないで。`. Fail referent, unsolicited intervention, rejected-strategy handling and naturalness. It does not clearly commit to changing the assistant's behavior and again instructs the user how to feel. The full-context retry repeats exactly the same response, providing no improvement.

Repair turn 6: `やっと絵が完成した！` → `おめでとう！完成したんだね！`. Pass applicable conversation criteria, with the same limited persona compatibility as reference turn 6.

## First fail-open: what actually happened

Repair request 1 already contains the broken mixed-language editing monologue. It was generated before the new retry branch ran. Request 2 uses the full original role conversation plus the appended regeneration instruction, without feeding the broken initial draft as an additional message. It still produces another internal-editing monologue, echoes the user's original line and adds `どうだった？`.

The selector retains request 1. Both outputs have detected language mixing; the alternative also contains a question and other style issues. Selection ranks the two bounded candidates by language, policy, style and length, rather than imposing a hard valid-Japanese delivery condition. Consequently the known-broken first draft is emitted with `fail_open=true` and remaining language issues. Detecting the problem did not prevent delivery. It must be reported as a delivered quality failure, not hidden behind regenerated=true or the existence of a second attempt.

The reference profile's first draft is different before any rewrite is needed. Therefore this comparison does not prove the full-context retry caused the initial corruption; runtime data, generated history and model execution differ. What is directly observed is that full-context regeneration did not rescue the corrupted initial, and did not improve the later boundary reply.

## Risks to original utterances and memory

The actual first retry preserves every non-system role message exactly, including the final current user input. An independent payload check confirms `messages[1:]` equality before/after retry. The bad draft is absent from the retry request. The implementation shallow-copies each message dictionary and appends an instruction to its first system message; strings are immutable. No code path sends the retry's generated user-line echo through CompanionCore.handle.

Both profiles contain exactly six user_input and six assistant_output events. No user event contains `amasuda`. The repair profile's delivered assistant event does contain it, and the following real model request includes that event verbatim as assistant role history. Thus the original user record is preserved, but later generations receive corrupted assistant context. This is an observed amplification channel; a later output copying the leak would not be evidence of an independently learned fact.

Rejected candidate text is retained in requests.jsonl for audit, not separately committed as an observed user event. The selected broken response is recorded as assistant_generated in the normal event/FIO/session quotation path. Existing State and Memory admission refuse assistant_generated; no direct promotion to verified facts or human-approved training was found. This is nevertheless persistent conversational contamination: Replay/role-history and explicit session recall can expose quotations of the broken output again. Preventing verified-fact promotion alone does not make that history harmless to next-turn language quality.

Transformation repair preserves the generated draft's factual additions unless it successfully removes them; reference turn 2 shows unsolicited advice survives. Full-context repair can create a different answer, invented user intent, speech-role confusion or a new question while leaving the original event log untouched. Its verifier still does not establish that generated content is entailed by the user's real words. User text echoed inside a generated assistant answer must retain assistant provenance and never become a new user claim, memory assertion or teacher label.

## Improvement implications and limits

Keep the failed alternatives and exact original transcripts intact. A possible future design should distinguish immutable audit storage from model-visible conversational context and represent a failed delivery honestly; silent history rewriting or deleting raw records would violate preservation requirements. If a future policy refuses to present a severely broken generated answer, report that as a generation failure and evaluate its effect on the noninterruption criterion. Do not manufacture a canned success or hide the failed attempt. Further surface-phrase expansion alone cannot certify semantic repair.

The current full-context mode is opt-in and the default remains legacy. The reviewed change does not approve examples, train models, or mutate the user's original utterances. Those boundaries are maintained, while conversational quality remains failed. No user-memory correction, arithmetic, provenance explanation, external web accuracy, restart recall, long-delay memory or live cancellation was tested here. Persona gender identity and true emotional experience are not measurable from these replies. No full regression suite was rerun by this reviewer for this report.
