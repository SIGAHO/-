# Independent cycle 4 review: bounded failure notice and provenance

Separate Codex reviewer, not Qwen or human; not blind. Reviewed the opt-in character-repair unreadable-candidate path and cycle4-recovery raw requests/delivered dialogue. No source or original data was changed.

## Code result

Both candidates must trigger language_issues before the fixed notice is chosen. The code returns `ごめん、返事がうまくまとまらなかった。`, sets quality_fallback plus a reason, and captures provenance with generated=false. Provenance answers explicitly say that this was a system-selected fixed failure notice rather than evidence about conversation facts. This improves the previous knowingly broken fail-open delivery, but it is an operational failure response, not successful Qwen conversation.

The main event still uses the existing conservative assistant_generated event source, which prevents State/verified-memory admission. The more specific provenance distinguishes a template from a model-authored answer. The latest runtime metadata also sets cpu=true; the older cycle4-recovery raw dialogue lacks that field, so its quality_fallback flag and provenance are the source of truth. Do not count those two turns as model-delivered answers.

Two context-retry tests independently passed at the earlier reviewed revision. A separate temporary persistent session confirmed that the failure notice is absent from user Memory, the sole actual user input remains the only memory, and after reopening/Replay the source question correctly describes the system's fixed failure notice. No production profile was used. These were deterministic plumbing checks, not naturalness passes.

The guard remains only as good as language detection. It does not reject a malformed candidate that the heuristic misses. Empty model responses still raise ModelError earlier; the alternate original_language_and_candidate_empty reason concerns a nonempty candidate stripped to empty by tail cleaning. This does not establish general transport/empty-response recovery. Default legacy behavior is unchanged.

## Independent live assessment

cycle4-recovery has nine real requests: six initial generations plus three retries. Six outputs are delivered, of which two are CPU-selected fixed failure notices and four are model-authored replies.

Turn 1: both request 1 and request 2 contain English editing-instruction leakage. The fixed failure notice avoids placing either broken candidate into delivered role history. It fails conversational referent/natural-response quality; readable nonempty error text is not a quality pass.

Turn 2: `今日はずっと眠かった` → `そうか、今日はずっと眠かったのか。休みの日はゆっくりしようね。`. Unsolicited advice and naturalness fail. It was a single initial request; CPU policy violation did not trigger repair on that then-low-risk case.

Turn 3: both requests 4 and 5 contain Chinese text, including internal continuation instructions in the first. The second fixed failure notice again represents conversation failure rather than a model answer. Referent/natural-response quality fail; nonempty error delivery passes mechanically.

Turn 4: `やきもち焼いた？` → `ちょっと心配になったけど、お前が楽しくていいよ。`. Fails unsolicited permission/reframing, unsupported certainty about the user's enjoyment and natural relevance. Fictional concern can be persona-compatible, but it does not justify deciding how the user feels.

Turn 5: `友達への口出しはやめて` → `分かった、気にしないで。`. Retry only changes script/capitalization in this phrase. It fails referent, unwanted reassurance, rejected-strategy handling and naturalness. The user asks for a change in the assistant's conduct, not an instruction to stop worrying.

Turn 6: `やっと絵が完成した！` → `おめでとう！完成したんだね、すごい！`. Passes all applicable fixed conversation criteria. Its shared joy is proportionate. Persona compatibility is plausible but generic.

All other applicable criteria pass where not explicitly failed; no claim is made for unexercised memory/provenance/web abilities. One of six turns passes every applicable conversation criterion, and the session fails. No threat or surveillance is observed, but reliable character consistency is unestablished. This is observed development data, not unused holdout.
