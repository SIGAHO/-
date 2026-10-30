"""CPU dialogue planning. Inferred acts are hypotheses, never facts or training labels.

Detectors describe speech acts rather than banning particular replies. Their finite
coverage is exposed in verifier evidence; they are not a semantic truth oracle.
"""
from dataclasses import asdict, dataclass
import re
import unicodedata

from .style import StyleValidator
from .session_memory import grams, EXPLICIT_RECALL


def norm(text):
    return unicodedata.normalize('NFKC', text).strip()


class Acts:
    question = re.compile(r'[?？]|(?:何|どう|どこ|いつ|誰|どれ|なぜ).{0,25}(?:か|の|たい)[。!！]*$|(?:かな|ますか|だろうか)[。!！]*$')
    advice = re.compile(r'(?:た|だ|し|寝|休|休ん|進め|やっ|備え|食べ|飲ん|行っ)(?:て|で)(?:ね|みて|みよう|ください|おこう)|(?:し|寝|備え|進め)よう|(?:休も|頑張ろ|やろ|取ろ)う|(?:した|する|寝た|休んだ)方が|べき|おすすめ|したらどう|するといい|しなよ')
    encourage = re.compile(r'頑張|がんば|応援|きっと.{0,12}(?:できる|大丈夫)|ファイト|負けるな|諦めないで')
    praise = re.compile(r'すごい|凄い|(?:すごく|凄く)(?:上手|優秀|立派)|素晴らし|立派|偉い|えらい|誇[りれ]|よくやった')
    reframe = re.compile(r'(?:でも|けど|むしろ|逆に).{0,35}(?:良い|いい|成長|経験|機会|価値|達成)|成長につなが|いい経験|達成感|順位より|結果より')
    rejection = re.compile(r'そういうことじゃない|そうじゃない|それは違う|違うって|やめて|いらない|望んでない|求めてない|押し付け|励まさないで|質問しないで|褒めないで|助言しないで|(?:褒め|励まさ|質問し|助言し)なくていい|(?:方法|手順|助言|アドバイス)(?:は|を|が)?(?:聞いてない|聞いていない|求めていない|求めてない|要らん|いらん|不要)')
    correction = re.compile(r'じゃなく|ではなく|訂正|違う[、,]|じゃない[。．、,]')
    approval = re.compile(r'^(?:その返し(?:が|で)いい|そういう返しがいい|今の返答(?:が|で)いい|今の返事(?:が|で)いい|その回答(?:が|で)いい)[。!！\s]*$')
    greeting = re.compile(r'^(?:よお|よう|やあ|おはよう|こんにちは|こんばんは|起きた|起きたよ|おーい|ただいま)[。!！\s]*$')
    negative = re.compile(r'嫌|いやだ|だる|面倒|めんど|潰れ|つぶれ|しんど|最悪|困った|つら|疲れ|商品なし|賞品なし')
    positive = re.compile(r'嬉し|うれし|やった|楽し|最高|成功|合格|優勝|(?:やっと|ついに).{0,30}(?:完成|できた|動いた)[^。\n]{0,5}[!！]')
    continuation = re.compile(r'^(?:ああ|うん|はい|そう|そうだよ|いや|いいえ|それ|は\?|\?+|参加する(?:の)?|.{1,16}として)[。!\s]*$')

    @classmethod
    def strategy(cls, text):
        t = norm(text)
        for name, detector in [('reframe', cls.reframe), ('encourage', cls.encourage),
                               ('advise', cls.advice), ('praise', cls.praise), ('ask', cls.question)]:
            if detector.search(t):
                return name
        if re.search(r'ｗ|笑', t):
            return 'joke'
        if re.search(r'つまり|理由|なので|とは', t):
            return 'explain'
        return 'acknowledge' if len(t) <= 100 else 'other'


@dataclass(frozen=True)
class ConversationState:
    user_dialogue_act: str
    reference_target: dict | None
    user_stance: str
    previous_assistant_strategy: str
    reaction_to_previous: str
    response_risk: str
    recent_raw_turns: list
    explicit_feedback: str | None = None

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class ResponseSpec:
    act: str = 'continue'
    advice_allowed: bool = False
    encouragement_allowed: bool = False
    praise_allowed: bool = False
    question_allowed: bool = False
    positive_reframe_allowed: bool = False
    acknowledge_misalignment: bool = False
    stance_match: bool = True
    max_questions: int = 0
    length: str = 'short'
    language: str = 'ja'
    target_reference: dict | None = None
    repetition: str = 'avoid_rejected_strategy'
    specificity: str = 'current_turn'
    relatedness: str = 'recent_context_first'

    def to_dict(self):
        return asdict(self)


class PolicyPlanner:
    def observe(self, text, events, intent='casual_chat'):
        # No Topic/Memory is consulted by short-term state extraction.
        raw = [{'turn_id': e.id, 'role': 'user' if e.kind == 'user_input' else 'assistant',
                'text': e.payload.get('text', '')}
               for e in events if e.kind in {'user_input', 'assistant_output'}]
        if raw and raw[-1]['role'] == 'user':
            raw = raw[:-1]
        recent = raw[-8:]
        previous = next((r for r in reversed(recent) if r['role'] == 'assistant'), None)
        t = norm(text)
        corrected = bool(Acts.correction.search(t))
        rejected = bool(Acts.rejection.search(t))
        approved = bool(Acts.approval.fullmatch(t))
        continuation = bool(Acts.continuation.fullmatch(t)) or intent in {'continuation', 'ambiguous_followup'}
        feedback = 'rejection' if rejected else 'correction' if corrected else 'approval' if approved else None
        reaction = ('rejected' if rejected else 'corrected' if corrected else 'accepted' if approved else
                    'neutral' if continuation else 'unknown') if previous else 'unknown'
        negative, positive = bool(Acts.negative.search(t)), bool(Acts.positive.search(t))
        stance = 'mixed' if negative and positive else 'negative' if negative or rejected else 'positive' if positive else 'neutral'
        if rejected:
            act = 'rejection'
        elif corrected:
            act = 'correction'
        elif approved:
            act = 'confirmation'
        elif Acts.greeting.fullmatch(t):
            act = 'greeting'
        elif continuation:
            act = 'continuation'
        elif Acts.negative.search(t) or re.search(r'眠い|眠たい', t):
            act = 'complaint'
        elif Acts.question.search(t) or intent == 'self_state_memory' and EXPLICIT_RECALL.search(t):
            act = 'question'
        elif positive:
            act = 'celebration'
        elif re.search(r'してほしい|作って|実装|手順|方法|どうすれば', t):
            act = 'task'
        elif previous and Acts.question.search(previous['text']):
            act = 'factual_answer'
        elif re.search(r'ｗ|笑', t):
            act = 'joke'
        else:
            act = 'other'
        reference = None
        if previous and (continuation or feedback or act == 'factual_answer'):
            reference = {**previous, 'context_turn_ids': [r['turn_id'] for r in recent[-6:]],
                         'resolution': 'recent_raw_hypothesis'}
        risk = 'high' if reaction in {'rejected', 'corrected'} else 'medium' if act in {'complaint', 'continuation', 'factual_answer'} or re.search(r'\d+位', t) else 'low'
        return ConversationState(act, reference, stance, Acts.strategy(previous['text']) if previous else 'other',
                                 reaction, risk, recent, feedback if previous else None)

    def plan(self, state, text, intent='casual_chat'):
        act = state.user_dialogue_act
        rejected = state.reaction_to_previous in {'rejected', 'corrected'}
        requested_advice = bool(re.search(r'どうすれば|どうしたら|助言(?:して|がほしい)|アドバイス|方法|手順|やり方(?:を|が)?(?:教えて|知りたい)', text)) and not Acts.rejection.search(text)
        response_act = ('apologize' if rejected else 'acknowledge' if act in {'greeting', 'complaint', 'factual_answer', 'confirmation'}
                        else 'celebrate' if act == 'celebration' else 'answer' if act == 'question'
                        else 'explain' if act == 'task' else 'joke' if act == 'joke' else 'continue')
        if requested_advice and not rejected:
            response_act = 'advise'
        return ResponseSpec(act=response_act, advice_allowed=requested_advice and not rejected,
                            praise_allowed=act == 'celebration' and not rejected,
                            acknowledge_misalignment=rejected,
                            length='medium' if act in {'question', 'task'} else 'short',
                            target_reference=state.reference_target)


class PolicyVerifier:
    def verify(self, reply, spec, state, user_text=''):
        prose = StyleValidator.protected.sub('', reply)
        issues = []
        detected = {name: bool(pattern.search(norm(prose))) for name, pattern in
                    [('ask', Acts.question), ('advise', Acts.advice), ('encourage', Acts.encourage),
                     ('praise', Acts.praise), ('reframe', Acts.reframe)]}
        for strategy, allowed in [('ask', spec.question_allowed), ('advise', spec.advice_allowed),
                                  ('encourage', spec.encouragement_allowed), ('praise', spec.praise_allowed),
                                  ('reframe', spec.positive_reframe_allowed)]:
            if detected[strategy] and not allowed:
                issues.append('forbidden_' + strategy)
        questions = max(len(re.findall(r'[?？]', prose)), int(detected['ask']))
        if questions > spec.max_questions and 'forbidden_ask' not in issues:
            issues.append('too_many_questions')
        if state.reaction_to_previous in {'rejected', 'corrected'} and detected.get(state.previous_assistant_strategy, False):
            issues.append('rejected_strategy_repeat')
        acknowledged = bool(re.search(r'ごめん|すまん|すまない|すみません|ずれ|ズレ|違った|取り違|受け取|そうじゃなかった|見当違い', prose))
        if (re.search(r'誤解した', prose) and not re.search(
                r'(?:あなた|君|お前|そっち)(?:が|は)誤解した|誤解したのは(?:あなた|君|お前|そっち)', prose)):
            acknowledged = True
        if spec.acknowledge_misalignment and not acknowledged:
            issues.append('missing_misalignment_acknowledgment')
        if state.user_stance == 'negative' and detected['reframe'] and spec.stance_match:
            issues.append('stance_mismatch')
        # Detect explicit referent loss. Absence of lexical overlap alone cannot
        # establish irrelevance for short natural acknowledgments.
        if spec.target_reference and re.search(r'何に|何の話|どの話|何について', prose):
            issues.append('reference_lost')
        issues.extend(StyleValidator().language_issues(reply, user_text))
        old_only = []
        if state.user_dialogue_act == 'greeting':
            # Greetings must not introduce a historical discussion unprompted.
            old_only = re.findall(r'前に話した|前回の|以前の|あの時の', prose)
            if old_only:
                issues.append('old_topic_resurrection')
        return {'issues': list(dict.fromkeys(issues)), 'adherent': not issues,
                'detected_acts': detected, 'questions': questions,
                'reference_checked': spec.target_reference is not None,
                'reference_overlap': bool(spec.target_reference and grams(prose) & grams(spec.target_reference['text'])),
                'semantic_coverage': 'bounded_cpu_heuristics_not_ground_truth'}
