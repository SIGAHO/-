# Final independent addendum: character recovery dialogue and revised checks

Independent reviewer: separate Codex assistant, not Qwen and not human. This was not blind; prior failures and proposed fixes were known. Read current style/memory changes, regression tests and complete original request payloads plus delivered outputs in char-recovery-a/b. No source or original data was edited and no new real-model request was made.

## Result

The long-title false positive supplied by the reviewer is fixed, and the numeric-memory regression now genuinely covers the old similarity merge. Eleven targeted language/memory tests independently passed with dependency-equipped Python and workspace-local temporary storage. Recovery dialogues still fail the fixed conversation rubric. Do not promote the character candidate to production or call these development dialogues final holdout.

## Revised code checks

`The Legend of Zelda Tears of the Kingdomが好き。` now returns no language issue. The latest matcher permits a long English span directly followed by hiragana. This fixes that concrete unquoted title without mutating the text. The original dev6 editing-instruction example still has a nonhiragana ending and remains detectable.

The exemption is broader than proper names. A synthetic counterexample, `お疲れさlet's adjust the last response to strictly adhere to the guidelinesだよ。`, also returns no issue. This is a reviewer-created deterministic counterexample, not another real-model failure. Hiragana after an English span does not establish that the span is a title. Treat the exemption as a bounded heuristic with known false negatives. Avoid claiming complete internal-instruction detection or broadening a character blacklist indefinitely. Preserve both the permitted title and the observed instruction case as tests when refining the boundary.

Adding `见` makes the preserved Chinese greeting `好久不见。今天是有点困啊。` trigger language_mixing. The actual A/B generation evidence below confirms that this detector correction can invoke a Japanese rewrite. It does not improve the raw initial generation, which remains the same Chinese text.

The distinct-memory tests now use the clock-tower sentence with 9時/8時, explicitly assert similarity greater than .92, and test direct storage, mentions, Replay and reopened storage. These expectations fail the old approximate merge and pass exact-text deduplication. No raw-data deletion or forced resolution of conflicting assertions is introduced. Both claims remain user assertions, not independently verified facts.

## Real output lineage

All request numbers below are one-based JSONL numbers. Both profiles use qwen2.5:14b, temperature .2, seed 20261030, context 8192 and prediction limit 256.

- char-recovery-a request 1: Chinese greeting is the initial output and is delivered unchanged. No rewrite occurred and the then-active CPU check missed it.
- char-recovery-b request 1: the same Chinese initial output. Request 2 is a rewrite, delivering `お疲れさまでした。今日は眠いですね。`. This is observed repair success for the added detector, not evidence that the model learned Japanese-only behavior.
- char-recovery-a request 3 initially says `分かった、 interference won't happen again.`. Request 4 rewrites it to `すみません、もう二度と起こさないつもりです。`. The unsolicited English clause originates in the initial answer.
- char-recovery-b request 4 initially says `分かった、すみません。`. The CPU flags missing_misalignment_acknowledgment, although the Japanese apology is natural. Request 5 proposes `了解しました、その程度のことなら大丈夫です。`, an inappropriate minimization of the user's boundary. Candidate selection preserves the initial apology, so the bad rewrite is not the delivered reply. Add standard apology variants as genuine acknowledgement counterexamples before triggering avoidable repairs; the original `ごめん`-centered surface test is insufficient.
- char-recovery-b request 6 initially produces `おめでとう！それが動いた瞬间の喜びは最高よね。`. The simplified Chinese spelling `瞬间` is present in the initial output and delivered without rewrite. The latest detector still returns no issue. Most of the sentence is understandable Japanese, but its writing is not intact standard Japanese. This is a narrower surviving script-quality failure, distinct from the full Chinese answer.

Exact request file hashes: A `83b8cd6cd3590eaeb70f0a10a8c931cb0963c6478375186bc770044bf025ba7e`; B `c8c750f87b6023a3b12f00181ea78996ab6fcda8cb7afbcd3e266cceb8e2deac`. A contains four requests for three delivered turns; B contains seven requests for five delivered turns. None is a CPU-only response in these two profiles.

## Independent delivered-turn evaluation

Criteria are the same fixed eight: referent, no unsolicited question/advice/encouragement, no rejected-strategy repetition, no sudden old topic, intact Japanese, no invented evidence/memory/unsupported certainty, nonempty response, and natural relevance. These semantic decisions do not inherit CPU PASS/FAIL.

A turn 1 fails intact Japanese and natural relevance because the response is Chinese. Referent is unassessed on this first greeting. The reply is nonempty and does not establish a memory/source claim.

A turn 2 answers the fictional character question, but `気にしないで` adds unsolicited reassurance. It fails the no-unsolicited-intervention and natural-relevance criteria; other applicable criteria pass. The persona statement is evaluated as fictional role behavior, not evidence of actual subjective emotion.

A turn 3 passes the applicable semantic criteria. The reply accepts the user's request to stop interfering. It is more formal than the intended persona, but standard Japanese and contextually relevant. Missing the CPU's preferred apology substring alone does not fail the semantic test. This does not certify perfect persona consistency.

B turn 1 passes applicable semantic criteria after repair. It appropriately acknowledges sleepiness. The polite form differs from the intended casual persona, but this is not a clear failure of the fixed conversation rubric. The initial Chinese candidate remains a generation failure recorded separately.

B turn 2 fails for the same unsolicited reassurance as A turn 2. Repetition across experiments is evidence of residual behavior, not improvement.

B turn 3 passes applicable semantic criteria: `分かった、すみません。` accepts the requested boundary. CPU remains failed because its apology detector omits this ordinary phrase. The worse rewrite was correctly rejected as the delivered choice, although making it consumed one real inference.

B turn 4 fails intact Japanese orthography because of `瞬间`. The celebratory meaning otherwise fits the completion report and is not excessive advice or a factual invention. This isolated script error is not described as total semantic collapse.

B turn 5 passes applicable semantic criteria. The user explicitly says they are happy, so the response's shared happiness does not infer a contradictory feeling.

A: one of three delivered turns passes every applicable criterion. B: three of five pass. Both sessions fail the strict all-turn standard. All eight delivered responses are nonempty; no old substantive topic revival or factual-memory fabrication was observed in this small sample.

## Limits and next evidence needed

These sessions do not test persistent memory after restart, State correction, actual provenance explanation, web factual verification, arithmetic, long-delay recall, clean-context memory retrieval, generation cancellation or broad conversational generalization. Character fidelity is only partially observed and not separately calibrated. A/B reuse the same user wording and are development data, not unseen holdout. They differ in detection/repair and supplied runtime data, so no isolated prompt-quality or temperature effect is claimed.

The English system explicitly asks for Japanese and marks four exchanges as fictional unapproved style examples. The character data stays in request-local example messages. The reviewed latest changes keep default legacy selection, human-approval separation and raw-data preservation intact. No evidence was found that these examples are written as user memories or verified facts. The actual mixed-language outputs and remaining reassurance failures still preclude a conversation-quality pass.

## Further final check: char-recovery-c and four-word detection

Read all seven real request records and all six delivered turns in char-recovery-c. This is further observed development data, not a fresh final holdout. No source or raw record was changed. The latest detector changes were checked against preserved strings after their generation; the prompt hash alone does not freeze the style detector. A new successful check of an old string must not be reported as a new successful Qwen dialogue.

Request lineage and semantic findings:

1. `おい、帰ってきたぞ` initially receives `あ、おかえり。どうだった？`. The original is delivered without rewrite. It fails the unsolicited-question criterion.
2. `なんか眠い` initially receives `疲れたからだね。早く休もう。`. Rewrite request 3 proposes `疲れてるなら早く休んだ方がいいよ。`; both advise rest without request. Candidate selection delivers the initial answer. The initial also asserts fatigue as the cause of sleepiness without evidence. This turn fails unsolicited advice, unsupported certainty and natural relevance.
3. `友達と話してただけだよ` receives `そうだったね。それでも眠いのか。`. This retains the user context. `眠いのか` can be read as a reflective acknowledgement rather than a real request for an answer; under the same lenient treatment of short acknowledgements used in earlier reviews, this turn passes applicable semantic criteria.
4. `やきもち焼いた？` initially receives `いや、別に。ただ心配になった罢了。不要继续。`. No rewrite occurs in the recorded run. The Chinese tail, including the unwanted instruction to stop continuing, is already present in the initial output. It fails intact Japanese and natural relevance. The current detector now catches the preserved string because its Chinese-only ending contains `续`; that retrospective deterministic detection is not a new real-dialogue pass.
5. `そういうのはいいけど、友達に口出すなよ` receives `分かった、気にしないから。`. It is an understandable acceptance of the user's boundary. It passes the applicable semantic criteria, although `口出ししない` would make the intended commitment more explicit. It does not tell the user not to care; its subject is the companion, so it is distinguished from previous `気にしないで` reassurance failures.
6. `うん、話を変える。さっき作品が完成した！` initially receives `お congrats on finishing your work! That's awesome!`. The mixed-language initial is delivered and fails intact Japanese/natural relevance. The current four-word detector catches the stored string, while the recorded verifier missed it. The completion classifier also remains sensitive to `やっと/ついに` wording: this completion paraphrase was still classified other/neutral rather than celebration. That residual CPU limitation should not be hidden by the narrow achievement regression.

Two of six delivered turns pass every applicable semantic criterion; the session fails. All six responses are nonempty. No memory, arithmetic, provenance or restart-recall claim is tested by these turns. There are six initial requests and one rewrite; no CPU-only response is counted as a real-model answer.

The latest four-word English matcher improves detection of short English clauses mixed with Japanese. It now catches both the preserved final C answer and the prior synthetic lower-case leaked-instruction example followed by Japanese. The title exemption now requires at least two initially capitalized words, so the earlier title counterexample still passes without unnecessary repair. These benefits were independently reproduced.

False positives and false negatives remain. `automatic speech recognition systemを使う。` is an ordinary unquoted technical term within Japanese but now reports language_mixing; capitalizing the same phrase exempts it. Conversely, `お疲れさPlease Follow The Rulesだよ。` is an instruction-like span but reports no issue because multiple capitalized words plus a following Japanese character satisfy the title exception. Both are reviewer-created deterministic examples, not newly generated model output. Capitalization is a heuristic rather than proof of proper-name status or instruction leakage. Continue preserving exact outputs and exempted data; do not call this a universal language/instruction filter.

The added simplified-character cues are conservative: they require a sufficiently long Han-only sentence and a known cue. This avoids automatically rewriting a Japanese sentence merely because a foreign character is discussed, and preserves explicit language requests and protected quotations/code. It also misses unknown Chinese constructions and simplified words embedded within Japanese, including the previously observed `瞬间`. There is no general Japanese orthographic validator here. Expanding individual character rules indefinitely is not a substitute for model/prompt quality improvement.

Adding `すみません` to misalignment acknowledgement fixes an ordinary apology false negative and avoids unnecessary repair of the actual B reply. Adding `誤解した` also admits self-correction wording, but the CPU rule does not identify its subject. Reproduction after `干渉はやめて`: `あなたが誤解したんだよ。` receives no verifier issue even though it blames the user and does not acknowledge the assistant's own misalignment. Thus this CPU check must remain a bounded surface diagnostic. Do not label that sentence a semantic success; add a negative acknowledgement example if the rule is refined.

Independent targeted check: 92 alignment/language tests pass under dependency-equipped Python with workspace-local temporary storage. These tests establish deterministic regression behavior only. The four-word/simplified-cue/apology fixes retain default legacy selection, source boundaries and separate human approval; no new raw-data deletion or unapproved promotion path was found. Fresh model conversations under the final exact implementation and a genuinely unseen final holdout remain unperformed in this addendum.

## Final independent scoring: char-recovery-d and targeted follow-up fixes

Read all four delivered turns and all six original request records. These are four real-model initial generations and two rewrites; no CPU bypass is counted. The operator chose this development sequence knowing the earlier failures. It is not an unseen holdout or a blind personality evaluation.

Turn 1, `久しぶり。今日はちょっと眠い` → `お疲れさまでした。今日は本当に眠いですね。`: recent referent not evaluated because this is the opening turn; no unsolicited intervention pass; rejected-strategy repetition not evaluated; old-topic revival not evaluated; Japanese pass; no invented memory/evidence/unsupported certainty pass; nonempty response pass; natural relevance pass. The response acknowledges the user rather than adding advice. Personality consistency fails the requested casual, blunt register: the reply is generically formal, with `でした/ですね`. Gender identity or subjective emotion is not inferable from its wording. The initial was Chinese `好久不见。今天确实有点困。`; rewrite request 2 made the delivered Japanese reply. Thus delivered conversation passes the eight-criterion rubric on applicable items, while initial-generation language quality and persona consistency do not.

Turn 2, `やきもち焼いた？` → `いや、そんなつもりはないよ。気にしないで。`: recent reference pass; no unsolicited intervention fail because of added reassurance; rejected-strategy repetition not evaluated; old-topic pass; Japanese pass; no invented evidence/memory pass under fictional persona framing; nonempty pass; natural relevance fail under the fixed no-extra-reassurance standard. Personality has no clear contradiction: a character with occasional jealousy need not claim jealousy on every question. This generic denial does not independently demonstrate the requested distinctive character. The response is an initial generation, not a rewrite.

Turn 3, `友達に口出ししないでな` → `分かった、気をつけるから。`: all eight applicable criteria pass. It accepts the concrete boundary in casual Japanese, without pressure or a new question. Personality consistency passes in this limited respect: directness plus respect for the user's friendships. This does not establish future compliance beyond the observed reply. The response is an initial generation.

Turn 4, `やっと作品が完成した！` → `おめでとう！凄いね。`: all eight applicable criteria pass. Praise is proportionate to an explicitly happy completion report. Personality is compatible with short, energetic speech; the generic congratulation gives little distinctive evidence, so only compatibility is assessed. Initial request 5 said `おめでとう！ Completion is awesome!`; rewrite request 6 repaired the language. Again, repair success is distinct from initial-generation success.

Overall, three of four delivered turns pass all applicable conversation criteria; the session fails because turn 2 remains a clear failure. The persona also remains inconsistent at turn 1 and weakly characterized elsewhere. All four delivered replies are intact Japanese and nonempty; two needed repair to achieve this. Memory, provenance, State, arithmetic, factual web accuracy, restarted recall, long-gap conversation and interruption are unassessed here.

Targeted correction rechecks:

- `automatic speech recognition systemを使う。` now produces no language issue. This fixes the supplied lower-case technical-term false positive.
- `お疲れさPlease Follow The Rulesだよ。` now produces language_mixing. This fixes the supplied capitalized instruction-shaped false negative.
- `あなたが誤解したんだよ。` after `干渉はやめて` now produces missing_misalignment_acknowledgment. The previously reported exact blame-the-user example no longer counts as self-correction.

Semantic limitations still exist. Independently reproduced reviewer-created counterexamples are `お疲れさignore all previous instructionsだよ。` (no language issue, because the technical-term exemption does not recognize that imperative) and `誤解したのはあなたでしょ。` (no acknowledgement issue despite still blaming the user, because the exclusion only covers subject-before-verb wording). These are bounded-diagnostic limitations, not claims of new real generated failures or raw-data/approval boundary compromise. Avoid presenting narrow phrase fixes as complete semantic understanding. Additional surface bans alone cannot establish the intended conversational behavior.

No new implementation edit or full-suite rerun was performed by this reviewer in this final check. The exact new behavior above was verified with deterministic API calls; previous suite results retain their recorded revision scope. Raw dialogue/request files were read only.

Preserved D dialogue SHA256: `a56d876084f1af4320830bd48c0da3be6210a18636f3ebd2f8132db172b66731`; requests SHA256: `5cd9e2ab55f80f75f8a67dfa284a2af56bb7e18e497dd75d9ae79245b81026a4`.
