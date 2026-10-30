"""Records evidence supplied to generation; does not claim semantic entailment of LLM prose."""
import re
from datetime import datetime, timezone
from .intent import IntentRouter, normalized
from .models import SourceType, Status
from .session_memory import EXPLICIT_RECALL


class ProvenanceResponder:
    def __init__(self):
        self.last = None

    def capture(self, context, *, generated):
        context = {**context, **context.get('prompt_context', {})}
        sources = []
        for kind in ('session_recall', 'salient_experiences'):
            if context.get(kind):
                sources.append({'kind': kind, 'items': context[kind], 'verified': False, 'fact_evidence': False})
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
        if self.last.get('fallback') == 'both_candidates_language_mixing':
            return '直前の文は、二つの生成候補に言語混在が検出されたため、システムが固定の失敗通知を返したもの。会話内容の事実根拠ではない。'
        if self.last.get('fallback') == 'original_language_and_candidate_empty':
            return '直前の文は、初稿の言語混在と書き直しの空文により、システムが固定の失敗通知を返したもの。会話内容の事実根拠ではない。'
        if self.last.get('fallback') == 'candidates_integrity_failure':
            return '直前の文は、生成候補に文章の破綻または内部指示の混入が検出され、システムが固定の失敗通知を返したもの。会話内容の事実根拠ではない。'
        if 'memory_recall' in self.last:
            records = self.last['memory_recall']
            if not records:
                return '直前の記憶照会では、条件に合う保存済みユーザー申告が見つからなかった。'
            return '直前の記憶照会は、保存済みのユーザー申告「' + '」「'.join(records) + '」を引用した。外部事実としての確認はしていない。'
        calculation = self.last.get('calculation')
        if calculation:
            return ('直前の回答は、あなたの入力「' + calculation['input'] +
                    '」をもとに、必要に応じて実行環境の時刻情報も使ってCPUで処理した結果「' +
                    calculation['result'] + '」。')
        labels = {'memory': '記憶（ユーザー申告を含む）', 'state': 'CPU管理の状態',
                  'runtime': '実行環境の観測', 'external': '信頼済み資料',
                  'session_recall': '過去の会話引用（未検証）', 'salient_experiences': '過去の経験記録（未検証）'}
        names = [labels[s['kind']] for s in self.last.get('sources', []) if s['kind'] in labels]
        message = '直前回答に渡した情報は、' + '・'.join(names) + '。' if names else '直前回答には確認済みの事実根拠はない。'
        exchanges = [item for source in self.last.get('sources', []) if source['kind'] == 'session_recall'
                     for hit in source.get('items', []) for item in hit.get('exchanges', [])
                     if item.get('user_source') == 'user_statement' and item.get('user') and item.get('user_complete') is True]
        if exchanges:
            excerpts = ['「' + x['user'] + '」（発言ID ' + str(x['turn_id']) + '）'
                        for x in exchanges[-2:] if x.get('turn_id')]
            if excerpts:
                message += '渡された過去のユーザー発言には' + '、'.join(excerpts) + 'がある。発言は未検証。'
        if any(item.get('user_complete') is not True for source in self.last.get('sources', [])
               if source['kind'] == 'session_recall' for hit in source.get('items', [])
               for item in hit.get('exchanges', []) if item.get('user_source') == 'user_statement'):
            message += '原文全体を確認できない発言は引用していない。'
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
        records = [m.text for m in memory.items if m.status == Status.ACTIVE
                   and m.source in {SourceType.USER_STATEMENT, SourceType.USER_CORRECTION}
                   and not re.search(r'[?？]', m.text)
                   and not EXPLICIT_RECALL.search(m.text)
                   and not IntentRouter.provenance.search(m.text)
                   and IntentRouter().route(m.text) not in {'time_calculation', 'ambiguous_followup'}]
        records = records[-2:]
        if not records:
            return '保存済みのユーザー申告はまだ見つからない。AIの発言は記憶の事実根拠に入れていない。', records
        return '保存されたユーザー申告は「' + '」「'.join(records) + '」。発言としての記憶で、外部事実の確認済み根拠ではない。', records
