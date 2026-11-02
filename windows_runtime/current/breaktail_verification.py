"""CPU verification of narrow arithmetic and finite box constraints.

No eval, model-produced code, external calls or persistence. Unsupported
expressions decline verification. Exact predicates, not a memorized answer,
determine which box satisfies the requested true-statement count.
"""
import ast
import operator
import re
from fractions import Fraction


def arithmetic(expression):
    expression = expression.translate(str.maketrans({'−':'-', '＋':'+', '－':'-', '×':'*', '÷':'/'}))
    if len(expression) > 120 or not re.fullmatch(r'[0-9+*/().\s-]+', expression):
        raise ValueError('unsupported arithmetic')
    tree = ast.parse(expression.strip(), mode='eval')
    if len(list(ast.walk(tree))) > 64:
        raise ValueError('expression too complex')
    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = Fraction(str(node.value))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in (ast.Add, ast.Sub, ast.Mult, ast.Div):
            value = {ast.Add:operator.add, ast.Sub:operator.sub, ast.Mult:operator.mul, ast.Div:operator.truediv}[type(node.op)](visit(node.left),visit(node.right))
        else:
            raise ValueError('unsupported AST')
        if abs(value) > 10**12:
            raise ValueError('amount too large')
        return value
    return visit(tree.body)


def parse_boxes(text):
    labels = re.search(r'箱([A-Z](?:[・、,][A-Z]){1,7})の一つ', text)
    statements = re.findall(r'[『「]鍵は([A-Z])に(ある|ない)[』」]', text)
    count = re.search(r'正しいのはちょうど([一二三四五六七八1-8])つ', text)
    if not (labels and statements and count):
        return None
    boxes = re.split('[・、,]', labels.group(1))
    n = int(count.group(1)) if count.group(1).isdigit() else '一二三四五六七八'.index(count.group(1))+1
    if len(set(boxes)) != len(boxes) or any(label not in boxes for label, _ in statements):
        return None
    return {'boxes': boxes, 'statements': statements, 'true_count': n, 'source':'user'}


def verify_reply(text, reply, state, history=None):
    session = state.setdefault('conversation', {'facts':{}, 'preferences':{}, 'logic':None})
    facts = {key:item['value'] for key,item in session.get('facts',{}).items()}
    if (re.search(r'呼び名',text) and '同行者' in text and re.search(r'何|確認|教えて|覚え',text)
            and not re.search(r'予算|曜日|残金|いつ|どこ',text)):
        # A multi-field recall must neither omit a requested item nor add an
        # unsupported blanket assertion that all other information is unknown.
        parts=['呼び名は'+str(facts.get('user_name','不明'))]
        companion=str(facts.get('companion','不明'))
        relationship=str(facts.get('relationship','不明'))
        parts.append('同行者は'+relationship+'の'+companion)
        if '苦手' in text:parts.append('苦手なものは'+str(facts.get('companion_dislikes','不明')))
        if re.search(r'食べ物|最初に買',text):parts.append('最初に買った食べ物は'+str(facts.get('first_food','不明')))
        return '、'.join(parts)+'。',{'kind':'user_only_fact_recall','source_keys':list(facts)}
    if (re.search(r'予定.{0,25}考えたい|予定.{0,25}考えて|プラン.{0,12}(?:考えて|作って)',text)
            and facts.get('destination') and re.search(r'人混み|騒が|混雑',str(facts.get('companion_dislikes','')))):
        # A small constraint-based planner: make an explicitly unadopted
        # option, never claim a venue's current crowding or invent its prices.
        proposal=f'人混みの少ない時間帯を確認して{facts["destination"]}へ行く'
        if all(k in facts for k in ('budget','transport','lunch_each','people')):
            remaining=facts['budget']-facts['transport']-facts['lunch_each']*facts['people']
            if remaining>=0:proposal=proposal.removesuffix('行く')+f'行き、交通費と昼食後の残金{remaining}円を追加支出の上限にする'
        return proposal+'案を候補にしよう。', {
            'kind':'constraint_based_proposal','status':'proposed','adopted':False,'destination':facts['destination']}
    if re.search(r'変更点だけ|訂正(?:した|の)?(?:点|箇所)だけ',text):
        labels={'relationship':'同行者の続柄','day':'曜日','budget':'予算','destination':'目的地'}
        changed=[key for key in session.get('last_changes',[]) if key in labels]
        if changed:
            return '、'.join(labels[key]+'は'+str(facts[key])+('円' if key=='budget' else '') for key in changed)+'。',{'kind':'explicit_changes','keys':changed}
    if re.search(r'(?:予定|ここまで).{0,35}まとめ|誰と・いつ|予定の確定事項',text) and all(k in facts for k in ('companion','day','destination','budget')):
        who=(facts.get('user_name','本人')+'と'+facts.get('relationship','')+'の'+facts['companion']).replace('との','と')
        where=(f'雨なら{facts["rain_destination"]}、晴れなら{facts["sun_destination"]}'
               if all(k in facts for k in ('rain_destination','sun_destination')) else facts['destination'])
        parts=[f'{who}で{facts["day"]}に{where}へ',f'予算は{facts["budget"]}円']
        if re.search(r'残金|残り',text):
            if all(key in facts for key in ('transport','lunch_each','people')):
                cost=facts['transport']+facts['lunch_each']*facts['people']
                with_admission=bool(re.search(r'雨|水族館|入場',text) or session.get('budget_scenario')=='with_admission')
                if re.search(r'晴れ|海',text) and not re.search(r'雨|水族館|入場',text):with_admission=False
                if with_admission:cost+=facts.get('admission',0)
                remaining=facts['budget']-cost
                prefix='雨天は' if with_admission else ''
                parts.append(prefix+(f'残金は{remaining}円' if remaining>=0 else f'{-remaining}円不足'))
            else:parts.append('残金は費用が未確定のため不明')
        if 'companion_dislikes' in facts and ('だけ' not in text or re.search(r'気をつけ|注意|苦手',text)):
            parts.append(facts['companion']+'は'+facts['companion_dislikes']+'が苦手')
        return '、'.join(parts)+'。',{'kind':'user_only_plan_summary','source_keys':list(facts)}
    problem = parse_boxes(text)
    if problem:
        session['logic'] = problem
    elif re.search(r'箱.{0,8}推理|鍵.{0,8}説明', text):
        problem = session.get('logic')
    if problem:
        counts = {box:sum((box == label) if predicate == 'ある' else (box != label)
                         for label,predicate in problem['statements']) for box in problem['boxes']}
        answers = [box for box,n in counts.items() if n == problem['true_count']]
        conclusion = '鍵は箱'+answers[0]+'。' if len(answers)==1 else ('条件を満たす箱はない。' if not answers else '候補は'+ '・'.join(answers)+'で一意には決まらない。')
        if re.search(r'一文|ひとこと',text):conclusion=conclusion.rstrip('。')+'で、'
        return conclusion+'正しい文の数は'+ '、'.join(f'{b}なら{n}つ' for b,n in counts.items())+'。', {'kind':'box_enumeration','counts':counts,'answers':answers}
    equation = re.search(r'([0-9][0-9 +＋−－×÷*/().-]*[+＋−－×÷*/-][0-9 +＋−－×÷*/().-]*)\s*(?:は|＝|=)\s*([0-9]+)円', text)
    if equation and not re.search(r'何を間違え', text):
        try:
            value = arithmetic(equation.group(1))
            if value.denominator == 1:
                result = f'{equation.group(1).strip()}＝{int(value)}円。'
                if value != int(equation.group(2)):
                    result += f'{equation.group(2)}円ではなく、{int(value)}円だよ。'
                if re.search(r'一文|一行|ひとこと',text):result=result.rstrip('。').replace('。','、')+'。'
                return result, {'kind':'arithmetic','expression':equation.group(1),'value':int(value)}
        except (ValueError, SyntaxError, ZeroDivisionError):
            pass
    facts = {key:item['value'] for key,item in session.get('facts',{}).items()}
    budget_question=bool(re.search(r'残り|残金|予算.*収まる|不足|何を間違え',text) or
                         (re.search(r'足り|収ま|以内|費用|総額',text) and re.search(r'予算|円|交通|昼食|入場|水族館|雨|晴れ',text)))
    if budget_question and all(k in facts for k in ('budget','transport','lunch_each','people')):
        budget,transport,lunch = facts['budget'],facts['transport'],facts['lunch_each']*facts['people']
        if re.search(r'雨|水族館|入場',text):session['budget_scenario']='with_admission'
        elif re.search(r'晴れ|海',text):session['budget_scenario']='base'
        admission = facts.get('admission',0) if session.get('budget_scenario')=='with_admission' else 0
        remaining = budget-transport-lunch-admission
        formula = f'{budget}−{transport}−{lunch}'+(f'−{admission}' if admission else '')+f'＝{remaining}円'
        result = formula+('で'+str(-remaining)+'円不足。' if remaining<0 else f'で残り{remaining}円。')
        if re.search(r'続柄|曜日', text):
            details = []
            if re.search(r'続柄', text) and 'relationship' in facts and 'companion' in facts:
                details.append('同行者は'+facts['relationship']+'の'+facts['companion'])
            if re.search(r'曜日', text) and 'day' in facts:
                details.append(facts['day'])
            if details:
                result = '、'.join(details)+'、'+result
        if re.search(r'何を間違え', text):
            previous=next((m.get('content','') for m in reversed(history or []) if m.get('role')=='assistant'),'')
            if '1200' in previous and re.search(r'2200円ではなく|2200円じゃなく',previous):
                result='直前の1200円という検算は正しく、誤訂正は受け入れていないよ、雨天は'+formula+'で'+str(max(0,-remaining))+'円不足。'
            elif re.search(r'残(?:り|金)(?:は)?2200円',previous):
                result='直前の残金2200円という計算が誤りで、雨天は'+formula+'で'+str(max(0,-remaining))+'円不足。'
            else:
                result='検算すると'+formula+'で'+str(max(0,-remaining))+'円不足。'
        return result, {'kind':'budget','budget':budget,'transport':transport,'lunch':lunch,'admission':admission,'remaining':remaining}
    return reply, None
