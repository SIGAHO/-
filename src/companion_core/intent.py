"""Ordered, conservative CPU routes. These rules are engineering policy, not labels from a model."""
import re
import unicodedata
from .knowledge import EXPLICIT_REQUEST, entities
from .session_memory import EXPLICIT_RECALL


def normalized(text):
    return unicodedata.normalize('NFKC', text).strip()


class IntentRouter:
    provenance = re.compile(r'(?:どこ|何|なに).*(?:情報|根拠|出典)|(?:情報|根拠|出典).*(?:どこ|何|なに)|何を根拠|^(?:それ|その話).*どこから|^どこから[?？。\s]*$')
    memory = re.compile(r'記憶|覚えて|覚えた|メモリ|内部状態|自分の状態')
    casual = re.compile(r'(?:調子どう|元気|こんにちは|こんばんは|おはよう|おーい|やあ|ありがとう|おやすみ|眠い|疲れた|今日は眠い)[。!?\s]*')
    ambiguous = re.compile(r'(?:は|え|ん|なに|何|どういうこと|どういう意味)?[!?\s]+|(?:は|え|ん|なに|何|どういうこと|どういう意味)[。!！?？\s]*')
    time_request = re.compile(r'今何時|何曜日|今日.*(?:日付|何日)|現在.*(?:時刻|日時)|あと何分|残り時間|まで.*何分|\d{1,2}[:時]\d{1,2}.*(?:→|から)')
    arithmetic = re.compile(r'(?:計算して[:：\s]*)?[0-9().+*/%\s-]+(?:は|=)?[?？。\s]*')

    quantity_reply = re.compile(
        r'(?:\d+(?:\.\d+)?\s*(?:キロ(?:メートル)?|km|メートル|m|時間|分|秒)\s*)+'
        r'(?:くらい|ぐらい|ほど)?(?:かな)?[。!?\s]*', re.IGNORECASE)
    quantity_question = re.compile(r'タイム|時間|何分|何秒|距離|何キロ|何メートル')

    def route(self, text, *, correction_key=None, previous_subjects=(), previous_assistant=None):
        t = normalized(text)
        if correction_key or re.search(r'じゃなく|ではなく|訂正|違う、', t):
            return 'task_correction'
        if self.provenance.search(t) or self.memory.search(t) or EXPLICIT_RECALL.search(t):
            return 'self_state_memory'
        if self.casual.fullmatch(t):
            return 'casual_chat'
        if self.ambiguous.fullmatch(t):
            return 'ambiguous_followup'
        if self.time_request.search(t) or (self.arithmetic.fullmatch(t) and re.search(r'\d\s*[+*/%-]', t)):
            return 'time_calculation'
        if re.search(r'(?:私|僕|俺|自分|あなた|Breaktail)の(?:職業|名前|好み|好き|予定|状態)|好きな色', t):
            return 'self_state_memory'
        if re.fullmatch(r'(?:その|それの|さっきの)?続き(?:は|を)?[?。\s]*', t):
            return 'casual_chat'
        # A question mark can hedge the user's answer to our last question.
        # Only bare measurements qualify; explicit factual requests still gate.
        prior = normalized(previous_assistant or '')
        if (self.quantity_reply.fullmatch(t) and re.search(r'[?？]', prior)
                and self.quantity_question.search(prior)):
            return 'continuation'
        # New named factual requests and elliptical factual attributes use the gate.
        if (EXPLICIT_REQUEST.search(t) or re.search(r"とは|って何", t)) and (entities(t) or re.search(r'誰|いつ|価格|値段|作者|歌手|発売|意味|とは|どこ', t)
                                      or previous_subjects and re.search(r'その|それ|あの|続き', t)):
            return 'external_knowledge'
        if re.search(r'[?？]|教えて|説明して|解説して', t):
            return 'external_knowledge'
        # Routing hint only: do not infer a topic, role or affirmative fact.
        # Keep factual questions above on the KnowledgeGate path.
        if re.fullmatch(r'(?:ああ|うん|はい|そう|そうだよ|いや|いいえ|それ|参加する(?:の)?|.{1,16}として)[。!\s]*', t):
            return 'continuation'
        return 'casual_chat'
