"""Bounded session facts from explicit user wording, never assistant output.

This is session state, not long-term memory or training data. Unknown wording
is left to the model; supported facts retain their source and turn identity.
"""
import re


def update_session(state, text, turn=None):
    session = state.setdefault('conversation', {'facts': {}, 'preferences': {}, 'logic': None})
    facts = session.setdefault('facts', {})
    prefs = session.setdefault('preferences', {})
    temporary=bool(re.search(r'今(?:は|回だけ|だけ)|いまだけ|今回は|この返答',text))
    session['last_changes']=[]
    def put(key, value, position=None):
        if key not in {'budget','transport','lunch_each','admission','people'}:
            start=position if position is not None else max(0,text.find(str(value)))
            left=max(text.rfind(mark,0,start) for mark in '。、！？?\n')+1
            ends=[text.find(mark,start) for mark in '。、！？?\n' if text.find(mark,start)>=0]
            clause=text[left:(min(ends)+1 if ends else len(text))]
            if (re.search(r'[？?]|だったよね|だよね|だっけ|だったっけ|ですか|でしょうか',clause)
                    and not re.search(r'訂正|変更して|に変更|にする|にして',clause)):
                return  # A confirmation question is not a new assertion.
        if facts.get(key,{}).get('value')!=value:
            session['last_changes'].append(key)
        facts[key] = {'value': value, 'source': 'user', 'turn': turn, 'status': 'explicit'}
    patterns = {
        'user_name': r'(?:俺|私|僕)の呼び名は([^、。\s]{1,20})',
        'companion': r'同行者は(?:妹|姉|弟|兄|友達|友人|同僚)の([^、。\s]{1,20})',
        'relationship': r'同行者は(妹|姉|弟|兄|友達|友人|同僚)の',
        'day': r'(?:[月火水木金土日]曜)(?:日)?(?:じゃなく|ではなく)([月火水木金土日]曜)(?:日)?(?:に変更|にする|にした|(?=[。、\s]|$))',
        'budget': r'予算(?:は|の)?(?:二人で|2人で)?\s*([0-9,]+)円',
        'transport': r'(?:(?:二人|2人)往復の)?(?:電車代|電車|交通費)(?:が|は)?(?:二人往復で|二人で|2人で|往復で)?\s*([0-9,]+)円',
        'lunch_each': r'昼食(?:が|は)?一人\s*([0-9,]+)円',
        'admission': r'入場料(?:は|が)?(?:二人で|2人で)\s*([0-9,]+)円',
        'destination':r'目的地は([^、。！？?\s]{1,24})',
        'explicit_day':r'曜日は([月火水木金土日]曜)(?:日)?',
    }
    # A proposed value inside a confirmation question is not a correction.
    # Limit this check to wording immediately after the matched amount:
    # "昼食が一人1200円なら残りは？" remains a conditional calculation.
    def uncertain_amount(match):
        suffix = text[match.end():]
        return bool(re.match(
            r'\s*(?:[？?]|(?:だった|でした|だ|です)?(?:っけ|よね)[？?]?'
            r'|(?:だった)?かな[？?]?|ですか[？?]?|でしょうか[？?]?'
            r'|で(?:合ってる|正しい)[？?]?)',
            suffix,
        ))

    numeric_question = False
    for key, pattern in patterns.items():
        m = re.search(pattern, text)
        if m:
            if key in {'budget','transport','lunch_each','admission'} and uncertain_amount(m):
                numeric_question = True
                continue
            value = m.group(1)
            put('day' if key=='explicit_day' else key, int(value.replace(',', '')) if key in {'budget','transport','lunch_each','admission'} else value,m.start())
    if (re.search(r'二人|2人', text) and re.search(r'予算|電車|交通費|入場料', text)
            and not numeric_question):
        put('people', 2)
    meeting = re.search(r'集合(?:場所)?(?:は|が)([^、。！？?]{1,30}?)(?=に[0-9]{1,2}時|[、。]|$)',text)
    if meeting and not re.search(r'どこ|どちら|何',meeting[1]):
        location=re.split(r'じゃなく(?:て)?|ではなく',meeting[1])[-1]
        put('meeting_place',re.sub(r'に変更$','',location))
    changed_time=re.search(r'[0-9]{1,2}時(?:[0-9]{1,2}分)?じゃなく(?:て)?([0-9]{1,2}時(?:[0-9]{1,2}分)?)',text)
    initial_time=re.search(r'集合[^。！？?]{0,35}?に([0-9]{1,2}時(?:[0-9]{1,2}分)?)',text)
    if changed_time or initial_time:
        put('meeting_time',(changed_time or initial_time)[1])
    if re.search(r'(?:まだ)?(?:昼食の)?お?店(?:は|を)(?:まだ)?(?:決めてない|決めていない|未決定)',text):
        put('meal_venue_status','未決定')
    initial_day = re.search(r'([月火水木金土日]曜)(?:日)?に海へ', text)
    if initial_day:
        put('day', initial_day.group(1))
        put('destination', '海')
    companion = facts.get('companion', {}).get('value')
    if companion:
        correction = re.search(re.escape(companion)+r'は(?:妹|姉|弟|兄|友達|友人|同僚)じゃなく(?:て)?(妹|姉|弟|兄|友達|友人|同僚)', text)
        if correction:
            put('relationship', correction.group(1))
        aversion = re.search(re.escape(companion)+r'は([^、。\s]{1,20})が苦手', text)
        if aversion:
            put('companion_dislikes', aversion.group(1))
    food = re.search(r'(パン|おにぎり|弁当|カレー|サンドイッチ|りんご|バナナ)(?:を)?買った', text)
    if food and 'first_food' not in facts:
        put('first_food', food.group(1))
    if re.search(r'雨なら([^、。\s]{1,16})、晴れなら([^、。\s]{1,16})', text):
        m = re.search(r'雨なら([^、。\s]{1,16})、晴れなら([^、。\s]{1,16})', text)
        put('rain_destination', m.group(1)); put('sun_destination', m.group(2))
    # Only explicit preferences persist. Current-task form constraints are
    # supplied separately below, so “two sentences” does not become permanent.
    if not temporary and re.search(r'敬語なし|敬語(?:を)?やめ|タメ口', text):
        prefs['register'] = 'casual'
    elif not temporary and re.search(r'敬語で(?:話|頼|お願い)', text):
        prefs['register'] = 'polite'
    if not temporary and re.search(r'アドバイスより|助言(?:は|も)?(?:不要|いらない)|休めとか.+いらない', text):
        prefs['no_advice'] = True
    if not temporary and re.search(r'前向き.{0,8}(?:まとめ|締め).{0,8}(?:いらない|不要|なし)',text):
        prefs['no_optimistic_wrapup']=True
    if not temporary and re.search(r'励まして|前向きにまとめて',text):
        prefs['no_optimistic_wrapup']=False
    if re.search(r'短く雑談|次からそんな感じ', text):
        prefs['brief'] = True
    example=re.search(r'[「『]([^」』]{1,80})[」』].{0,12}(?:軽い返し|返しが好き|感じ)',text)
    if example:
        prefs['tone_example']=example[1]
    if re.search(r'(?:今後|これから|次から).*(?:質問不要|質問はいらない)', text):
        prefs['no_questions'] = True
    if not re.search(r'今は|今回は|この返答|今回だけ',text):
        if re.search(r'質問(?:は|も)?(?:不要|いらない|しないで|なし)',text):
            prefs['no_questions'] = True
        if re.search(r'短く(?:話して|返して|お願い)|今後.*短く|これから.*短く',text):
            prefs['brief'] = True
    if not temporary and re.search(r'質問していい|質問してよい',text):
        prefs['no_questions'] = False
    if re.search(r'一人称(?:は|を)[「『]?(私|俺|僕|あたし)',text):
        prefs['first_person'] = re.search(r'一人称(?:は|を)[「『]?(私|俺|僕|あたし)',text)[1]
    if not temporary and re.search(r'助言して|アドバイスして|解決策を', text):
        prefs['no_advice'] = False
    return session


def session_context(state, text):
    session = state.get('conversation', {})
    facts = session.get('facts', {})
    lines = ['[会話状態: ユーザーの明示発言だけ。assistantの提案は合意ではない。',
             '予定の要約にはユーザーが決めた事実だけを使う。提案は明示的な承認まで未確定。',
             '呼び名は本人、同行者は別人。参照できない情報は不明とし、会話になかったと断定しない。]']
    labels = {'user_name':'本人の呼び名','companion':'同行者','relationship':'同行者の続柄',
              'day':'曜日','budget':'予算','transport':'二人分の交通費','lunch_each':'一人分の昼食費',
              'admission':'雨天の二人分入場料','people':'人数','destination':'目的地',
              'first_food':'以前買った食べ物（予定の食事ではない）','companion_dislikes':'同行者が苦手なもの',
              'rain_destination':'雨天の目的地','sun_destination':'晴天の目的地'}
    labels.update(meeting_place='集合場所',meeting_time='集合時刻',meal_venue_status='昼食の店の決定状態')
    for key, item in facts.items():
        lines.append(f'{labels.get(key,key)}={item["value"]}')
    prefs = session.get('preferences', {})
    rules = []
    if prefs.get('register') == 'casual':
        rules.append('敬語なし。自然な口調を保ち、です・ます・わね・ぜを混ぜない。')
    elif prefs.get('register') == 'polite':
        rules.append('敬語で返す。')
    if prefs.get('brief'):
        rules.append('短い雑談は一〜二文。計算・複数質問・創作は今回の指定を優先。')
    if prefs.get('tone_example'):
        rules.append('ユーザーが好きな軽い返しの例（毎回コピーせず、今の題材に接続する）: '+prefs['tone_example'])
    if prefs.get('no_advice') or re.search(r'解決策も質問もいらない|助言不要', text):
        rules.append('求められない助言、休息の指示、前向きなまとめ、根拠のない将来の保証を足さない。')
    if prefs.get('no_questions') or re.search(r'質問もいらない|質問不要|質問はいらない', text):
        rules.append('質問を追加しない。')
    if re.search(r'ひとこと|一言|一文', text):
        rules.append('今回は一文だけ。')
    if rules:
        lines.append('[継続する会話上の希望]\n'+'\n'.join(rules))
    return '\n'.join(lines) if facts or rules else ''


def constraint_violations(state, text, reply):
    prefs = state.get('conversation', {}).get('preferences', {})
    hits = []
    # Requested planning/advice overrides a general no-advice preference.
    advice_requested = bool(re.search(r'予定.*考え|提案して|助言して|アドバイスして|解決策を', text))
    if (prefs.get('no_advice') and not advice_requested) or re.search(r'解決策も質問もいらない|助言不要', text):
        if re.search(r'休(?:もう|んで|めよ)|明日に備え|明日は.{0,12}(?:いい|良い)|時間が経つと楽|早めに.{0,8}(?:寝|休)', reply):
            hits.append('助言・根拠のない励まし不要')
    if prefs.get('no_questions') or re.search(r'質問もいらない|質問不要|質問はいらない', text):
        if re.search(r'[？?]', reply):
            hits.append('質問不要')
    if re.search(r'ひとこと|一言|一文', text) and len(re.findall(r'[。！？!?](?:\s|$|[^」』])',reply)) > 1:
        hits.append('一文だけ')
    if prefs.get('brief') and not re.search(r'創作|小話|計算|推理|説明|教えて|まとめ|考え',text) and len(reply)>140:
        hits.append('短く')
    return hits
