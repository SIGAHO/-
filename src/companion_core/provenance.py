"""Records evidence supplied to generation; does not claim semantic entailment of LLM prose."""
import re
from datetime import datetime, timezone
from .intent import IntentRouter, normalized
from .models import SourceType, Status


class ProvenanceResponder:
    def __init__(self):
        self.last = None

    def capture(self, context, *, generated):
        context = {**context, **context.get('prompt_context', {})}
        sources = []
        if context.get('memory'):
            sources.append({'kind': 'memory', 'items': context['memory'], 'verified': False})
        if context.get('state'):
            sources.append({'kind': 'state', 'items': context['state']})
        if context.get('runtime'):
            sources.append({'kind': 'runtime', 'items': context['runtime']})
        if context.get('knowledge', {}).get('evidence'):
            sources.append({'kind': 'external', 'items': context['knowledge']['evidence']})
        if context.get('external_evidence'):
            sources.append({'kind': 'web', 'items': [
                {k: v for k, v in item.items() if k != 'snippet'}
                for item in context['external_evidence']], 'verified': False})
        if generated:
            sources.append({'kind': 'assistant_generated', 'fact_evidence': False})
        return {'intent': context['intent'], 'sources': sources, 'generated': generated,
                'scope': 'supplied_context_not_claim_verification'}

    def answer(self):
        if self.last is None:
            return '直前回答の出所記録はない。AIの発言だけでは事実を確認できない。'
        labels = {'memory': '記憶（ユーザー申告を含む）', 'state': 'CPU管理の状態',
                  'runtime': '実行環境の観測', 'external': '信頼済み資料'}
        names = [labels[s['kind']] for s in self.last.get('sources', []) if s['kind'] in labels]
        message = '直前回答に渡した情報は、' + '・'.join(names) + '。' if names else '直前回答には確認済みの事実根拠はない。'
        web = [item for source in self.last.get('sources', []) if source['kind'] == 'web' for item in source['items']]
        if web:
            message = '直前回答に渡したWeb資料（未検証）は以下。\n' + '\n'.join(
                f"{item['title']} — {item['url']}（取得 {datetime.fromtimestamp(item['retrieved_at'], timezone.utc).isoformat(timespec='seconds')}、公開日 {item.get('published_at') or '不明'}、SHA256 {item['content_hash']}）"
                for item in web)
        if self.last.get('generated'):
            message += '文章はAI生成で、それ自体は事実の根拠にならない。渡した情報と文章の一致までは保証していない。'
        return message

    @staticmethod
    def generic_memory_query(text):
        return bool(re.fullmatch(r'(?:(?:Breaktail|自分|あなた)の)?(?:記憶に(?:入ってる|ある)|覚えてる)[?。\s]*', normalized(text), re.IGNORECASE))

    @staticmethod
    def memory_answer(memory):
        records = [m.text[:80] for m in memory.items if m.status == Status.ACTIVE
                   and m.source in {SourceType.USER_STATEMENT, SourceType.USER_CORRECTION}
                   and not re.search(r'[?？]', m.text)
                   and IntentRouter().route(m.text) not in {'self_state_memory', 'time_calculation', 'ambiguous_followup'}]
        records = records[-2:]
        if not records:
            return '保存済みのユーザー申告はまだ見つからない。AIの発言は記憶の事実根拠に入れていない。', records
        return '保存されたユーザー申告は「' + '」「'.join(records) + '」。発言としての記憶で、外部事実の確認済み根拠ではない。', records
