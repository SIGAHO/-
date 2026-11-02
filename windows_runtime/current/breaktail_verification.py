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


def verify_reply(text, reply, state):
    session = state.setdefault('conversation', {'facts':{}, 'preferences':{}, 'logic':None})
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
        return conclusion+'正しい文の数は'+ '、'.join(f'{b}なら{n}つ' for b,n in counts.items())+'。', {'kind':'box_enumeration','counts':counts,'answers':answers}
    equation = re.search(r'([0-9][0-9 +＋−－×÷*/().-]*[+＋−－×÷*/-][0-9 +＋−－×÷*/().-]*)\s*(?:は|＝|=)\s*([0-9]+)円', text)
    if equation and not re.search(r'何を間違え', text):
        try:
            value = arithmetic(equation.group(1))
            if value.denominator == 1:
                result = f'{equation.group(1).strip()}＝{int(value)}円。'
                if value != int(equation.group(2)):
                    result += f'{equation.group(2)}円ではなく、{int(value)}円だよ。'
                return result, {'kind':'arithmetic','expression':equation.group(1),'value':int(value)}
        except (ValueError, SyntaxError, ZeroDivisionError):
            pass
    facts = {key:item['value'] for key,item in session.get('facts',{}).items()}
    if re.search(r'残り|残金|予算.*収まる|不足|何を間違え', text) and all(k in facts for k in ('budget','transport','lunch_each','people')):
        budget,transport,lunch = facts['budget'],facts['transport'],facts['lunch_each']*facts['people']
        admission = facts.get('admission',0) if re.search(r'雨|水族館|何を間違え', text) else 0
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
            result = '検算すると'+formula+'で'+str(max(0,-remaining))+'円不足する（以前の誤りの原因まではこの検算だけでは断定できない）。'
        return result, {'kind':'budget','budget':budget,'transport':transport,'lunch':lunch,'admission':admission,'remaining':remaining}
    return reply, None
