"""量纲推导引擎：词法分析 → 递归下降解析 → 量纲/数值求值。

支持：
  - 四则运算、幂运算（^ 或 **，右结合）、括号、一元正负号
  - 隐式乘法：``2 m``、``2(1+1)``、``kg m/s^2``、``2π r``
  - 数字后跟单位：``9.8 m/s^2``、``1.5e-3 mol``
  - 上标 Unicode：``m²``、``x⁻¹``
  - 全角/符号运算符：× ÷ · −
  - 函数调用：sqrt / abs / sin / cos / tan / asin / acos / atan / exp / ln / log / log2
  - 变量引用（变量值本身也是带单位的表达式，可相互引用，检测循环）

所有错误都携带 (start, end) 片段位置，指回原始表达式字符串。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from fractions import Fraction

from .units import (
    CONSTANTS, DIMLESS, DIM_NAMES, FUNCTIONS, UNITS,
    derived_matches, dim_str, format_fraction, si_unit_str,
)

# ---------------------------------------------------------------------------
# 错误
# ---------------------------------------------------------------------------

@dataclass
class AnalysisError:
    message: str
    start: int
    end: int
    kind: str = "error"
    source: str = "expression"  # expression / target / var:<name>

    def to_dict(self) -> dict:
        return {
            "message": self.message,
            "start": self.start,
            "end": self.end,
            "kind": self.kind,
            "source": self.source,
        }


class EngineError(Exception):
    """携带片段位置的引擎内部异常。"""

    def __init__(self, message: str, start: int, end: int, kind: str = "error"):
        super().__init__(message)
        self.error = AnalysisError(message, start, end, kind)


# ---------------------------------------------------------------------------
# 词法分析
# ---------------------------------------------------------------------------

@dataclass
class Token:
    kind: str          # num / ident / op / eof
    text: str
    start: int
    end: int
    value: float = 0.0


_NUM_RE = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")

_SUPERSCRIPTS = {
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9", "⁻": "-",
}

# 单字符运算符（含常见全角/符号别名，长度均为 1，不影响片段定位）
_CHAR_OPS = {
    "+": "+", "-": "-", "−": "-",
    "*": "*", "×": "*", "·": "*", "⋅": "*",
    "/": "/", "÷": "/",
    "^": "^", "(": "(", ")": ")", ",": ",",
}

_IDENT_EXTRA_START = "_°%"   # isalpha() 之外的标识符起始字符
_IDENT_EXTRA_CONT = "_"


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch.isspace():
            i += 1
            continue
        # 注意：'²' 等上标字符的 isdigit() 为真，数字判断必须限定 ASCII
        if ch in "0123456789" or (ch == "." and i + 1 < n and src[i + 1] in "0123456789"):
            m = _NUM_RE.match(src, i)
            assert m is not None
            text = m.group()
            tokens.append(Token("num", text, i, m.end(), float(text)))
            i = m.end()
            continue
        if ch in _SUPERSCRIPTS:
            j = i
            digits = ""
            while j < n and src[j] in _SUPERSCRIPTS:
                digits += _SUPERSCRIPTS[src[j]]
                j += 1
            # 上标序列 → 幂运算：^ <digits>（^ 为零宽 token，指向上标起点）
            tokens.append(Token("op", "^", i, i))
            tokens.append(Token("num", digits, i, j, float(digits)))
            i = j
            continue
        if ch.isalpha() or ch in _IDENT_EXTRA_START:
            j = i + 1
            # 注意：'²' 等上标字符的 isalnum() 为真，必须显式排除
            while j < n and src[j] not in _SUPERSCRIPTS and (
                src[j].isalnum() or src[j] in _IDENT_EXTRA_CONT
            ):
                j += 1
            tokens.append(Token("ident", src[i:j], i, j))
            i = j
            continue
        if ch == "*" and i + 1 < n and src[i + 1] == "*":
            tokens.append(Token("op", "^", i, i + 2))
            i += 2
            continue
        if ch in _CHAR_OPS:
            tokens.append(Token("op", _CHAR_OPS[ch], i, i + 1))
            i += 1
            continue
        raise EngineError(f"无法识别的字符「{ch}」", i, i + 1, "syntax")
    tokens.append(Token("eof", "", n, n))
    return tokens


# ---------------------------------------------------------------------------
# 语法分析（递归下降）
# ---------------------------------------------------------------------------

@dataclass
class Node:
    kind: str                       # num / name / neg / bin / pow / call / group
    start: int
    end: int
    value: float = 0.0
    name: str = ""
    op: str = ""
    left: "Node | None" = None
    right: "Node | None" = None
    args: list = field(default_factory=list)


class Parser:
    """文法（优先级由低到高）：
        add  := mul  (('+'|'-') mul)*
        mul  := unary (('*'|'/'|隐式) unary)*
        unary:= ('-'|'+') unary | pow
        pow  := primary ('^' unary)?          （右结合；指数允许负号）
        primary := NUMBER | IDENT | IDENT '(' args ')' | '(' add ')'
    隐式乘法：primary 之后紧跟 NUMBER / IDENT / '(' 时视为相乘。
    """

    def __init__(self, tokens: list[Token]):
        self.toks = tokens
        self.i = 0

    def peek(self) -> Token:
        return self.toks[self.i]

    def advance(self) -> Token:
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def expect_op(self, op: str) -> Token:
        tok = self.peek()
        if tok.kind != "op" or tok.text != op:
            raise EngineError(f"此处应为「{op}」", tok.start, max(tok.end, tok.start + 1), "syntax")
        return self.advance()

    def parse(self) -> Node:
        if self.peek().kind == "eof":
            raise EngineError("表达式为空", 0, 0, "syntax")
        node = self.parse_add()
        tok = self.peek()
        if tok.kind != "eof":
            raise EngineError(f"此处有多余的内容「{tok.text}」", tok.start, max(tok.end, tok.start + 1), "syntax")
        return node

    def parse_add(self) -> Node:
        left = self.parse_mul()
        while self.peek().kind == "op" and self.peek().text in ("+", "-"):
            op = self.advance()
            right = self.parse_mul()
            left = Node("bin", left.start, right.end, op=op.text, left=left, right=right)
        return left

    def parse_mul(self) -> Node:
        left = self.parse_unary()
        while True:
            tok = self.peek()
            if tok.kind == "op" and tok.text in ("*", "/"):
                self.advance()
                right = self.parse_unary()
                left = Node("bin", left.start, right.end, op=tok.text, left=left, right=right)
            elif tok.kind in ("num", "ident") or (tok.kind == "op" and tok.text == "("):
                right = self.parse_unary()  # 隐式乘法
                left = Node("bin", left.start, right.end, op="*", left=left, right=right)
            else:
                return left

    def parse_unary(self) -> Node:
        tok = self.peek()
        if tok.kind == "op" and tok.text == "-":
            self.advance()
            operand = self.parse_unary()
            return Node("neg", tok.start, operand.end, left=operand)
        if tok.kind == "op" and tok.text == "+":
            self.advance()
            return self.parse_unary()
        return self.parse_pow()

    def parse_pow(self) -> Node:
        base = self.parse_primary()
        tok = self.peek()
        if tok.kind == "op" and tok.text == "^":
            self.advance()
            exponent = self.parse_unary()
            return Node("pow", base.start, exponent.end, left=base, right=exponent)
        return base

    def parse_primary(self) -> Node:
        tok = self.peek()
        if tok.kind == "num":
            self.advance()
            return Node("num", tok.start, tok.end, value=tok.value)
        if tok.kind == "ident":
            self.advance()
            name = tok.text
            nxt = self.peek()
            if name in FUNCTIONS and nxt.kind == "op" and nxt.text == "(":
                self.advance()
                args: list[Node] = []
                if not (self.peek().kind == "op" and self.peek().text == ")"):
                    args.append(self.parse_add())
                    while self.peek().kind == "op" and self.peek().text == ",":
                        self.advance()
                        args.append(self.parse_add())
                rpar = self.expect_op(")")
                return Node("call", tok.start, rpar.end, name=name, args=args)
            return Node("name", tok.start, tok.end, name=name)
        if tok.kind == "op" and tok.text == "(":
            self.advance()
            inner = self.parse_add()
            rpar = self.expect_op(")")
            return Node("group", tok.start, rpar.end, left=inner)
        raise EngineError("此处应为数字、变量、单位或括号", tok.start, max(tok.end, tok.start + 1), "syntax")


# ---------------------------------------------------------------------------
# 求值（数值 + 量纲递归推导）
# ---------------------------------------------------------------------------

@dataclass
class Quantity:
    value: float      # 以 SI 基本单位计的数值
    dim: tuple        # 量纲向量


def _dim_add(a: tuple, b: tuple) -> tuple:
    return tuple(x + y for x, y in zip(a, b))


def _dim_sub(a: tuple, b: tuple) -> tuple:
    return tuple(x - y for x, y in zip(a, b))


def _dim_scale(d: tuple, k: Fraction) -> tuple:
    return tuple(x * k for x in d)


class Evaluator:
    """对 AST 递归求值。resolve(name, node) 由外层注入，用于解析变量/单位/常量。"""

    def __init__(self, resolve):
        self.resolve = resolve

    def eval(self, node: Node) -> Quantity:
        kind = node.kind
        if kind == "num":
            return Quantity(node.value, DIMLESS)
        if kind == "group":
            return self.eval(node.left)
        if kind == "name":
            return self.resolve(node.name, node)
        if kind == "neg":
            q = self.eval(node.left)
            return Quantity(-q.value, q.dim)
        if kind == "call":
            args = [self.eval(a) for a in node.args]
            return self._call(node, args)
        if kind == "bin":
            return self._bin(node)
        if kind == "pow":
            return self._pow(node)
        raise EngineError(f"内部错误：未知节点 {kind}", node.start, node.end)

    # -- 二元运算 -----------------------------------------------------------
    def _bin(self, node: Node) -> Quantity:
        left = self.eval(node.left)
        right = self.eval(node.right)
        op = node.op
        if op in ("+", "-"):
            if left.dim != right.dim:
                word = "加" if op == "+" else "减"
                raise EngineError(
                    f"量纲不一致：「{dim_str(left.dim)}」与「{dim_str(right.dim)}」不能相{word}",
                    node.right.start, node.right.end, "dim_mismatch",
                )
            value = left.value + right.value if op == "+" else left.value - right.value
            return Quantity(value, left.dim)
        if op == "*":
            return Quantity(left.value * right.value, _dim_add(left.dim, right.dim))
        if op == "/":
            if right.value == 0:
                raise EngineError("除数为零", node.right.start, node.right.end, "value")
            return Quantity(left.value / right.value, _dim_sub(left.dim, right.dim))
        raise EngineError(f"内部错误：未知运算符 {op}", node.start, node.end)

    # -- 幂运算 -------------------------------------------------------------
    def _pow(self, node: Node) -> Quantity:
        base = self.eval(node.left)
        expo = self.eval(node.right)
        if expo.dim != DIMLESS:
            raise EngineError(
                f"幂指数必须无量纲（实际量纲为 {dim_str(expo.dim)}）",
                node.right.start, node.right.end, "bad_exponent",
            )
        k = Fraction(expo.value).limit_denominator(1_000_000)
        try:
            value = base.value ** float(k)
        except ZeroDivisionError:
            raise EngineError("零的负数次幂无意义", node.start, node.end, "value") from None
        except OverflowError:
            raise EngineError("数值溢出", node.start, node.end, "value") from None
        if isinstance(value, complex):
            raise EngineError("负数不能取分数次幂", node.start, node.end, "value")
        return Quantity(value, _dim_scale(base.dim, k))

    # -- 函数调用 -----------------------------------------------------------
    def _call(self, node: Node, args: list[Quantity]) -> Quantity:
        name = node.name
        meta = FUNCTIONS[name]
        if len(args) != meta["arity"]:
            raise EngineError(
                f"函数 {name} 需要 {meta['arity']} 个参数，实际给了 {len(args)} 个",
                node.start, node.end, "arity",
            )
        arg_node = node.args[0]
        q = args[0]
        if name == "sqrt":
            if q.value < 0:
                raise EngineError("sqrt 的参数不能为负数", arg_node.start, arg_node.end, "value")
            return Quantity(math.sqrt(q.value), _dim_scale(q.dim, Fraction(1, 2)))
        if name == "abs":
            return Quantity(abs(q.value), q.dim)
        if q.dim != DIMLESS:
            raise EngineError(
                f"函数 {name} 的参数必须无量纲（实际量纲为 {dim_str(q.dim)}）",
                arg_node.start, arg_node.end, "dimless_arg",
            )
        fn = {
            "sin": math.sin, "cos": math.cos, "tan": math.tan,
            "asin": math.asin, "acos": math.acos, "atan": math.atan,
            "exp": math.exp, "ln": math.log, "log": math.log10, "log2": math.log2,
        }[name]
        try:
            return Quantity(fn(q.value), DIMLESS)
        except ValueError:
            raise EngineError(f"函数 {name} 的参数超出定义域", arg_node.start, arg_node.end, "value") from None
        except OverflowError:
            raise EngineError("数值溢出", arg_node.start, arg_node.end, "value") from None


# ---------------------------------------------------------------------------
# 顶层分析入口
# ---------------------------------------------------------------------------

def _parse_and_eval(src: str, resolve) -> Quantity:
    tokens = tokenize(src)
    node = Parser(tokens).parse()
    return Evaluator(resolve).eval(node)


def analyze(expression: str, variables: dict | None = None,
            target_unit: str | None = None) -> dict:
    """分析表达式，返回可 JSON 序列化的结果字典。

    即使存在错误也会尽量返回已算出的部分；errors 中每项都带有
    source（expression / target / var:<名称>）与 (start, end) 片段位置。
    """
    expression = expression or ""
    variables = {
        str(k).strip(): (v if isinstance(v, str) else str(v))
        for k, v in (variables or {}).items() if str(k).strip()
    }
    errors: list[AnalysisError] = []
    # 变量名与内置单位/常量同名时给出非致命警告（变量优先级更高）
    warnings = []
    for name in variables:
        if name in UNITS:
            warnings.append({"message": f"变量「{name}」与内置单位同名，所有表达式中的 {name} 将按变量解析",
                             "name": name, "kind": "shadow_unit"})
        elif name in CONSTANTS:
            warnings.append({"message": f"变量「{name}」与内置常量同名，所有表达式中的 {name} 将按变量解析",
                             "name": name, "kind": "shadow_constant"})
    var_qty: dict[str, Quantity] = {}
    var_err: dict[str, EngineError] = {}
    stack: list[str] = []

    def evaluate_variable(name: str) -> None:
        if name in var_qty or name in var_err:
            return
        stack.append(name)
        try:
            q = _parse_and_eval(variables[name], make_resolver())
            var_qty[name] = q
        except EngineError as exc:
            exc.error.source = f"var:{name}"
            var_err[name] = exc
            errors.append(exc.error)
        except OverflowError:
            err = EngineError("数值溢出", 0, len(variables[name]), "value")
            err.error.source = f"var:{name}"
            var_err[name] = err
            errors.append(err.error)
        finally:
            stack.pop()

    def make_resolver():
        def resolve(name: str, node: Node) -> Quantity:
            if name in var_qty:
                return var_qty[name]
            if name in var_err:
                raise EngineError(
                    f"变量「{name}」计算出错：{var_err[name].error.message}",
                    node.start, node.end, "var_error",
                )
            if name in variables:
                if name in stack:
                    chain = " → ".join(stack + [name])
                    raise EngineError(f"变量循环引用：{chain}", node.start, node.end, "var_cycle")
                evaluate_variable(name)
                if name in var_qty:
                    return var_qty[name]
                raise EngineError(
                    f"变量「{name}」计算出错：{var_err[name].error.message}",
                    node.start, node.end, "var_error",
                )
            if name in CONSTANTS:
                value, d, _ = CONSTANTS[name]
                return Quantity(value, d)
            if name in UNITS:
                d, factor, _, _ = UNITS[name]
                return Quantity(factor, d)
            raise EngineError(f"未定义的变量或单位「{name}」", node.start, node.end, "undefined")
        return resolve

    # 先求值全部变量（即使未被引用，也能暴露变量自身的错误）
    for name in variables:
        evaluate_variable(name)

    # 主表达式
    result: Quantity | None = None
    try:
        result = _parse_and_eval(expression, make_resolver())
        if not math.isfinite(result.value):
            raise EngineError("计算结果不是有限数值", 0, len(expression), "value")
    except EngineError as exc:
        exc.error.source = "expression"
        errors.append(exc.error)
    except OverflowError:
        err = EngineError("数值溢出", 0, len(expression), "value")
        err.error.source = "expression"
        errors.append(err.error)

    # 目标单位换算
    target = None
    if target_unit and target_unit.strip():
        try:
            tq = _parse_and_eval(target_unit.strip(), make_resolver())
            if tq.value == 0:
                raise EngineError("目标单位不能为零", 0, len(target_unit), "value")
            if result is not None:
                if tq.dim != result.dim:
                    raise EngineError(
                        f"目标单位量纲为「{dim_str(tq.dim)}」，与结果量纲「{dim_str(result.dim)}」不一致",
                        0, len(target_unit), "target_dim",
                    )
                target = {"unit": target_unit.strip(), "value": result.value / tq.value}
        except EngineError as exc:
            exc.error.source = "target"
            errors.append(exc.error)

    response: dict = {
        "ok": not errors,
        "errors": [e.to_dict() for e in errors],
        "warnings": warnings,
        "result": None,
    }
    if result is not None:
        response["result"] = {
            "si_value": result.value,
            "dimension": [format_fraction(x) for x in result.dim],
            "dimension_names": DIM_NAMES,
            "dimension_str": dim_str(result.dim),
            "si_unit": si_unit_str(result.dim),
            "derived": derived_matches(result.dim),
            "target": target,
        }
    return response
