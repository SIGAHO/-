"""Bounded source observations for syntax failures. No edits or execution."""
import hashlib
import json


class SyntaxFeedback:
    def __init__(self):
        self.reset()

    def reset(self):
        self.last_fingerprint=None
        self.repeats=0

    def observe(self,workspace,error,checked_inputs):
        observation={'source':'current_workspace_file','cause_inferred':False}
        try:
            path=workspace.path(error.filename)
            if path.suffix!='.py' or path.stat().st_size>64000:return observation
            data=path.read_bytes()
            text=data.decode('utf-8-sig')
            name=str(path.relative_to(workspace.root))
            digest=hashlib.sha256(data).hexdigest()
            lines=text.splitlines()
            line=error.lineno
            if type(line) is not int or not 1<=line<=len(lines)+1:return observation
            excerpt=[]
            for index in range(max(0,line-3),min(len(lines),line+2)):
                source=lines[index]
                excerpt.append({'line':index+1,'text':source[:240],
                    'truncated':len(source)>240,'leading_whitespace':source[:len(source)-len(source.lstrip(' \t'))][:40]})
            observation.update(path=name,sha256=digest,error_line=line,error_offset=error.offset,
                lines=excerpt,matches_checked_input=isinstance(checked_inputs,dict) and checked_inputs.get(name)==digest)
            if not observation['matches_checked_input']:
                self.last_fingerprint=None
                self.repeats=0
                return observation
            fingerprint=json.dumps([checked_inputs,name,line,error.offset,error.msg],sort_keys=True)
            self.repeats=self.repeats+1 if fingerprint==self.last_fingerprint else 1
            self.last_fingerprint=fingerprint
            observation['unchanged_failure_count']=self.repeats
            observation['stalled']=self.repeats>=3
        except (OSError,ValueError,TypeError):
            observation['unavailable']=True
        return observation
