"""Bounded verification of user-stated ordering conditions, without model code."""
import itertools
import re


def parse_ordering(text):
    pattern=r'([一-龯ぁ-んァ-ヶA-Za-z0-9_]{1,20})(?:は|が)([一-龯ぁ-んァ-ヶA-Za-z0-9_]{1,20})より(左|右|前|後)'
    constraints=[]
    for a,b,direction in re.findall(pattern,text):
        constraints.append((a,b) if direction in ('左','前') else (b,a))
    entities=list(dict.fromkeys(x for pair in constraints for x in pair))
    if len(constraints)<2 or not 2<=len(entities)<=6:
        return None
    return {'entities':entities,'before':[list(pair) for pair in constraints], 'source':text}


def solve_ordering(problem):
    result=[]
    for order in itertools.permutations(problem['entities']):
        positions={name:i for i,name in enumerate(order)}
        if all(positions[a]<positions[b] for a,b in problem['before']):
            result.append(order)
    return result


def verify_ordering(text,session,history):
    problem=parse_ordering(text)
    if problem:
        session['ordering']=problem
    else:
        if re.search(r'条件を(?:変更|変え)|別の(?:問題|推理)|今度は',text):
            session.pop('ordering',None)
            return None
        previous=session.get('ordering')
        recent=[m.get('content','') for m in (history or [])[-8:] if m.get('role')=='user']
        if (previous and previous['source'] in recent
                and re.search(r'元の条件|条件を満たす|順番|順序|並べ|でもいい',text)):
            problem=previous
    if not problem:
        return None
    orders=solve_ordering(problem)
    if len(orders)==1:
        reply='、'.join(orders[0])+'の順だよ。'
        if re.search(r'確かめ|理由|元の条件',text):
            reply+='元の条件では'+ '、'.join(a+'が'+b+'より先' for a,b in problem['before'])+'になる。'
    elif not orders:
        reply='条件が矛盾していて、この順序を満たす並べ方はないよ。'
    else:
        reply=f'条件を満たす並べ方が{len(orders)}通りあるので、一つには決まらないよ。'
    return reply,{'kind':'ordering_enumeration','source':'user_conditions','solutions':[list(x) for x in orders],
                  'conditions':problem['before']}
