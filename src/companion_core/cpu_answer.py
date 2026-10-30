"""Bounded arithmetic and time answers never pass through model generation/rewrite."""
import ast
from datetime import datetime, timedelta
from decimal import Decimal, DecimalException, localcontext
import operator
import re
from .intent import normalized


class CPUAnswer:
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Mod: operator.mod}

    @classmethod
    def calculate(cls, expression):
        if len(expression) > 160 or not re.fullmatch(r'[0-9().+*/%\s-]+', expression):
            raise ValueError('unsupported arithmetic')
        tree = ast.parse(expression.strip(), mode='eval')
        if sum(1 for _ in ast.walk(tree)) > 60:
            raise ValueError('expression too complex')
        def visit(node):
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                return Decimal(ast.get_source_segment(expression.strip(), node))
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                return visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
            if isinstance(node, ast.BinOp) and type(node.op) in cls.ops:
                return cls.ops[type(node.op)](visit(node.left), visit(node.right))
            raise ValueError('unsupported arithmetic')
        with localcontext() as ctx:
            ctx.prec = 28
            value = visit(tree.body)
        if not value.is_finite() or abs(value) > Decimal('1e30'):
            raise ValueError('result outside supported range')
        return format(value, 'f').rstrip('0').rstrip('.') if '.' in format(value, 'f') else str(value)

    def answer(self, text, facts):
        t = normalized(text)
        n = datetime.fromisoformat(facts['time.iso'])
        try:
            pair = re.fullmatch(r'(\d{1,2})(?::(\d{1,2})|時(?:(\d{1,2})分?)?)\s*(?:→|から)\s*(\d{1,2})(?::(\d{1,2})|時(?:(\d{1,2})分?)?)(?:まで)?(?:は|あと)?(?:何分)?[?。\s]*', t)
            if pair:
                h, end_h = int(pair[1]), int(pair[4])
                m, end_m = int(pair[2] or pair[3] or 0), int(pair[5] or pair[6] or 0)
                if not (0 <= h < 24 and 0 <= end_h < 24 and 0 <= m < 60 and 0 <= end_m < 60):
                    raise ValueError('invalid time')
                return f'{(end_h * 60 + end_m - h * 60 - m) % 1440}分。'
            target = re.fullmatch(r'(?:今日の|明日の)?(\d{1,2})(?::(\d{1,2})|時(?:(\d{1,2})分)?)(?:まで)(?:あと|残り)?何分[?。\s]*', t)
            if target:
                h = int(target[1]); minute = int(target[2] or target[3] or 0)
                if not (0 <= h < 24 and 0 <= minute < 60):
                    raise ValueError('invalid time')
                end = n.replace(hour=h, minute=minute, second=0, microsecond=0)
                if t.startswith('明日'):
                    end += timedelta(days=1)
                seconds = (end - n).total_seconds()
                if seconds < 0:
                    return '今日のその時刻はもう過ぎている。明日の時刻なら「明日の8時まであと何分？」のように指定して。'
                minutes, seconds = divmod(int(seconds), 60)
                return f'あと{minutes}分' + (f'{seconds}秒。' if seconds else '。')
            if re.fullmatch(r'(?:今何時|現在の?時刻)(?:ですか)?[?。\s]*', t):
                return n.strftime('%H:%M:%S') + '（Asia/Tokyo）。'
            if re.fullmatch(r'(?:今日(?:は)?|今(?:日)?(?:は)?)?何曜日(?:ですか)?[?。\s]*', t):
                return '月火水木金土日'[n.weekday()] + '曜日。'
            if re.fullmatch(r'(?:今日(?:の|は)?)?(?:日付|何日)(?:は)?(?:ですか)?[?。\s]*', t):
                return f'{n.year}年{n.month}月{n.day}日。'
            expr = re.sub(r'^計算して[:：\s]*', '', t)
            expr = re.sub(r'(?:は|=)?[?。\s]*$', '', expr)
            return self.calculate(expr) + '。'
        except (ValueError, SyntaxError, DecimalException, OverflowError, RecursionError, TypeError):
            return 'その時刻・計算式はCPUで確定できない。時刻か簡単な四則演算を明示して。'
