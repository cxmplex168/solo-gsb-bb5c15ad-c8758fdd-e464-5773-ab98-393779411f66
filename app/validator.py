"""递归量纲推导 + 数值换算求值。

求值结果 R 同时携带:
    value  —— 以 SI 基准单位表示的数值（float）
    dim    —— Dimension
    unit   —— 显示单位（UnitExpr），数值按显示单位的 factor 折算:
              value_si = factor * value_display
对带 offset 的简单温度单位（°C/°F）额外携带 offset 语义。

错误类型:
    DimError        量纲不一致（相加异量纲 / 非法幂 / 函数量纲错误）
    UndefVarError   未定义变量
    EvalError       数值域错误（除零、负数开方等）
所有错误均带 span，前端可高亮到表达式片段。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

from .dimensions import Dimension, UnitExpr, UnitPiece, UNITS
from .parser import (
    BinaryNode, CallNode, Node, NumberNode,
    ParseError, UnaryNode, VarNode, parse,
)


class ValidateError(Exception):
    def __init__(self, code: str, message: str, start: int, end: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.start = start
        self.end = end


@dataclass
class R:
    value: float
    dim: Dimension
    unit: Optional[UnitExpr] = None
    offset: float = 0.0          # 简单温度单位的偏移
    display_value: Optional[float] = None  # 显示单位下的数值
    span: Tuple[int, int] = (0, 0)
    undef: bool = False          # 未定义变量传播标记
    desc: str = ""               # 节点简述（推导轨迹用）
    difference: bool = False     # 差值语义（温差）：换算时不应用温标偏移

    def shown(self) -> float:
        if self.display_value is not None:
            return self.display_value
        return self.value


# 内置常量: name -> (SI 基准值, UnitExpr 或 None, 说明)
def _u(s: str) -> UnitExpr:
    from .parser import resolve_unit_phrase
    expr, _, ok = resolve_unit_phrase(s)
    assert ok, s
    return expr


CONSTANT_VALUES = {
    "pi": (math.pi, None, "圆周率 π"),
    "e": (math.e, None, "自然对数底 e"),
    "R": (8.314462618, _u("kg·m^2/(s^2·mol·K)"), "气体常数 R（J/(mol·K)）"),
    "NA": (6.02214076e23, _u("mol^-1"), "阿伏伽德罗常数 N_A（mol⁻¹）"),
    "N_A": (6.02214076e23, _u("mol^-1"), "阿伏伽德罗常数 N_A（mol⁻¹）"),
    "c0": (299792458.0, _u("m/s"), "真空光速 c（m/s）"),
    "k_B": (1.380649e-23, _u("kg·m^2/(s^2·K)"), "玻尔兹曼常数 k_B（J/K）"),
}

# 函数元数据: (参数个数, 量纲类别)
#   same       —— 所有参数必须同量纲，结果保持量纲（min/max/abs/round...）
#   dimensionless —— 参数必须无量纲，结果无量纲（exp/ln/sin...）
#   sqrt       —— 特殊处理（允许量纲，指数须为偶数）
#   pow        —— 双参数特殊处理
#   single_keep—— 单参数，量纲保持（abs/round/floor/ceil）
FUNC_SPECS: Dict[str, Tuple[str, int, int]] = {
    # name: (kind, min_args, max_args)
    "sqrt": ("sqrt", 1, 1),
    "abs": ("same1", 1, 1),
    "round": ("same1", 1, 1),
    "floor": ("same1", 1, 1),
    "ceil": ("same1", 1, 1),
    "exp": ("dimensionless", 1, 1),
    "ln": ("dimensionless", 1, 1),
    "log10": ("dimensionless", 1, 1),
    "log2": ("dimensionless", 1, 1),
    "log": ("dimensionless", 1, 2),
    "sin": ("dimensionless", 1, 1),
    "cos": ("dimensionless", 1, 1),
    "tan": ("dimensionless", 1, 1),
    "min": ("same", 1, 8),
    "max": ("same", 1, 8),
    "pow": ("pow", 2, 2),
}


@dataclass
class Variable:
    value: float
    unit: Optional[UnitExpr]
    raw_value: str = ""
    raw_unit: str = ""

    def si_value(self) -> float:
        if self.unit is None:
            return self.value
        simple = self.unit.simple_def()
        if simple is not None and simple.offset != 0:
            return simple.to_si(self.value)
        return self.value * self.unit.factor


@dataclass
class Step:
    label: str
    expr: str
    value: Optional[float]
    unit: str
    dim: str
    span: Tuple[int, int]
    kind: str = "op"          # num/var/const/op/call


@dataclass
class Result:
    ok: bool
    value_si: Optional[float] = None
    display_value: Optional[float] = None
    unit_symbol: str = ""
    unit_name: str = ""
    dim_symbol: str = ""
    dim_name: str = ""
    steps: List[Step] = field(default_factory=list)
    errors: List[dict] = field(default_factory=list)
    conversions: List[dict] = field(default_factory=list)


class Evaluator:
    def __init__(self, text: str, variables: Dict[str, Variable]):
        self.text = text
        self.variables = variables
        self.steps: List[Step] = []
        self.errors: List[ValidateError] = []
        self.had_undef = False

    def fail(self, code: str, msg: str, span: Tuple[int, int]) -> R:
        self.errors.append(ValidateError(code, msg, span[0], span[1]))
        return R(0.0, Dimension.scalar(), None, span=span, undef=True)

    def eval_node(self, node: Node) -> R:
        if isinstance(node, NumberNode):
            return self._eval_number(node)
        if isinstance(node, VarNode):
            return self._eval_var(node)
        if isinstance(node, UnaryNode):
            return self._eval_unary(node)
        if isinstance(node, BinaryNode):
            return self._eval_binary(node)
        if isinstance(node, CallNode):
            return self._eval_call(node)
        raise TypeError(f"未知节点 {type(node)}")

    # ---------------------------------------------------------- 叶子
    def _eval_number(self, node: NumberNode) -> R:
        val = float(node.value)
        unit = node.unit
        if unit is None:
            r = R(val, Dimension.scalar(), None, span=node.span,
                  display_value=val)
        else:
            dim = unit.dim
            simple = unit.simple_def()
            if simple is not None and simple.offset != 0:
                si = simple.to_si(val)
                r = R(si, dim, unit, offset=simple.offset, span=node.span,
                      display_value=val)
            else:
                r = R(val * unit.factor, dim, unit, span=node.span,
                      display_value=val)
        self._record_leaf(node, r)
        return r

    def _eval_var(self, node: VarNode) -> R:
        name = node.name
        if name in CONSTANT_VALUES:
            cval, cunit, cdesc = CONSTANT_VALUES[name]
            cdim = cunit.dim if cunit is not None else Dimension.scalar()
            disp = cval / cunit.factor if cunit is not None else cval
            r = R(cval, cdim, cunit, span=node.span,
                  display_value=disp, desc=cdesc)
            self.steps.append(Step(
                "常量", name, disp,
                cunit.to_symbol() if cunit else "",
                cdim.to_name(), node.span, "const"))
            return r
        if name not in self.variables:
            self.had_undef = True
            self.steps.append(Step(
                "未定义变量", name, None, "", "？", node.span, "var"))
            from .dimensions import ALIASES
            low = name.lower()
            hint = ""
            if low in ALIASES:
                sym = UNITS[ALIASES[low]].symbol
                hint = (f"（“{name}” 是单位 {sym}；若要把它当作单位常量，"
                        "请写在数字之后，如 1 "
                        f"{sym}；若确为变量，请在变量表中定义）")
            return self.fail(
                "undef_var",
                f"未定义的变量 “{name}”，请在变量表中录入其数值与单位{hint}",
                node.span)
        var = self.variables[name]
        si = var.si_value()
        # 变量声明单位（权威），表达式中后缀单位仅做展示校验
        unit = var.unit
        simple = unit.simple_def() if unit else None
        offset = simple.offset if simple else 0.0
        r = R(si, var.unit.dim if unit else Dimension.scalar(), unit,
              offset=offset, span=node.span, display_value=var.value)
        # 表达式里给变量加了后缀单位时：仅允许同量纲，作显示单位提示
        if node.unit is not None:
            if not node.unit.dim.compatible_with(r.dim):
                return self.fail(
                    "dim_mismatch",
                    f"变量 “{name}” 的单位为 {unit.to_symbol() if unit else '无量纲'}"
                    f"（{r.dim.to_name()}），与后缀单位 {node.unit.to_symbol()} 量纲不一致",
                    node.span)
        self.steps.append(Step(
            "变量", name, var.value,
            unit.to_symbol() if unit else "",
            r.dim.to_name(), node.span, "var"))
        return r

    def _record_leaf(self, node: NumberNode, r: R):
        self.steps.append(Step(
            "数值", self.text[node.span[0]:node.span[1]],
            r.display_value,
            r.unit.to_symbol() if r.unit else "",
            r.dim.to_name(), node.span, "num"))

    # ---------------------------------------------------------- 运算
    def _eval_unary(self, node: UnaryNode) -> R:
        v = self.eval_node(node.operand)
        if v.undef:
            return self._propagate(v, node)
        if node.op == "-":
            r = R(-v.value, v.dim, v.unit, v.offset,
                  display_value=(-v.display_value if v.display_value is not None
                                 else None), span=node.span)
        else:
            r = R(v.value, v.dim, v.unit, v.offset,
                  display_value=v.display_value, span=node.span)
        self._record_op(node, r, [v])
        return r

    def _eval_binary(self, node: BinaryNode) -> R:
        a = self.eval_node(node.left)
        b = self.eval_node(node.right)
        if a.undef or b.undef:
            return self._propagate_pair(a, b, node)
        op = node.op

        if op in "+-":
            if not a.dim.compatible_with(b.dim):
                return self.fail(
                    "dim_mismatch",
                    f"{'相减' if op == '-' else '相加'}的两个量量纲不一致："
                    f"{a.dim.to_name()}（{a.dim.to_symbol()}）与 "
                    f"{b.dim.to_name()}（{b.dim.to_symbol()}）",
                    node.right.span)

            a_off = _simple_offset(a.unit)
            b_off = _simple_offset(b.unit)

            if op == "-":
                # 相减恒为“温差/差值”：SI 线性值之差。
                # 显示时沿用左侧温标/单位的 factor，但 offset 归零。
                si = a.value - b.value
                is_temp_diff = a_off is not None
                if a.unit is not None:
                    d0 = a.unit.simple_def()
                    if is_temp_diff:
                        disp = si / d0.factor
                    else:
                        disp = si / a.unit.factor
                    r = R(si, a.dim, a.unit, 0.0, span=node.span,
                          display_value=disp, difference=is_temp_diff)
                else:
                    r = R(si, a.dim, None, 0.0, span=node.span,
                          display_value=si, difference=False)
                self._record_op(node, r, [a, b])
                return r

            # 加法：两个带偏移的绝对温度相加无物理意义
            if a_off is not None and b_off is not None:
                return self.fail(
                    "dim_mismatch",
                    "两个带温标的温度（如 °C）不能直接相加；"
                    "如要叠加温差，请把温差以 K（或度）表示",
                    node.span)
            si = a.value + b.value
            # 绝对温度 + 温差：结果仍是绝对温度（用左值温标，含偏移）
            disp = None
            if a.unit is not None:
                disp = self._to_display(si, a)
            r = R(si, a.dim, a.unit, a.offset, span=node.span,
                  display_value=disp)
            self._record_op(node, r, [a, b])
            return r

        if op == "*":
            # 温度 offset 单位不能参与乘法
            off_bad = self._check_offset_mult(a, node.left.span)
            if off_bad:
                return off_bad
            off_bad = self._check_offset_mult(b, node.right.span)
            if off_bad:
                return off_bad
            si = a.value * b.value
            unit = self._combine_units(a, b, 1)
            r = R(si, a.dim * b.dim, unit, span=node.span,
                  display_value=si / unit.factor if unit else si)
            self._record_op(node, r, [a, b])
            return r

        if op == "/":
            off_bad = self._check_offset_mult(a, node.left.span)
            if off_bad:
                return off_bad
            off_bad = self._check_offset_mult(b, node.right.span)
            if off_bad:
                return off_bad
            if b.value == 0:
                return self.fail("domain", "除数为零", node.right.span)
            si = a.value / b.value
            unit = self._combine_units(a, b, -1)
            r = R(si, a.dim / b.dim, unit, span=node.span,
                  display_value=si / unit.factor if unit else si)
            self._record_op(node, r, [a, b])
            return r

        if op == "^":
            # 指数节点必须可推导为无量纲常数
            if not b.dim.is_dimensionless():
                return self.fail(
                    "bad_power",
                    "幂指数必须是无量纲数，但指数的量纲为 "
                    f"{b.dim.to_name()}（{b.dim.to_symbol()}）",
                    node.right.span)
            p = b.value
            # 量纲非 1 的底，只允许整数幂
            if not a.dim.is_dimensionless():
                pi = _as_integer(p)
                if pi is None:
                    return self.fail(
                        "bad_power",
                        f"非整指数 {_fmt(p)} 不能作用于带量纲的底"
                        f"（{a.dim.to_name()}）：量纲指数必须为整数，"
                        "请改用 sqrt 处理开方",
                        node.span)
                dim = a.dim ** pi
            else:
                dim = Dimension.scalar()
            try:
                si = math.pow(a.value, p)
            except (ValueError, OverflowError):
                return self.fail("domain",
                                 f"幂运算结果超出实数域（{_fmt(a.value)}"
                                 f"^{_fmt(p)}）", node.span)
            if math.isinf(si) or math.isnan(si):
                return self.fail("domain", "幂运算结果非有限值", node.span)
            unit = self._power_unit(a, p)
            r = R(si, dim, unit, span=node.span,
                  display_value=si / unit.factor if unit else si)
            self._record_op(node, r, [a, b])
            return r

        return self.fail("domain", f"不支持的运算符 {op}", node.span)

    # ---------------------------------------------------------- 函数
    def _eval_call(self, node: CallNode) -> R:
        name = node.name
        kind, amin, amax = FUNC_SPECS[name]
        if not (amin <= len(node.args) <= amax):
            want = (f"{amin}" if amin == amax else f"{amin}~{amax}")
            return self.fail(
                "syntax",
                f"函数 {name} 需要 {want} 个参数，但得到 {len(node.args)} 个",
                node.span)
        vals = [self.eval_node(a) for a in node.args]
        if any(v.undef for v in vals):
            return self._propagate(vals[0], node)

        def arg_span(i):
            return node.arg_spans[i] if i < len(node.arg_spans) else node.span

        if kind == "dimensionless":
            x = vals[0]
            if not x.dim.is_dimensionless():
                return self.fail(
                    "dim_mismatch",
                    f"函数 {name} 的参数必须是无量纲数，但得到"
                    f"{x.dim.to_name()}（{x.dim.to_symbol()}）",
                    arg_span(0))
            try:
                if name == "exp":
                    y = math.exp(x.value)
                elif name == "ln":
                    if x.value <= 0:
                        raise ValueError
                    y = math.log(x.value)
                elif name == "log10":
                    if x.value <= 0:
                        raise ValueError
                    y = math.log10(x.value)
                elif name == "log2":
                    if x.value <= 0:
                        raise ValueError
                    y = math.log2(x.value)
                elif name == "log":
                    base = vals[1].value if len(vals) == 2 else 10.0
                    if x.value <= 0 or base <= 0 or base == 1:
                        raise ValueError
                    y = math.log(x.value, base)
                else:  # sin/cos/tan
                    y = getattr(math, name)(x.value)
            except ValueError:
                return self.fail("domain",
                                 f"函数 {name} 的参数超出实数定义域",
                                 arg_span(0))
            r = R(y, Dimension.scalar(), None, span=node.span,
                  display_value=y)
            self._record_call(node, r, vals)
            return r

        if kind in ("same1", "same"):
            base = vals[0]
            for i, v in enumerate(vals[1:], start=1):
                if not v.dim.compatible_with(base.dim):
                    return self.fail(
                        "dim_mismatch",
                        f"函数 {name} 的各参数必须同量纲：参数 1 为 "
                        f"{base.dim.to_name()}，参数 {i + 1} 为 "
                        f"{v.dim.to_name()}",
                        arg_span(i))
            if kind == "same1":
                x = vals[0]
                if name == "abs":
                    y = abs(x.value)
                elif name == "round":
                    y = float(round(x.value))
                elif name == "floor":
                    y = math.floor(x.value)
                else:  # ceil
                    y = math.ceil(x.value)
                r = R(y, x.dim, x.unit, x.offset, span=node.span,
                      display_value=self._to_display(y, x) if x.unit else y)
            else:
                picked = vals[0]
                y = picked.value
                for v in vals[1:]:
                    if name == "min" and v.value < y:
                        picked, y = v, v.value
                    if name == "max" and v.value > y:
                        picked, y = v, v.value
                r = R(y, picked.dim, picked.unit, picked.offset,
                      span=node.span,
                      display_value=self._to_display(y, picked)
                      if picked.unit else y)
            self._record_call(node, r, vals)
            return r

        if kind == "sqrt":
            x = vals[0]
            # 量纲各指数必须是偶数
            for b, e in x.dim.exps.items():
                if e % 2 != 0:
                    return self.fail(
                        "bad_power",
                        f"sqrt 要求被开方量的量纲指数均为偶数，但 "
                        f"{x.dim.to_symbol()} 中 {b} 的指数为 "
                        f"{_frac_str(e)}",
                        arg_span(0))
            if x.value < 0:
                return self.fail("domain", "sqrt 的被开方数不能为负",
                                 arg_span(0))
            y = math.sqrt(x.value)
            dim = x.dim ** Fraction(1, 2)
            unit = self._power_unit(x, 0.5)
            r = R(y, dim, unit, span=node.span,
                  display_value=y / unit.factor if unit else y)
            self._record_call(node, r, vals)
            return r

        if kind == "pow":
            a, b = vals
            if not b.dim.is_dimensionless():
                return self.fail(
                    "bad_power",
                    "pow 的指数参数必须无量纲", arg_span(1))
            if not a.dim.is_dimensionless():
                pi = _as_integer(b.value)
                if pi is None:
                    return self.fail(
                        "bad_power",
                        f"非整指数 {_fmt(b.value)} 不能作用于带量纲的底",
                        node.span)
                dim = a.dim ** pi
            else:
                dim = Dimension.scalar()
            try:
                y = math.pow(a.value, b.value)
            except (ValueError, OverflowError):
                return self.fail("domain", "pow 结果超出实数域", node.span)
            unit = self._power_unit(a, b.value)
            r = R(y, dim, unit, span=node.span,
                  display_value=y / unit.factor if unit else y)
            self._record_call(node, r, vals)
            return r

        return self.fail("domain", f"未实现的函数 {name}", node.span)

    # ---------------------------------------------------------- 辅助
    def _check_offset_mult(self, v: R, span) -> Optional[R]:
        if v.unit is not None:
            simple = v.unit.simple_def()
            if simple is not None and simple.offset != 0:
                return self.fail(
                    "dim_mismatch",
                    f"温标单位 “{simple.symbol}” 含固定偏移，不能直接参与"
                    "乘除或幂运算（请先换算为 K）", span)
        return None

    def _combine_units(self, a: R, b: R, sign_b: int) -> Optional[UnitExpr]:
        if a.unit is None and b.unit is None:
            return None
        pieces: Dict[str, int] = {}
        order: List[str] = []
        for src, sgn in ((a, 1), (b, sign_b)):
            if src.unit is None:
                continue
            for p in src.unit.pieces:
                if p.key not in pieces:
                    pieces[p.key] = 0
                    order.append(p.key)
                pieces[p.key] += p.exp * sgn
        return UnitExpr(tuple(UnitPiece(k, pieces[k]) for k in order
                              if pieces[k] != 0))

    def _power_unit(self, a: R, p) -> Optional[UnitExpr]:
        if a.unit is None:
            return None
        pi = _as_integer(p)
        if pi is None:
            # 分数单位（如 sqrt(m^2)）退化为不显示复合单位
            return None
        return UnitExpr(tuple(UnitPiece(pc.key, pc.exp * pi)
                              for pc in a.unit.pieces if pc.exp * pi != 0))

    def _to_display(self, si: float, ref: R) -> Optional[float]:
        if ref.unit is None:
            return None
        simple = ref.unit.simple_def()
        # 差值语义（温差）时不应用温标偏移
        if simple is not None and simple.offset != 0 and not ref.difference:
            return simple.from_si(si)
        return si / ref.unit.factor

    def _record_op(self, node: Node, r: R, operands: List[R]):
        frag = self.text[node.span[0]:node.span[1]]
        self.steps.append(Step(
            "运算", frag, r.shown(),
            r.unit.to_symbol() if r.unit else "",
            r.dim.to_name(), node.span, "op"))

    def _record_call(self, node: CallNode, r: R, args: List[R]):
        self.steps.append(Step(
            "函数", self.text[node.span[0]:node.span[1]],
            r.shown(), r.unit.to_symbol() if r.unit else "",
            r.dim.to_name(), node.span, "call"))

    def _propagate(self, v: R, node: Node) -> R:
        return R(0.0, v.dim, v.unit, span=node.span, undef=True)

    def _propagate_pair(self, a: R, b: R, node: Node) -> R:
        dim = a.dim if not a.undef else b.dim
        return R(0.0, dim, None, span=node.span, undef=True)


def _simple_offset(unit: Optional[UnitExpr]):
    """返回简单 offset 单位的 offset 值，否则 None。"""
    if unit is None:
        return None
    d = unit.simple_def()
    return d.offset if d is not None and d.offset != 0 else None


def _as_integer(x: float) -> Optional[int]:
    if math.isclose(x, round(x), rel_tol=0, abs_tol=1e-9):
        return int(round(x))
    return None


def _frac_str(f) -> str:
    from fractions import Fraction as _F
    f = _F(f).limit_denominator(10**6)
    return str(f.numerator) if f.denominator == 1 else f"{f.numerator}/{f.denominator}"


def _fmt(x: float) -> str:
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:.6g}"


# ---------------------------------------------------------------- 对外入口

def parse_variable_unit(raw_unit: str) -> Optional[UnitExpr]:
    """解析变量值中填写的单位字符串（如 kg/m^3、mL、°C）。"""
    raw = raw_unit.strip()
    if not raw:
        return None
    expr, _fac, ok = _parse_unit_string(raw)
    if not ok:
        raise ParseError(f"无法识别的单位 “{raw_unit}”", 0, len(raw_unit))
    return expr


def _parse_unit_string(raw: str):
    from .parser import resolve_unit_phrase
    return resolve_unit_phrase(raw)


def conversions_for(dim: Dimension, si_value: float,
                    current: Optional[UnitExpr],
                    difference_mode: bool = False) -> List[dict]:
    """列出同量纲的常用单位换算结果。

    difference_mode=True 时按“温差”换算（不加减温标偏移）。
    """
    def to_local(d: UnitDef):
        if difference_mode and d.offset != 0:
            return si_value / d.factor
        return d.from_si(si_value)

    out = []
    seen = set()
    if current is not None and current.is_simple():
        key = current.pieces[0].key
        d = UNITS[key]
        out.append({
            "symbol": d.symbol, "name":
            ("温差·" + d.cn) if difference_mode and d.offset else d.cn,
            "value": _fmt_num(to_local(d)),
            "current": True,
        })
        seen.add(key)
    elif current is not None:
        out.append({
            "symbol": current.to_symbol(), "name": current.to_name(),
            "value": _fmt_num(si_value / current.factor),
            "current": True,
        })
    si_symbol, si_name = _canonical_si_unit(dim)
    if si_symbol:
        out.append({
            "symbol": si_symbol, "name": si_name,
            "value": _fmt_num(si_value), "current": current is None,
            "si": True,
        })
    for key, d in UNITS.items():
        if key in seen:
            continue
        if d.dim.compatible_with(dim):
            out.append({
                "symbol": d.symbol,
                "name": ("温差·" + d.cn) if difference_mode and d.offset
                        else d.cn,
                "value": _fmt_num(to_local(d)),
                "current": False,
            })
            seen.add(key)
    return out


def _canonical_si_unit(dim: Dimension) -> Tuple[str, str]:
    si_map = {"M": ("kg", "千克"), "L": ("m", "米"), "T": ("s", "秒"),
              "I": ("A", "安培"), "Θ": ("K", "开尔文"), "N": ("mol", "摩尔"),
              "J": ("cd", "坎德拉")}
    num, den, nname, dname = [], [], [], []
    for b, e in dim.exps.items():
        sym, nm = si_map[b]
        ei = int(e) if e.denominator == 1 else None
        if ei is None:
            return "", ""
        if ei > 0:
            num.append(sym if ei == 1 else f"{sym}^{ei}")
            nname.append(nm if ei == 1 else f"{nm}^{ei}")
        else:
            den.append(sym if ei == -1 else f"{sym}^{-ei}")
            dname.append(nm if ei == -1 else f"{nm}^{-ei}")
    sym = "·".join(num) if num else "1"
    nm = "·".join(nname) if nname else "一"
    if den:
        sym += "/" + "·".join(den)
        nm += "每" + "·".join(dname)
    return sym, nm


def _fmt_num(x: float) -> float:
    if x == 0:
        return 0.0
    ax = abs(x)
    if ax >= 1e-4 and ax < 1e10:
        return float(f"{x:.10g}")
    return float(f"{x:.6e}")


def validate_expression(text: str, variables: Dict[str, Variable]) -> Result:
    res = Result(ok=False)
    try:
        tree = parse(text)
    except ParseError as e:
        end = e.end if e.end > e.start else min(len(text), e.start + 1)
        res.errors = [{
            "code": "syntax", "message": e.message,
            "start": e.start, "end": end,
        }]
        return res

    ev = Evaluator(text, variables)
    root = ev.eval_node(tree)
    res.steps = ev.steps
    if ev.errors:
        res.errors = [{
            "code": e.code, "message": e.message,
            "start": e.start, "end": e.end,
        } for e in ev.errors]
        return res

    res.ok = True
    res.value_si = _fmt_num(root.value)
    # 显示单位优选：
    # 1) 表达式自带的复合单位若与某个具名导出单位等价（如 km/h），优先该具名单位；
    # 2) 复合单位 factor 偏离 1 且无具名等价物时（如 atm·L 对能量），
    #    退回到最贴近 SI 的具名单位或规范 SI 组合。
    disp_unit = root.unit
    disp_value = root.shown()
    if disp_unit is not None and not disp_unit.is_simple():
        named_equiv = _named_unit_equivalent(disp_unit)
        if named_equiv is not None:
            nd = UNITS[named_equiv]
            disp_unit = UnitExpr((UnitPiece(named_equiv, 1),))
            disp_value = nd.from_si(root.value)
        else:
            import math as _m
            if not _m.isclose(disp_unit.factor, 1.0, rel_tol=1e-9,
                              abs_tol=1e-12):
                cand = _preferred_named_unit(root.dim)
                if cand is not None:
                    disp_unit = UnitExpr((UnitPiece(cand, 1),))
                    disp_value = UNITS[cand].from_si(root.value)
                else:
                    disp_unit = None
                    disp_value = root.value
    if disp_unit is not None:
        res.display_value = _fmt_num(disp_value)
        res.unit_symbol = disp_unit.to_symbol()
        res.unit_name = disp_unit.to_name()
    else:
        res.display_value = _fmt_num(root.value)
        res.unit_symbol = ""
        res.unit_name = "无量纲" if root.dim.is_dimensionless() else \
            _canonical_si_unit(root.dim)[1]
    res.dim_symbol = root.dim.to_symbol()
    res.dim_name = root.dim.to_name()
    res.conversions = conversions_for(
        root.dim, root.value, disp_unit, difference_mode=root.difference)
    return res


def _named_unit_equivalent(unit: UnitExpr) -> Optional[str]:
    """找一个与给定复合单位 factor 相同的具名单位（如 km/h）。"""
    import math as _m
    f = unit.factor
    for key, d in UNITS.items():
        if d.offset != 0 or not d.dim.compatible_with(unit.dim):
            continue
        if _m.isclose(d.factor, f, rel_tol=1e-12, abs_tol=1e-15) \
                and (d.factor != 1.0 or
                     # factor==1 时只接受真正的“非 SI 基本组合”具名单位，
                     # 避免 km/h(≠1) 之外的意外回退
                     key in ("newton", "joule", "watt", "pascal", "hertz",
                             "coulomb", "volt", "ohm", "farad", "mole_per_liter")):
            return key
    return None


def _preferred_named_unit(dim: Dimension) -> Optional[str]:
    """在同量纲具名单位中选 factor 最接近 1 的（即最贴近 SI 基准）。"""
    best = None
    best_gap = float("inf")
    for key, d in UNITS.items():
        if d.offset != 0:
            continue
        if d.dim.compatible_with(dim):
            import math as _m
            gap = abs(_m.log10(abs(d.factor))) if d.factor > 0 else 1e9
            if gap < best_gap - 1e-12:
                best_gap, best = gap, key
    return best
