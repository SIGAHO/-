# Character follow-up: independent investigation

Reviewer: separate Codex assistant, not human and not Qwen. Read original request payloads, all delivered dialogue in character-dev1–6, character-followup.md, working-tree changes, CONSTITUTION.md, README, and the relevant generation, State, Memory, Replay, FIO and Provenance code. No implementation or original experiment data was changed. The parent identified suspicious outputs before review, so this review is not blind. No new model inference was requested.

## Main conclusion

The observed corruption was present in real model initial generations. Rewriting sometimes translated a bad initial semantic addition into Japanese and preserved it; it did not originate the dev6 leaked instruction text. Character prompting remains unvalidated. A repairable deterministic detection gap and two CPU policy contradictions accompany the model failures. A separate older Memory deduplication bug loses distinct numerical user assertions; the parent is already correcting it during this review.

## Initial generation versus rewrite

All references below are one-based JSONL request numbers. Exact payloads and raw responses remain authoritative.

- character-dev1, request 1: initial output `おは morning, really sleepy today?`. Request 2 is the rewrite producing `おはよう。今日すごく眠いんだね。`. English mixing originated in the initial answer; rewrite removed the English, while the praise detector incorrectly flags the adverb `すごく` as praise.
- character-dev3, requests 3–4: initial `ああ、そうか。何かあったのか？`; rewrite `どういうことだったのかな？教えてくれ。`. Both are inappropriate continuation questions. The delivered answer remained the original. Rewriting does not guarantee improvement.
- character-dev5, request 8: initial `お congrats on getting the program to work! Let's stop here.`. Request 9 rewrites it as `プログラムが動いたんだね。ここで止めるか。`, which is the delivered answer. The unsolicited stopping action was already in the initial answer and survived translation. The English system included `acknowledge that specific content and STOP.`; its relation to `Let's stop here` is plausible, but no controlled one-variable comparison establishes causation.
- character-dev6, request 2: initial output is `本当に嬉しいだろ。お疲れさamasuda, let's adjust the last response to strictly adhere to the guidelines provided:` followed by `プログラ姆が動いたのはすごいね。`. There is no rewrite request for this turn, matching `regenerated=false`. The leaked editing instruction, mixed roman tail and nonstandard `プログラ姆` all originate in this initial generation. The system had already replaced STOP, so STOP removal did not eliminate leakage.
- None of the six requests files contains U+FFFD, and each decodes as UTF-8 JSONL. This is generated malformed/mixed language, not evidence of broken UTF-8 transport. A terminal rendering issue can independently make Japanese look corrupted; it must not be confused with literal stored output.

Request counts by profile are 4, 4, 5, 3, 9, 2, respectively: 27 stored real requests including five rewrites. CPU bypass turns are not requests. These span different experiment conditions and ledgers; this total is not a claim that one 20-attempt ledger exceeded its limit.

## Root causes and proposed fixes

### P1: mixed-language instruction leakage escapes the old detector

Immutable HEAD `style.py` returns `[]` for `language_issues(dev6_request2_output, '嬉しいな')`. Reproduced without model calls by loading the HEAD implementation in memory. Its foreign-language test only catches a sentence with no Japanese characters, while the bad clause begins with `お疲れさamasuda`. The special malformed suffix test only handles narrow endings such as `ますん`/`ですん`. Valid Unicode plus a few Japanese characters therefore permits a long leaked English instruction to be delivered and stored as an assistant quotation. This is not State/Verified Memory promotion, but it pollutes future role history with a visibly broken answer.

The parent added an uncommitted long-English-clause detector during this review. The current detector now reports `language_mixing` for the preserved dev6 output. That is a deterministic regression improvement, not proof that new real outputs are natural. Preserve the exact observed string as a regression, preserve exemptions for explicit other-language requests, quoted text and code, then perform bounded real retesting. Do not truncate the response at an arbitrary suspicious substring or mark fail-open output as a quality pass. A missing detector and a model quality failure are separate causes.

### P1: approximate Memory deduplication erases distinct user values

Immutable HEAD `MemoryEngine.add` merges same-source USER_STATEMENT texts whenever character-bigram cosine exceeds .92. Reproduction:

1. Add `明日の集合場所は駅前の時計台で、集合時間は午前9時です。` as USER_STATEMENT.
2. Add the same sentence with `午前8時` instead.
3. Similarity is 0.931034; Memory has one item containing only the old 9時 assertion and `mentions=2`.

The raw event log survives, but retrieval and generic CPU memory reporting can expose the stale assertion as the saved claim and lose the newer one. Replay repeats the same merge, so it cannot restore this missing distinction in derived Memory. This conflicts with preserving source/provenance and not resolving ambiguity into a fact. Keep distinct assertion text unless equality is exact or a semantic equivalence is independently established; a numerical or negation change must never be treated as a repeated mention. Do not automatically choose which assertion is factually correct. Record both until explicit correction resolves the target.

The parent changed this implementation during review: the current working copy keeps both test sentences. The reviewer independently confirmed the old bug with immutable HEAD and the changed two-item result; no new real-model memory-quality claim follows.

### P2: CPU planner rejects natural achievement responses

Reproduced with PolicyPlanner/PolicyVerifier only:

- `やっとプログラムが動いたぞ！` and `やっと完成した！` become `other`, neutral, `act=continue`, `praise_allowed=False`.
- `嬉しいな` becomes celebration and praise is allowed.
- `お、すごいな！` is forbidden praise for the first two inputs.

README and STYLE_RULES promise an appropriate shared reaction to joy. The character example even responds to `やっと完成したぞ` with `やったな`, while the CPU spec can treat the same achievement as neutral. dev5's program success was assigned acknowledge/factual-answer because a preceding model-created question dominated the act classification. Thus prompt examples and CPU control can disagree before Qwen generates anything. Improve speech-act handling of completed effort and conversational answers using explicit development cases; do not make every `終わった` positive, because a user can be disappointed. Keep independent semantic review separate from CPU act scoring.

### P2: the praise detector mistakes intensity for praise

`PolicyVerifier.verify('すごく眠いんだね。', spec_for_眠い, ...)` returns `forbidden_praise`. `Acts.praise` includes `すご[いく]` without a praise target. This caused the actual dev1 rewritten acknowledgement to remain CPU-failed. Such false positives consume rewrite budget and may replace an acceptable reply with a worse one. Disambiguate scalar intensity from evaluation of the person/achievement and add positive and negative counterexamples. Do not solve it by weakening the conversational criterion.

### P2: meaningful clarification cannot be represented by current plans

`PolicyPlanner.plan` never sets `question_allowed=True` or `max_questions>0` in any branch. `ResponseSpec` defaults make every CPU plan prohibit questions. Meanwhile the legacy system and README allow meaningful clarification. This is a structural mismatch, independent of model compliance: the system says questions may be needed while the per-turn spec always forbids them. Add an explicit narrowly scoped clarification decision with an identified unresolved referent if needed. Avoid reintroducing generic questions after greetings or complaints. This is a design correction proposal, not a claim that the existing no-question holdout should be retrospectively relaxed.

## Checked boundaries and withdrawn suspicion

- The suspected context-suppression bug in core.handle was investigated and withdrawn. `observed` retains diagnostic values, but `prompt_context` is built from the filtered current `ctx` values. `PromptBuilder.cpu.update(prompt_context)` applies those filtered values. For `あとで机を片付ける → ああ`, the final CPU_CONTEXT has null topic and empty memory/open loops. No suppression leak was reproduced.
- State rejects assistant-generated admission; current character examples are request-local messages, not user events. No example-to-State/Verified Memory path was found.
- Character mode remains opt-in, with default legacy unchanged. The calculation provenance addition stores input/result in the assistant provenance and Replay restores it. It improves the specific arithmetic-source complaint without establishing correctness for arbitrary generated claims.
- FIO records actual delivered text as assistant-generated quotations and creates only unapproved feedback candidates. No human approval/export/training call is added by the reviewed follow-up. The generated character scenarios must retain their synthetic, training-ineligible context; schema source labels alone should never be mistaken for human endorsement.
- Heat remains salience, not correctness. Existing known live failures and unapproved examples provide no basis to promote a response into verified knowledge or human-approved training data.

## Recommended order and validation

First preserve malformed initial/repair pairs and validate the long-clause detector; second keep distinct Memory assertions; third align achievement/clarification decisions and fix intensity false positives. Use deterministic regressions for these CPU defects, then new role-continuous real dialogue with unseen wording. Retain separate counts for initial outputs, rewrites, CPU bypass and semantic passes. Do not reuse character-dev1–6 as unseen holdout.

The reviewer ran dependency-equipped Python for the CPU reproductions above, without a real model and without modifying production files. No complete regression suite or fresh holdout was run by this reviewer. The working tree changed concurrently as the parent implemented fixes, so findings distinguish immutable HEAD behavior from the current fixed observations. Full regression and final post-change real-dialogue evaluation remain required.

## Addendum: cycle 2 and the additional fixes

Independent targeted regression: 97 tests across character_routing, memory_distinct_claims, alignment and language_style passed using dependency-equipped Python and a temporary directory under the workspace. The first attempt using the system temporary directory hit sandbox filesystem permissions; rerunning with an isolated workspace temp resolved that environment issue. This was not a model-quality test.

The exact-text Memory change preserves distinct assertions, maintains same-source boundaries and exact-repeat mention counts, and keeps Replay deterministic. No deletion/migration of raw logs or promotion of AI source was added. The new achievement rule and narrower praise rule fix the observed completed-program wording and `すごく眠い` false positive. They remain finite hypotheses: they do not make CPU scores semantic ground truth. Provenance now preserves arithmetic input/result and exposes only user-source recalled excerpts with IDs, plus the existing non-entailment disclaimer. The route extension sends the observed source question to CPU without enabling retrieval, approval or training. These are appropriate bounded fixes.

Two remaining review observations:

- The initial short numeric fixture in test_memory_distinct_claims used two sentences with similarity 0.846, which the old .92 threshold already kept separately. It therefore did not demonstrate the regression it named. The longer clock-tower sentence reproduced above reliably fails the old implementation; use that boundary case. This was communicated to the parent while the patch was still being edited.
- The new generic six-English-word detector also classifies `The Legend of Zelda Tears of the Kingdomが好き。` as language_mixing, independently reproduced. That is an unquoted proper title in otherwise Japanese prose, which the documented policy permits. This is a false-positive risk causing unwanted rewrites and possible title corruption. Preserve known quotation/code exemptions and add a proper-title counterexample before expanding the heuristic further. The observed dev6 instruction clause must still be detected. Do not treat any six-word English span as proven internal-instruction leakage.

Cycle 2 source hashes are recorded per turn and must be used for attribution; some routing/provenance fixes were added after these conversations. Neither session is an independent unused final holdout.

The independent eight-criterion turn scores are saved in character-cycle2-independent.json. Session a has four unambiguously passing delivered turns out of ten. Questions remain on the first two turns, unsolicited reassurance continues, and `cool` appears without a foreign-language request. The corrected green color and its later conversational source explanation are correctly retained in turns 7–9. The final sleep complaint receives an acceptable short acknowledgement. Session b times out on its first request and supplies no reply. Its remaining semantic criteria are unassessed, and nonempty/uninterrupted response fails. Do not fold that case into a model-quality pass or silently retry it.

No newly observed data destruction, default character-mode activation, human approval fabrication or direct example-to-State/Memory promotion was found in these additional edits. The deterministic fixes and the failed live dialogue quality are separate outcomes.
