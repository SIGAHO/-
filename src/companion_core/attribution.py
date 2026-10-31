"""Bounded experimental attribution signal; not a fact checker or a labeler."""
import re
from .topic_evidence import _tokenizer
from .style import StyleValidator

FRIEND = {'友達', '友人', '友だち'}
USER = {'俺', '僕', '私', '自分', 'お前', 'あなた', '君'}


def _claims(text):
    # Only explicit subject + topic/case marker + one sahen verb.  Skip
    # questions, negation, quotations and clauses with multiple subjects.
    text = StyleValidator.protected.sub('', text)
    result = set()
    for clause in re.split(r'(?<=[、,。.!！?？\n])', text):
        if re.search(r'[?？]', clause):
            continue
        tokens = list(_tokenizer().tokenize(clause))
        subjects = [(i, t.surface) for i, t in enumerate(tokens[:-1])
                    if t.surface in FRIEND | USER and tokens[i+1].surface in {'は', 'が', 'も'}]
        if len(subjects) != 1:
            continue
        i, subject = subjects[0]
        for j in range(i+2, len(tokens)-1):
            token, following = tokens[j], tokens[j+1]
            if (token.part_of_speech.startswith('名詞,サ変接続') and following.base_form == 'する'):
                tail = ''.join(t.surface for t in tokens[j+2:])
                if re.search(r'^(?:(?:て|で)?(?:いない|いません|いなかっ)|ない|なかっ|ません|ず|たら|れば|ば|なら|たわけじゃない|た(?:の|ん)?(?:では|じゃ)なく)', tail):
                    break
                result.add(('friend' if subject in FRIEND else 'user', token.surface))
                break
    return result


def unsupported_attribution(reply, current, recent):
    if re.search(r'[?？]', reply):
        return False
    source = _claims(current)
    for turn in recent[-8:]:
        if turn.get('role') == 'user':
            source |= _claims(turn.get('text', ''))
    response = _claims(StyleValidator().analysis_prose(reply, current))
    return any(('friend', event) in source and ('user', event) not in source
               and ('user', event) in response for _, event in source)
