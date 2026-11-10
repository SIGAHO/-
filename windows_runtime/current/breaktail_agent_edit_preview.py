"""Syntax-only preview for literal Python replacements; never executes code."""
import ast
import hashlib
from pathlib import Path


class ReplacementSyntaxError(ValueError):
    def __init__(self,observation):
        super().__init__('Python replacement would introduce invalid syntax; original file unchanged. Check candidate indentation/newlines, read the file and correct the replacement or write the complete file.')
        self.observation=observation


def preview(name,before,candidate,source_sha256):
    if len(candidate.encode('utf-8'))>64000:raise ValueError('UTF-8 content must be <=64KB')
    if Path(name).suffix.lower()!='.py':return {'checked':False,'reason':'not_python'}
    try:
        ast.parse(before,filename=name)
    except SyntaxError:
        return {'checked':False,'reason':'original_syntax_invalid'}
    try:
        ast.parse(candidate,filename=name)
    except SyntaxError as error:
        lines=candidate.splitlines()
        line=error.lineno or 1
        excerpt=[]
        for index in range(max(0,line-3),min(len(lines),line+2)):
            text=lines[index]
            excerpt.append({'line':index+1,'text':text[:240],'truncated':len(text)>240,
                            'leading_whitespace':text[:len(text)-len(text.lstrip(' \t'))][:40]})
        raise ReplacementSyntaxError({'source':'replacement_candidate_not_written','path':name,
            'original_sha256':source_sha256,'candidate_sha256':hashlib.sha256(candidate.encode('utf-8')).hexdigest(),
            'error':type(error).__name__,'error_line':line,'error_offset':error.offset,
            'lines':excerpt,'written':False,'execution_performed':False}) from None
    return {'checked':True,'kind':'replacement_syntax_only','execution_performed':False}
