"""
title: Rechner
description: Exakter Taschenrechner für Grundrechenarten, Potenzen, Prozente und Rundung — ohne Schätzfehler des Sprachmodells.
version: 1.0.0
"""

import ast
import math
import operator

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_FUNCTIONS = {
    'abs': abs,
    'round': round,
    'min': min,
    'max': max,
    'sqrt': math.sqrt,
    'log': math.log,
    'log10': math.log10,
    'exp': math.exp,
    'sin': math.sin,
    'cos': math.cos,
    'tan': math.tan,
}

_CONSTANTS = {
    'pi': math.pi,
    'e': math.e,
}

_MAX_POW = 1000


def _eval_node(node):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError('Nur Zahlen sind erlaubt')
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POW:
            raise ValueError(f'Exponent zu groß (maximal {_MAX_POW})')
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS:
        if node.keywords:
            raise ValueError('Benannte Argumente sind nicht erlaubt')
        return _FUNCTIONS[node.func.id](*[_eval_node(arg) for arg in node.args])
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    raise ValueError(f'Nicht unterstützter Ausdruck: {ast.dump(node)[:80]}')


class Tools:
    async def calculate(self, expression: str) -> str:
        """
        Berechnet einen mathematischen Ausdruck exakt und gibt das Ergebnis zurück. Nutze dieses Werkzeug für jede Rechnung, statt selbst zu rechnen.

        :param expression: Mathematischer Ausdruck in Python-Notation, z. B. "1250 * 0.19", "round(7 / 3, 2)" oder "sqrt(2) * pi". Erlaubt: + - * / // % ** Klammern sowie abs, round, min, max, sqrt, log, log10, exp, sin, cos, tan, pi, e.
        :return: Das Ergebnis der Berechnung oder eine Fehlermeldung.
        """
        expression = (expression or '').strip()
        if not expression:
            return 'Fehler: Es wurde kein Ausdruck übergeben.'
        if len(expression) > 500:
            return 'Fehler: Der Ausdruck ist zu lang (maximal 500 Zeichen).'
        try:
            tree = ast.parse(expression, mode='eval')
            result = _eval_node(tree)
        except ZeroDivisionError:
            return 'Fehler: Division durch null.'
        except (ValueError, SyntaxError, TypeError, OverflowError) as e:
            return f'Fehler: Der Ausdruck konnte nicht berechnet werden ({e}).'

        if isinstance(result, float) and result.is_integer() and abs(result) < 1e15:
            result = int(result)
        return f'{expression} = {result}'


if __name__ == '__main__':
    import asyncio

    tools = Tools()

    def calc(expr):
        return asyncio.run(tools.calculate(expr))

    assert calc('2 + 3 * 4') == '2 + 3 * 4 = 14'
    assert calc('round(7 / 3, 2)') == 'round(7 / 3, 2) = 2.33'
    assert calc('1250 * 0.19') == '1250 * 0.19 = 237.5'
    assert calc('sqrt(16)') == 'sqrt(16) = 4'
    assert calc('1 / 0').startswith('Fehler: Division durch null')
    assert calc('__import__("os")').startswith('Fehler')
    assert calc('2 ** 99999').startswith('Fehler')
    assert calc('').startswith('Fehler')
    print('ok')
