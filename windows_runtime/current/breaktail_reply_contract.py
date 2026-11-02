"""Turn-level reply contracts, checked after grounding and postprocessing.

Checks are structural and evidence-based. They never trim a substantive answer
to meet a length limit or rewrite protected code/quoted text.
"""
import json
import re
from breaktail_code_regions import split_code_regions,map_prose


def sentences(text):
    result, start, stack = [], 0, []
    pairs = {'「':'」','『':'』','（':'）','(' : ')','“':'”'}
    for i,char in enumerate(text):
        if char in pairs:
            stack.append(pairs[char])
        elif stack and char == stack[-1]:
            stack.pop()
        if not stack and char in '。！？!?':
            piece = text[start:i+1].strip()
            if piece:
                result.append(piece)
            start = i+1
    if text[start:].strip():
        result.append(text[start:].strip())
    return result


def unquoted_prose(text):
    prose = '\n'.join(part for protected,part in split_code_regions(text) if not protected)
    return re.sub(r'「[^」]*」|『[^』]*』|“[^”]*”', '', prose)


def grounded_reflection(text,contract):
    """Last-resort reflection of an explicit feeling, never inferred advice.

    Also supports an acknowledgement or a bare request for one question.
    Other speakers, negation, hypothetical feelings and creative work decline.
    """
    if not contract['no_advice'] or contract['creative'] or contract['artifact']:
        return None
    if contract['required_questions']:
        bare_question=re.fullmatch(r'(?:いまだけ|今だけ|今回だけ)?(?:私に|僕に|俺に)?質問を?(?:一つ|1つ)(?:だけ)?して[。！!\s]*(?:次(?:の返事)?から.*質問なし.*)?',text.strip())
        if contract['required_questions']==1 and bare_question:
            return {'reply':'今日はどんな一日だった？','evidence':text,'kind':'requested_question'}
        return None
    if contract['exact_sentences'] not in (None,1):return None
    prose=unquoted_prose(text)
    if re.search(r'[？?]|なぜ|どうす|理由|もし|(?:友達|友人|姉|妹|兄|弟|彼|彼女)(?:は|が)',prose):return None
    if re.search(r'次から.{0,12}(?:感じ|口調|返し)|(?:口調|返し).{0,12}(?:好き|して|頼む)',prose):
        return {'reply':'分かった、その口調で返すね。','evidence':prose.strip(),'kind':'style_acknowledgement'}
    found=list(re.finditer(r'寂し(?:い|かった)|疲れ(?:た|てる|ている)|悲し(?:い|かった)|嬉し(?:い|かった)|つら(?:い|かった)|不安(?:だった|だ)',prose))
    found=[m for m in found if not re.search(r'(?:ほうが|方が|くれると)\s*$',prose[max(0,m.start()-12):m.start()])]
    if len(found)!=1:return None
    feeling=found[0]
    if re.match(r'(?:ら|なら|わけ|とは|ってこと|と思わ|とは思わ|かも|のか)',prose[feeling.end():]):return None
    evidence=feeling.group()
    reply='不安なんだね。' if evidence=='不安だ' else evidence+'んだね。'
    return {'reply':reply,'evidence':evidence,'kind':'explicit_feeling'}


def build_contract(state, text, history=None):
    prefs = state.get('conversation',{}).get('preferences',{})
    creative = bool(re.search(r'創作|小話|物語|短編|お話',text))
    artifact = bool(re.search(r'コード|プログラム|翻訳|引用して|原文|そのまま',text))
    foreign_requested=bool(re.search(r'(?:[一-龯ぁ-んァ-ヶA-Za-z]+語|英語|中国語)で.{0,8}(?:答え|話して|返して|書いて)',text))
    explicit_advice = bool(re.search(r'案を|案も|提案して|助言して|アドバイスして|解決策を|どうすれば|予定.*考え|プラン.*(?:考えて|作って)',text))
    explicit_questions = bool(re.search(r'(?:質問|聞き返し)(?:を)?(?:一つ|1つ|一個|1個)?(?:だけ)?して|質問していい|質問してよい',text))
    exact = re.search(r'([一二三四五六七八九十1-9])文(?:だけ|で|に)',text)
    n = (int(exact[1]) if exact[1].isdigit() else '一二三四五六七八九十'.index(exact[1])+1) if exact else None
    if re.search(r'ひとこと|一言|一文',text) and not exact:
        n=1
    short = prefs.get('brief',False) or bool(re.search(r'短く|ひとこと|一言|だけ答え|有無だけ|普通に少し話そう|どんな性格',text))
    required = []
    if creative and re.search(r'入れて|含め|使って',text):
        required = re.findall(r'[『「]([^』」]{1,60})[』」]',text)
    no_questions = (prefs.get('no_questions',False) or (short and not creative)
                    or bool(re.search(r'質問(?:は|も)?(?:不要|いらない|しないで|なし)',text))) and not explicit_questions
    active_mode=bool(state.get('mode',{}).get('active'))
    register=prefs.get('register',None if active_mode else 'casual')
    if re.search(r'敬語で(?:話|頼|お願い|返)',text):register='polite'
    elif re.search(r'敬語なし|敬語(?:を)?やめ|タメ口',text):register='casual'
    permitted_latin=set(re.findall(r'[A-Za-z][A-Za-z0-9.+_-]*',text))
    permitted_latin.update(('Breaktail','Ollama','Qwen','Qwen2.5','Qwen2.5:14b','Memory','Raw','Trace','JSON','CPU','GPU','RAM','API','PC','Web','Studio'))
    for item in state.get('conversation',{}).get('facts',{}).values():
        permitted_latin.update(re.findall(r'[A-Za-z][A-Za-z0-9.+_-]*',str(item.get('value',''))))
    actions=[]
    for phrase in required:
        action=re.fullmatch(r'(.+?)を(止める|中断する|中止する)([^を]{1,20})',phrase)
        if action:actions.append({'phrase':phrase,'object':action[1],'actor':action[3]})
    event_time=None
    if not creative and not artifact:
        sources=[text]
        if re.search(r'さっき|先ほど|前の話',text):
            anchors=set(re.findall(r'[一-龯]{2,}',text))-{'今日','昨日','明日','質問','返事','予定','確認','一言','一文','返答','敬語','名前'}
            sources.extend(m.get('content','') for m in (history or []) if m.get('role')=='user'
                           and any(a in m.get('content','') for a in anchors))
        times={t for source in sources for t in re.findall(r'今日|昨日|明日',unquoted_prose(source))}
        if len(times)==1:event_time=next(iter(times))
    return {'exact_sentences':n, 'max_sentences':n or (2 if short and not creative and not artifact else None),
            'max_chars':(100 if n==1 and not creative else 160 if short and not creative else None),
            'no_questions':no_questions, 'no_advice':(prefs.get('no_advice',False) and not explicit_advice and not creative and not artifact)
              or bool(re.search(r'解決策も質問もいらない|助言(?:は|も)?(?:不要|いらない)|アドバイス(?:は|も)?(?:不要|いらない)',text)),
            'register':register, 'required_phrases':required,
            'required_questions':1 if explicit_questions and re.search(r'一つ|1つ|一個|1個',text) else None,
            'creative':creative, 'artifact':artifact,
            'propose_plan':bool(re.search(r'予定.{0,25}考えたい|予定.{0,25}考えて|プラン.{0,12}(?:考えて|作って)',text)),
            'plan_destination':state.get('conversation',{}).get('facts',{}).get('destination',{}).get('value'),
            'companion_dislikes':state.get('conversation',{}).get('facts',{}).get('companion_dislikes',{}).get('value'),
            'required_actions':actions,
            'permitted_latin':sorted(permitted_latin),
            'foreign_requested':foreign_requested,
            'event_time':event_time,
            'source_han':text+''.join(str(item.get('value','')) for item in state.get('conversation',{}).get('facts',{}).values()),
            'first_person':prefs.get('first_person',None if active_mode else '私')}


def repetition(text):
    if len(text)<80:
        return False
    if re.search(r'(.{8,80}?)\1{3,}',text,re.S):
        return True
    pieces=sentences(text)
    return any(pieces.count(p)>=3 for p in pieces if len(p)>8)


def unexpected_han(text,allowed):
    # Shared Japanese/Chinese Han cannot be classified by Unicode block alone.
    # CP932 covers ordinary Japanese kanji; unfamiliar Han from user material
    # are explicitly allowed instead of being deleted or silently substituted.
    for char in text:
        if '\u3400'<=char<='\u9fff' and char not in allowed:
            try:char.encode('cp932')
            except UnicodeEncodeError:return True
    return False


def imperative_mood(text):
    for part in sentences(text):
        end=re.sub(r'[。！？!?\sｗw笑]+$','',part)
        end=re.sub(r'(?:よね|よ)$','',end)
        # Sentence-final ね after a predicate is conversational, while 死ね
        # and similar bare imperatives are not. Ambiguous bare endings cause
        # regeneration, never deletion of a possibly substantive sentence.
        if re.search(r'[だたるいうくすつぬむぶぐきしな]ね$',end):end=end[:-1]
        if re.search(r'(?:おつかれ|お疲れ|それ|これ|あれ|どれ|だけ|わけ|おかげ)$',end):continue
        if re.search(r'[えけげせてべめれろ]$|なさい$|(?:来い|こい)$',end):return True
    return False


def violations(reply, contract):
    hits=[]
    prose=unquoted_prose(reply)
    count=len(sentences(reply))
    if not reply.strip(): hits.append('empty_reply')
    if contract.get('event_time') and any(t!=contract['event_time'] for t in re.findall(r'今日|昨日|明日',prose)):
        hits.append('unsupported_event_time_change')
    if not contract['artifact'] and re.fullmatch(r'(?:笑|w|ｗ|[。！!、\s])+',prose):
        hits.append('empty_social_reaction')
    if contract['propose_plan'] and (len(prose.strip())<15 or not re.search(r'案|候補|提案',prose)):
        hits.append('missing_concrete_plan_proposal')
    if contract['propose_plan'] and contract['companion_dislikes'] and re.search(r'人混み|騒が|混雑',contract['companion_dislikes']):
        if not re.search(r'人混み|騒が|混雑|静か|空いて|人の少|空いた',reply):
            hits.append('proposal_ignored_companion_constraint')
    if contract['propose_plan'] and contract['plan_destination']:
        destination=contract['plan_destination']
        if destination not in reply or re.search(re.escape(destination)+r'(?:以外|ではなく|じゃなく|の代わり|はやめ|(?:に|へ)?(?:行く)?より)',reply):
            hits.append('proposal_changed_confirmed_destination')
    if re.search(r'てるある|ているある|だです|ですだ|ますだ|(?<=[一-龯])なよね|自然さ(?:よ|ね)[。！？!?\s]*$|[.;；]。|(?<=[一-龯ァ-ヶA-Za-z])(?:もも|がが|をを|にに|でで|とと)',prose):hits.append('malformed_japanese')
    elif not contract['artifact'] and not contract['foreign_requested'] and (prose.rstrip().endswith('.') or re.search(r'[ \t]{4,}',prose)):
        hits.append('malformed_japanese')
    if repetition(prose): hits.append('repetitive_generation')
    if not contract['artifact'] and not contract['foreign_requested']:
        foreign=[w for w in re.findall(r'(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9.+_-]{2,}(?![A-Za-z0-9])',prose) if w not in contract['permitted_latin']]
        if foreign:hits.append('unrequested_foreign_phrase')
        if re.search(r'业务|业|务|这|们|吗|让|给|还|为|过|从|对|发|觉|应|开|关|请|续|说|观|习|饭',prose):
            hits.append('unrequested_chinese_fragment')
        elif unexpected_han(prose,contract['source_han']):
            hits.append('unrequested_chinese_fragment')
    if contract['exact_sentences'] and count!=contract['exact_sentences']:
        hits.append('sentence_count')
    elif contract['max_sentences'] and count>contract['max_sentences']:
        hits.append('too_many_sentences')
    if contract['max_chars'] and len(reply)>contract['max_chars']:
        hits.append('too_long')
    ending=re.sub(r'(?:[\s。！!ｗw笑]|[（(]笑[）)])+$','',prose)
    implicit_question=bool(re.search(r'(?:かな|どう|かい|なの|だろうか)$',ending) or
                           (re.search(r'何|どんな|どこ|いつ|誰|どれ',ending) and re.search(r'(?:の|か)$',ending)))
    if contract['no_questions'] and (re.search(r'[？?]',prose) or implicit_question):
        hits.append('unrequested_question')
    if contract['required_questions']:
        question_count=sum(bool(re.search(r'[？?]',unquoted_prose(part)) or
            (re.search(r'何|どんな|どこ|いつ|誰|どれ',unquoted_prose(part)) and
             re.search(r'(?:の|か|かい|かな)[。！!\s]*$',unquoted_prose(part)))) for part in sentences(reply))
        if question_count!=contract['required_questions']:hits.append('requested_question_count')
    if contract['no_advice'] and re.search(
        r'休(?:もう|んで|めよ)|寝(?:よう|てね)|[たんだ]ほうがいい|明日に備え|時間が経つと楽|次は.{0,25}(?:しよう|気をつけ)|'
        r'次の機会に|(?:また|次回|今度).{0,25}(?:話そう|会おう|行こう|やろう|しよう)|(?:した|する|したら|すれば|してみる|持たせる)(?:方が|ほうが|と)?(?:いい|良い)|'
        r'気をつけ(?:て|よう)|(?:のも|のが|と|ば)(?:いい|良い|大切)|'
        r'(?:しなくて|しないで|なくても)いい|無理(?:は)?しな|大切に(?:して|しよう)|'
        r'(?:しちゃ|しては)(?:ダメ|だめ|いけない)|(?:休む|休息|寝る).{0,10}必要|(?:するべき|すべき)|'
        r'思え|考えろ|頑張れ|がんばれ|しなさい|したらどう|しようよ|してみて|してみよう|'
        r'(?:(?<!は)よう|ましょう)(?:ね|よ|か)?(?=[。！!\s]|$)|(?:て|で)(?:も)?いい(?:よ|ね|んだ|んだよ|んだね)?(?=[。！!\s]|$)|'
        r'(?:のが|のは|ことが|ことは).{0,8}(?:大事|大切)|(?:進む|休む).{0,15}(?:大事|大切)|'
        r'(?:聴いて|飲んで|散歩して|寝て)(?:ね|よ|みて)?[。！!]|'
        r'(?:明日|次は).{0,20}(?:大丈夫|良くなる|いいこと|元気)|元気出せ|'
        r'大丈夫(?:だよ|だと|、)|前向きに|時間が必要|元気(?:を)?出(?:して|せ)',prose):
        hits.append('unrequested_advice_or_reassurance')
    if contract['no_advice'] and imperative_mood(prose):hits.append('imperative_mood')
    if not contract['artifact'] and contract['register']=='casual' and re.search(r'(?:です|ます|ました|ません|でしょう)(?:よね|よ|ね)?(?:[。！？!?\s]|$)',prose):
        hits.append('register_drift')
    if not contract['artifact'] and not contract['creative'] and contract['register']=='casual' and re.search(r'(?:だわ|わね|ぜ)[。！？!?\s]|(?:だわ|わね|ぜ)$',prose):
        hits.append('mixed_character_voice')
    if contract['first_person'] and not contract['artifact'] and not contract['creative'] and re.search(r'(?:僕|俺|あたし|私)(?:は|が|自身|も|の性格)',prose):
        for pronoun in ('僕','俺','あたし','私'):
            if pronoun!=contract['first_person'] and re.search(re.escape(pronoun)+r'(?:は|が|自身|も|の性格)',prose):
                hits.append('first_person_drift');break
    for phrase in contract['required_phrases']:
        # An action can be conjugated in the story. Requiring the noun phrase
        # verbatim rejected the valid sentence 「猫が会議を止めた」.
        if phrase not in reply and not any(a['phrase']==phrase for a in contract['required_actions']):
            hits.append('missing_required_phrase:'+phrase)
    for action in contract['required_actions']:
        events=reply.replace(action['phrase'],'')
        objects=re.escape(action['object'])+('|議論' if action['object']=='会議' else '')
        if (action['actor'] not in reply or not re.search(r'(?:'+objects+r').{0,45}(?:止めた|止めて|止まった|止まり|中断|中止|終了)',events)):
            hits.append('missing_required_action:'+action['phrase'])
    if re.search(r'(?:それとも|ところで|そして|だから|けれど)[、,\s]*$',prose):
        hits.append('dangling_clause')
    return hits


def instruction(contract):
    rules=['[この返答の検証条件。過去のassistant発言を文体や正しさの見本にしない]']
    if contract['first_person'] and not contract['creative'] and not contract['artifact']:
        rules.append('一人称を使う場合は「'+contract['first_person']+'」。呼び名の指定に勝手な「さん」を付けない。')
    if contract['register']=='casual' and not contract['artifact']:
        rules.append('自然なタメ口。です・ます、わね・ぜを混ぜない。')
    if contract['exact_sentences']:
        rules.append(f'句点まで含む完全文をちょうど{contract["exact_sentences"]}文。前置き・あとがきなし。')
    elif contract['max_sentences']:
        rules.append(f'{contract["max_sentences"]}文以内。')
    if contract['max_chars']:
        rules.append(str(contract['max_chars'])+'文字以内。回答要素は落とさない。')
    if contract['no_questions']:rules.append('質問や問いかけを追加しない。')
    if contract.get('event_time'):rules.append('参照している出来事の時点は「'+contract['event_time']+'」。根拠なく別の日へ変えない。')
    if contract['required_questions']:rules.append('今回はユーザーから頼まれた質問を一つだけする。')
    if contract['no_advice']:rules.append('助言、買い方や休息の指示、気をつけよう、無理しないで、大丈夫という保証を足さない。行動の推奨や許可は0個。今の具体物・感情にだけ反応し、「～だったんだね」のように受け止める。')
    if contract['propose_plan']:
        rules.append('今回は予定を考える依頼なので、相槌だけで終わらず、条件に合う具体案を少なくとも一つ述べる。必ず「案」「候補」「提案」のいずれかを使い、未承認の案として示す。')
        if contract['plan_destination']:
            rules.append('確定している目的地は「'+contract['plan_destination']+'」。この目的地の案を出し、別の目的地へ勝手に変更しない。')
        if contract['companion_dislikes']:
            rules.append('同行者は「'+contract['companion_dislikes']+'」が苦手。この条件に具体的に配慮した案にする。')
    if contract['creative']:
        rules.append('今回指定された題材で独立した物語を書く。会話の予定や同行者を勝手に流用しない。登場するだけでなく指定された行動を実際に起こす。')
    if contract['required_phrases']:
        rules.append('必ず本文に次の題材を入れる（動作は活用してよい）: '+json.dumps(contract['required_phrases'],ensure_ascii=False))
    for action in contract['required_actions']:
        rules.append('「'+action['phrase']+'」は名称として登場するだけでは不合格。本文で実際に'+action['actor']+'が'+action['object']+'を止め、'+action['object']+'が中断したことまで描く。')
    return '\n'.join(rules)


def normalize_voice(reply,contract):
    """Meaning-preserving known inflections only; no clipping or code edits."""
    if contract['artifact'] or contract['creative']:
        return reply
    forms=(('分かりません','分からない'),('わかりません','わからない'),
           ('分かりました','分かった'),('わかりました','分かった'),
           ('ありません','ない'),('できません','できない'),('出来ません','出来ない'),
           ('しています','してる'),('思います','思う'),('あります','ある'),
           ('できます','できる'),('なります','なる'),('しました','した'),
           ('いました','いた'),('でしょう','だろう'),('でした','だった'),
           ('ですね','だね'),('ですよ','だよ'),('です','だよ'),
           ('思っちゃうわ','思っちゃう'),('ちゃうわ','ちゃう'),('思うわ','思う'),('だわ','だよ'),('わね','ね'),('ぜ','よ'))
    def prose_transform(prose):
        parts=re.split(r'(「[^」]*」|『[^』]*』|“[^”]*”)',prose)
        for i,part in enumerate(parts):
            if i%2:continue
            if contract['first_person']:
                part=re.sub(r'(?:僕|俺|あたし|私)(?=は|が|自身|も|の性格)',contract['first_person'],part)
            if contract['register']=='casual':
                for before,after in forms:
                    part=re.sub(re.escape(before)+r'(?=(?:よね|よ|ね)?(?:[。！？!?、\s]|$))',after,part)
            parts[i]=part
        return ''.join(parts)
    return map_prose(reply,prose_transform)


def remove_unrequested_sentences(reply,contract):
    """Remove only whole, unsolicited social add-ons after a real response.

    Never clip to a word/character limit, drop the only sentence, or apply this
    to requested code, translations, stories or a numeric/logic explanation.
    A one-sentence mixed answer must be regenerated instead of substring-cut.
    """
    if contract['artifact'] or contract['creative']:
        return reply,[]
    if any(protected for protected,_ in split_code_regions(reply)):
        return reply,[]
    parts=sentences(reply)
    if len(parts)<2:
        return reply,[]
    dropped=[];kept=[]
    for part in parts:
        hits=violations(part,contract)
        unwanted=[x for x in hits if x in ('unrequested_question','unrequested_advice_or_reassurance')]
        # A grounded computation is substantive even if the surrounding
        # sentence is awkward; it must not disappear during style cleanup.
        if unwanted and not re.search(r'\d|＝|箱[A-Z]',unquoted_prose(part)):
            dropped.append({'sentence':part,'reasons':unwanted})
        else:kept.append(part)
    if not kept or not dropped:
        return reply,[]
    return ''.join(kept),dropped


def retry_schema(contract):
    # Lists encode sentence boundaries. Code and translation use raw text so
    # line breaks, punctuation and the exact artifact are never reformatted.
    if contract['artifact']:
        return None
    n=contract['exact_sentences']
    properties={'sentences':{'type':'array','items':{'type':'string'},'minItems':n or 1}}
    if n or contract['max_sentences']:
        properties['sentences']['items']['pattern']=(r'^[^。！？!?]+[。！!]?$' if contract['no_questions'] else r'^[^。！？!?]+[。！？!?]?$')
    elif contract['no_questions']:
        properties['sentences']['items']['pattern']=r'^[^？?]*$'
    if n or contract['max_sentences']:
        properties['sentences']['maxItems']=n or contract['max_sentences']
    return {'type':'object','properties':properties,'required':['sentences'],'additionalProperties':False}


def decode_retry(content, schema):
    if schema is None:
        return content.strip()
    try:
        value=json.loads(content)
        parts=value['sentences']
        if not isinstance(parts,list) or not parts or not all(isinstance(x,str) for x in parts):
            return ''
        cleaned=[re.sub(r'[.;；]+。$','。',part.strip()) for part in parts]
        return ''.join(part if part.endswith(('。','！','？','!','?')) else part.rstrip('.;；')+'。' for part in cleaned).strip()
    except (ValueError,KeyError,TypeError):
        return ''
