"""表达式词法分析与递归下降解析器。

文法（优先级从低到高）:
    expr   := term (('+' | '-') term)*
    term   := factor (('*' | '/' | '·') factor)*        # 另含隐式乘法
    factor := unary (('^' | '**') unary)                # 幂，右结合
    unary  := ('+' | '-')* primary
    primary:= NUMBER UNIT?
           |  NAME '(' arglist? ')'
           |  NAME UNIT?
           |  '(' expr ')' UNIT?

词法阶段识别两类 token:
    NUM  —— 数字字面量（小数 / 科学计数法）
    UNIT —— 单位短语，如 kg、°C、km/h、kg/m^3、m·s^-2
            数字后紧跟的空白分隔单位（25 °C）也在此阶段归入 UNIT。
变量名（含函数名、常量名）是普通 NAME。
单位名与变量名重名时（如 m 既是米又是变量名）按位置判定:
    数字、另一个单位、或 '*' '/' 之后的 NAME 视为单位；其余视为变量。
若用户确需名为 m 的变量，建议改名为 m_rate 等。

每个 AST 节点带 span=(start,end)，错误据此定位到表达式片段。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import List, Optional, Tuple

from .dimensions import ALIASES, COMPOUND_ALIASES, UnitExpr, UnitPiece, UNITS


class ParseError(Exception):
    def __init__(self, message: str, start: int, end: int):
        super().__init__(message)
        self.message = message
        self.start = start
        self.end = end


# ---------------------------------------------------------------- AST

@dataclass
class Node:
    span: Tuple[int, int] = (0, 0)


@dataclass
class NumberNode(Node):
    value: Fraction = Fraction(0)
    unit: Optional[UnitExpr] = None


@dataclass
class VarNode(Node):
    name: str = ""
    unit: Optional[UnitExpr] = None


@dataclass
class UnaryNode(Node):
    op: str = ""
    operand: Optional[Node] = None


@dataclass
class BinaryNode(Node):
    op: str = ""
    left: Optional[Node] = None
    right: Optional[Node] = None


@dataclass
class CallNode(Node):
    name: str = ""
    args: List[Node] = field(default_factory=list)
    arg_spans: List[Tuple[int, int]] = field(default_factory=list)
    unit: Optional[UnitExpr] = None


# ---------------------------------------------------------------- 词法

@dataclass
class Token:
    kind: str          # NUM / NAME / UNIT / OP / EOF
    value: str
    start: int
    end: int
    num: Optional[Fraction] = None
    unit: Optional[UnitExpr] = None
    unit_factor: float = 1.0


_UNIT_LEAD_CHARS = "°℃℉μΩ%"
_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789μΩ°℃℉%")
# 单位原子: 单位名（^ 整数幂，指数可带负号）
_UNIT_ATOM_RE = re.compile(
    r"[A-Za-z_°℃℉μΩ%][A-Za-z0-9_μΩ°℃℉%]*(?:\^-?\d+)?")
_UNIT_LEAD_CHARS = "°℃℉μΩ%"


def _is_unit_name(s: str) -> bool:
    return s.lower() in ALIASES


def resolve_unit_phrase(raw: str):
    """解析单位短语字符串 -> (UnitExpr, factor, ok)。

    支持 kg、m^2、kg*m/s^2、kg·m/s^2、km/h、g/L、m·s^-2、J/(mol·K)、% 等。
    分母可用括号包裹多个原子。
    """
    s = raw.strip()
    if s.lower() in COMPOUND_ALIASES:
        pcs, fac = COMPOUND_ALIASES[s.lower()]
        return _pieces_to_expr(pcs), fac, True
    pieces: List[UnitPiece] = []
    factor = 1.0
    pos = 0
    sign = 1
    n = len(s)
    while pos < n:
        # 括号分组（仅在分母位置出现，如 J/(mol·K)；也允许分子）
        if s[pos] == "(":
            depth, k = 0, pos
            while k < n:
                if s[k] == "(":
                    depth += 1
                elif s[k] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            if k >= n:
                return None, 1.0, False
            inner_expr, inner_fac, ok = resolve_unit_phrase(s[pos + 1:k])
            if not ok:
                return None, 1.0, False
            for p in inner_expr.pieces:
                pieces.append(UnitPiece(p.key, p.exp * sign))
            factor *= inner_fac ** sign
            pos = k + 1
        else:
            m = _UNIT_ATOM_RE.match(s, pos)
            if not m:
                return None, 1.0, False
            token = m.group(0)
            if "^" in token:
                name, exp_s = token.split("^", 1)
                exp = int(exp_s)
            else:
                name, exp = token, 1
            low = name.lower()
            if low in COMPOUND_ALIASES and exp == 1:
                pcs, fac = COMPOUND_ALIASES[low]
                for kk, ee in pcs:
                    pieces.append(UnitPiece(kk, ee * sign))
                factor *= fac ** sign
            elif low in ALIASES:
                pieces.append(UnitPiece(ALIASES[low], sign * exp))
            else:
                return None, 1.0, False
            pos = m.end()
        if pos >= n:
            break
        if s[pos] in "*/·":
            sign = -1 if s[pos] == "/" else 1
            pos += 1
            if pos >= n:
                return None, 1.0, False   # 尾随运算符
            continue
        return None, 1.0, False
    expr = _pieces_to_expr([(p.key, p.exp) for p in pieces])
    # offset 单位只能单独出现
    if expr is not None:
        for p in expr.pieces:
            d = UNITS[p.key]
            if d.offset != 0 and not (len(expr.pieces) == 1
                                      and expr.pieces[0].exp == 1):
                return None, 1.0, False
    return expr, factor, True


def _pieces_to_expr(pcs):
    merged, order = {}, []
    for k, e in pcs:
        if k not in merged:
            merged[k] = 0
            order.append(k)
        merged[k] += e
    return UnitExpr(tuple(UnitPiece(k, merged[k]) for k in order
                          if merged[k] != 0))


def tokenize(text: str) -> List[Token]:
    tokens: List[Token] = []
    i, n = 0, len(text)

    def is_name_start(ch):
        return ch.isalpha() or ch == "_" or ch in _UNIT_LEAD_CHARS or ord(ch) >= 0x2000

    def read_name(j):
        while j < n and (text[j].isalnum() or text[j] in _NAME_CHARS
                         or ord(text[j]) >= 0x2000):
            j += 1
        return j

    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        start = i
        wide = {"（": "(", "）": ")", "，": ",", "＊": "*", "／": "/",
                "－": "-", "＋": "+", "−": "-"}
        if c in wide:
            tokens.append(Token("OP", wide[c], i, i + 1))
            i += 1
            continue
        # 数字（可带紧邻单位，如 25°C、3kg）
        if c.isdigit() or (c == "." and i + 1 < n and text[i + 1].isdigit()):
            j = i + 1
            dot = c == "."
            while j < n and (text[j].isdigit() or (text[j] == "." and not dot)):
                dot |= text[j] == "."
                j += 1
            if j < n and text[j] in "eE":
                k = j + 1
                if k < n and text[k] in "+-":
                    k += 1
                if k < n and text[k].isdigit():
                    j = k
                    while j < n and text[j].isdigit():
                        j += 1
            raw = text[i:j]
            try:
                num = Fraction(raw)
            except (ValueError, ZeroDivisionError):
                num = Fraction(float(raw)).limit_denominator(10**12)
            tokens.append(Token("NUM", raw, i, j, num=num))
            i = j
            # 数字后的单位短语：紧邻（3kg）或空白分隔（25 °C、3 kg m/s^2）
            if i < n:
                had_space = text[i].isspace()
                end, expr, fac = _scan_unit_phrase(
                    text, i, skip_leading_space=True)
                if end > i:
                    ustart = end
                    # 找回单位首字符位置（跳过空白）
                    k2 = i
                    while k2 < n and text[k2].isspace():
                        k2 += 1
                    tokens.append(Token("UNIT", text[k2:end], k2, end,
                                        unit=expr, unit_factor=fac))
                    i = end
            continue
        # 名称：可能是变量/函数名，也可能是单位短语（kg、m/s^2、km/h）
        if is_name_start(c):
            j = read_name(i)
            name = text[i:j]
            # 尝试按单位短语扩展（吃到后面的 / * · ^数字 / 括号）
            end_u, expr_u, fac_u = _scan_unit_phrase(
                text, i, skip_leading_space=False)
            prev = tokens[-1] if tokens else None
            # NUM 后若只有空白（25 °C、3 m），同样视为单位语境
            num_space_ctx = False
            if prev is not None and prev.kind == "NUM":
                between = text[prev.end:i]
                num_space_ctx = between != "" and between.strip() == ""
            unit_context = num_space_ctx or (prev is not None and (
                prev.kind in ("NUM", "UNIT")
                or (prev.kind == "OP" and prev.value in "*/")))
            after = j
            while after < n and text[after].isspace():
                after += 1
            is_call = after < n and text[after] == "("
            name_is_unit = _is_unit_name(name)
            # 起始位置的单位短语必须包含 / · 或括号（如 m/s^2、J/(mol·K)），
            # 单纯的“名称^幂”（a^2、L^3）视为变量/数字的幂运算；
            # 单原子在开头也视为变量，避免 V、m、A 等单字母单位遮蔽同名变量。
            phrase_text = text[j:end_u]
            looks_unit_only = any(ch in phrase_text for ch in "/·(")
            phrase_extended = end_u > j
            multi_atom_start = (phrase_extended and looks_unit_only
                                and not unit_context)
            # 显式运算符 * / 之后：名称一律优先当变量（避免 V*m、m/s
            # 这类既可能是变量运算又可能是单位的写法被误吞）。需要单位
            # 常量时把单位写在数字后（60 km/h）或变量声明里。
            after_op = (prev is not None and prev.kind == "OP"
                        and prev.value in "*/")
            single_unit_as_var = after_op
            if (unit_context and (name_is_unit or phrase_extended)
                    or multi_atom_start) \
                    and not (is_call and not phrase_extended) \
                    and not single_unit_as_var:
                tokens.append(Token("UNIT", text[i:end_u], i, end_u,
                                    unit=expr_u, unit_factor=fac_u))
                i = end_u
            else:
                # 变量/函数名。变量后可空白跟“单个原子”单位（如 “T °C”），
                # 不吞 / * —— 它们属于表达式层运算；复合单位请写在变量值里
                # 或紧贴变量（v_m/s 式写法不推荐）。
                tokens.append(Token("NAME", name, i, j))
                i = j
                if i < n and text[i].isspace():
                    k = i
                    while k < n and text[k].isspace():
                        k += 1
                    if k < n and is_name_start(text[k]):
                        m = _UNIT_ATOM_RE.match(text, k)
                        if m:
                            base = m.group(0).split("^", 1)[0]
                            if _is_unit_name(base):
                                raw = text[k:m.end()]
                                expr, fac, ok = resolve_unit_phrase(raw)
                                if ok:
                                    tokens.append(Token("UNIT", raw, k, m.end(),
                                                        unit=expr,
                                                        unit_factor=fac))
                                    i = m.end()
            continue
        if c == "*" and i + 1 < n and text[i + 1] == "*":
            tokens.append(Token("OP", "**", i, i + 2))
            i += 2
            continue
        if c in "+-*/^()·,":
            tokens.append(Token("OP", c, i, i + 1))
            i += 1
            continue
        raise ParseError(f"无法识别的字符 “{c}”", i, i + 1)

    tokens.append(Token("EOF", "", n, n))
    return tokens


def _scan_unit_phrase(text: str, start: int, skip_leading_space: bool = False):
    """从 start 尝试匹配单位短语，返回 (end, UnitExpr|None, factor)。

    贪婪地吃完 单位原子(^指数)?，之间可有 * / · 连接符；
    任何一段不是已知单位则整体失败（返回 start）。
    skip_leading_space=True 时允许跳过前导空白（用于 “25 °C”）。
    """
    n = len(text)
    j = start
    if skip_leading_space:
        while j < n and text[j].isspace():
            j += 1
    ustart = j
    matched_any = False
    while True:
        if j < n and text[j] == "(":
            depth, k = 0, j
            while k < n:
                if text[k] == "(":
                    depth += 1
                elif text[k] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            if k >= n:
                break
            j = k + 1
            matched_any = True
        else:
            m = _UNIT_ATOM_RE.match(text, j)
            if not m:
                break
            base = m.group(0).split("^", 1)[0]
            if not (_is_unit_name(base) or base.lower() in COMPOUND_ALIASES):
                break
            matched_any = True
            j = m.end()
        # 仅当分隔符紧贴下一个单位原子（无空格）时才继续吞，
        # 否则分隔符属于表达式层（如 “100 km / 2 h”）。
        if j < n and text[j] in "*/·" and j + 1 < n:
            nxt = text[j + 1]
            if nxt == "(":
                j += 1
                continue
            m2 = _UNIT_ATOM_RE.match(text, j + 1)
            if m2:
                b2 = m2.group(0).split("^", 1)[0]
                if _is_unit_name(b2) or b2.lower() in COMPOUND_ALIASES:
                    j += 1
                    continue
        break
    if not matched_any:
        return start, None, 1.0
    raw = text[ustart:j]
    expr, fac, ok = resolve_unit_phrase(raw)
    if not ok:
        return start, None, 1.0
    return j, expr, fac


# ---------------------------------------------------------------- 解析

FUNCTIONS = {
    "sqrt", "abs", "exp", "ln", "log10", "log2", "log",
    "sin", "cos", "tan", "round", "floor", "ceil", "min", "max", "pow",
}
CONSTANTS = {"pi", "e", "R", "NA", "c0", "k_B", "N_A"}


class Parser:
    def __init__(self, text: str):
        self.text = text
        self.tokens = tokenize(text)
        self.pos = 0

    def peek(self, k: int = 0) -> Token:
        return self.tokens[min(self.pos + k, len(self.tokens) - 1)]

    def next(self) -> Token:
        t = self.tokens[self.pos]
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return t

    def expect(self, value: str) -> Token:
        t = self.peek()
        if t.kind != "OP" or t.value != value:
            want = {"(": "左括号 “(”", ")": "右括号 “)”", ",": "逗号 “,”"}.get(
                value, f"“{value}”")
            got = "表达式结尾" if t.kind == "EOF" else f"“{t.value}”"
            raise ParseError(f"期望 {want}，但得到 {got}", t.start, t.end)
        return self.next()

    def parse(self) -> Node:
        node = self.parse_expr()
        t = self.peek()
        if t.kind != "EOF":
            raise ParseError(f"表达式存在无法解析的片段 “{t.value}”",
                             t.start, t.end)
        return node

    def parse_expr(self) -> Node:
        left = self.parse_term()
        while self.peek().kind == "OP" and self.peek().value in "+-":
            op = self.next()
            right = self.parse_term()
            left = BinaryNode((left.span[0], right.span[1]),
                              op.value, left, right)
        return left

    def parse_term(self) -> Node:
        left = self.parse_power()
        while True:
            t = self.peek()
            if t.kind == "OP" and t.value in ("*", "/", "·"):
                op = self.next()
                right = self.parse_power()
                left = BinaryNode((left.span[0], right.span[1]),
                                  "*" if op.value == "·" else op.value,
                                  left, right)
            elif t.kind in ("NUM", "UNIT", "NAME") \
                    or (t.kind == "OP" and t.value == "("):
                # 隐式乘法: 2 x、(a)(b)、kg m（相邻 UNIT）
                right = self.parse_power()
                left = BinaryNode((left.span[0], right.span[1]),
                                  "*", left, right)
            else:
                break
        return left

    def parse_power(self) -> Node:
        base = self.parse_unary()
        t = self.peek()
        if t.kind == "OP" and t.value in ("^", "**"):
            self.next()
            exp_node = self.parse_power()
            return BinaryNode((base.span[0], exp_node.span[1]),
                              "^", base, exp_node)
        return base

    def parse_unary(self) -> Node:
        if self.peek().kind == "OP" and self.peek().value in "+-":
            op = self.next()
            operand = self.parse_unary()
            return UnaryNode((op.start, operand.span[1]), op.value, operand)
        return self.parse_primary()

    def parse_primary(self) -> Node:
        t = self.peek()
        if t.kind == "NUM":
            self.next()
            unit = None
            end = t.end
            if self.peek().kind == "UNIT":
                ut = self.next()
                unit = ut.unit
                end = ut.end
            return NumberNode((t.start, end), t.num, unit)
        if t.kind == "UNIT":
            # 独立单位开头（如 m/s^2）：视为数字 1 乘该单位
            self.next()
            return NumberNode((t.start, t.end), Fraction(1), t.unit)
        if t.kind == "OP" and t.value == "(":
            self.next()
            inner = self.parse_expr()
            self.expect(")")
            close_end = self.tokens[self.pos - 1].end
            unit = None
            if self.peek().kind == "UNIT":
                ut = self.next()
                unit = ut.unit
            inner.span = (t.start, ut.end if unit else close_end)
            inner = self._annotate_paren(inner, unit)
            return inner
        if t.kind == "NAME":
            if self.peek(1).kind == "OP" and self.peek(1).value == "(":
                return self.parse_call()
            self.next()
            unit = None
            end = t.end
            if self.peek().kind == "UNIT":
                ut = self.next()
                unit = ut.unit
                end = ut.end
            return VarNode((t.start, end), t.value, unit)
        if t.kind == "EOF":
            raise ParseError("表达式意外结束，缺少操作数", t.start, t.start + 1)
        raise ParseError(f"此处不能出现 “{t.value}”，期望数字、变量或括号",
                         t.start, t.end)

    def _annotate_paren(self, node: Node, unit) -> Node:
        """括号后的单位尾巴等价于对括号结果做乘法，包装成 BinaryNode。"""
        if unit is None:
            return node
        unit_node = NumberNode(node.span, Fraction(1), unit)
        return BinaryNode(node.span, "*", node, unit_node)

    def parse_call(self) -> Node:
        name_tok = self.next()
        if name_tok.value not in FUNCTIONS:
            raise ParseError(f"未知函数 “{name_tok.value}”",
                             name_tok.start, name_tok.end)
        open_paren = self.expect("(")
        args, arg_spans = [], []
        if not (self.peek().kind == "OP" and self.peek().value == ")"):
            while True:
                a = self.parse_expr()
                args.append(a)
                arg_spans.append(a.span)
                if self.peek().kind == "OP" and self.peek().value == ",":
                    self.next()
                    if self.peek().kind == "OP" and self.peek().value == ")":
                        t = self.peek()
                        raise ParseError("函数参数列表末尾多余的逗号",
                                         t.start, t.end)
                    continue
                break
        self.expect(")")
        close_end = self.tokens[self.pos - 1].end
        unit = None
        if self.peek().kind == "UNIT":
            ut = self.next()
            unit = ut.unit
        return CallNode((name_tok.start, ut.end if unit else close_end),
                        name_tok.value, args, arg_spans, unit)


def parse(text: str) -> Node:
    return Parser(text).parse()
