"""量纲与单位的核心定义。

量纲采用 7 个 SI 基本量纲上的稀疏指数向量（Fraction 精确表示）:
    M 质量 / L 长度 / T 时间 / I 电流 / Θ 温度 / N 物质的量 / J 发光强度

单位用 UnitDef 描述: 到 SI 基准的线性换算 y = factor * x + offset。
UnitExpr 表示由单位符号的幂积组成的复合单位（如 kg*m/s^2）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Dict, Optional, Tuple

# ---------------------------------------------------------------- 量纲

BASE_DIMS = ["M", "L", "T", "I", "Θ", "N", "J"]
BASE_NAMES = {
    "M": "质量", "L": "长度", "T": "时间", "I": "电流",
    "Θ": "温度", "N": "物质的量", "J": "发光强度",
}
# 常见导出量纲的中文名 (M,L,T,I,Θ,N,J)
DERIVED_NAMES: Dict[Tuple[int, ...], str] = {
    (0, 2, 0, 0, 0, 0, 0): "面积",
    (0, 3, 0, 0, 0, 0, 0): "体积",
    (0, 1, -1, 0, 0, 0, 0): "速度",
    (0, 1, -2, 0, 0, 0, 0): "加速度",
    (0, 0, -1, 0, 0, 0, 0): "频率",
    (0, 0, -2, 0, 0, 0, 0): "频率变化率",
    (1, 1, -2, 0, 0, 0, 0): "力",
    (1, 2, -2, 0, 0, 0, 0): "能量/功/热量",
    (1, 2, -3, 0, 0, 0, 0): "功率",
    (-1, 1, -2, 0, 0, 0, 0): "压强/应力",
    (0, -1, 0, 1, 0, 0, 0): "电场强度",
    (0, 0, 1, 1, 0, 0, 0): "电荷量",
    (1, 2, -3, -1, 0, 0, 0): "电压/电势",
    (1, 2, -3, -2, 0, 0, 0): "电阻",
    (-1, -2, 4, 2, 0, 0, 0): "电容",
    (1, 2, -2, -2, 0, 0, 0): "电感",
    (1, 2, -3, 0, 0, 0, 0): "磁通量",
    (0, 0, -1, -1, 0, 0, 0): "磁场强度",
    (1, 0, -2, -1, 0, 0, 0): "磁感应强度",
    (-1, 3, 0, 0, 0, -1, 0): "摩尔浓度",
    (1, -3, 0, 0, 0, 0, 0): "密度",
    (1, 2, -2, 0, -1, -1, 0): "摩尔能量",
    (1, 1, -2, 0, 0, -1, 0): "摩尔力",
    (0, 2, -2, 0, -1, -1, 0): "比热（质量基准以外）",
    (1, -1, -2, 0, 0, 0, 0): "动力粘度",
    (0, 2, -1, 0, 0, 0, 0): "运动粘度",
    (1, 2, -2, 0, 0, -1, 0): "摩尔热力学能",
    (0, 0, 0, 0, 0, 0, 1): "发光强度",
    (0, 0, 0, 0, 0, 0, 0): "无量纲",
}


@dataclass(frozen=True)
class Dimension:
    """稀疏量纲向量，指数为 Fraction。空向量表示无量纲。"""
    exps: Dict[str, Fraction] = field(default_factory=dict)

    @staticmethod
    def scalar() -> "Dimension":
        return Dimension({})

    @staticmethod
    def of(**kw: int | Fraction) -> "Dimension":
        return Dimension({k: Fraction(v) for k, v in kw.items() if v})

    def is_dimensionless(self) -> bool:
        return not self.exps

    def __mul__(self, other: "Dimension") -> "Dimension":
        d = dict(self.exps)
        for k, v in other.exps.items():
            d[k] = d.get(k, Fraction(0)) + v
        return Dimension({k: v for k, v in d.items() if v != 0})

    def __truediv__(self, other: "Dimension") -> "Dimension":
        d = dict(self.exps)
        for k, v in other.exps.items():
            d[k] = d.get(k, Fraction(0)) - v
        return Dimension({k: v for k, v in d.items() if v != 0})

    def __pow__(self, p: Fraction | int) -> "Dimension":
        p = Fraction(p)
        return Dimension({k: v * p for k, v in self.exps.items() if v * p != 0})

    def compatible_with(self, other: "Dimension") -> bool:
        return self.exps == other.exps

    def signature(self) -> Tuple[int, ...]:
        return tuple(int(self.exps.get(b, 0)) for b in BASE_DIMS)

    def to_symbol(self) -> str:
        """量纲的规范符号，如 M*L*T^-2；无量纲返回 1。"""
        if not self.exps:
            return "1"
        parts = []
        for b in BASE_DIMS:
            e = self.exps.get(b)
            if e is None:
                continue
            parts.append(b if e == 1 else f"{b}^{_frac_str(e)}")
        return "·".join(parts)

    def to_name(self) -> str:
        """量纲的中文名称；无专名时回退到中文名积。"""
        sig = self.signature()
        # 只有全部指数为整数时才查导出量纲专名
        if all(f.denominator == 1 for f in self.exps.values()):
            name = DERIVED_NAMES.get(sig)
            if name:
                return name
        if not self.exps:
            return "无量纲"
        pos, neg = [], []
        for b in BASE_DIMS:
            e = self.exps.get(b)
            if e is None:
                continue
            if e > 0:
                pos.append(BASE_NAMES[b] if e == 1 else f"{BASE_NAMES[b]}^{_frac_str(e)}")
            else:
                neg.append(BASE_NAMES[b] if e == -1 else f"{BASE_NAMES[b]}^{_frac_str(-e)}")
        head = "·".join(pos) if pos else "1"
        if neg:
            return f"{head}/{'·'.join(neg)}"
        return head

    def to_json(self) -> Dict[str, int]:
        # Fraction 指数（如分数幂场景）转字符串会破坏 JSON，这里取整数；
        # 量纲推导阶段已保证非法分数幂被拒绝，合法路径指数均为整数。
        return {k: int(v) for k, v in self.exps.items()}


def _frac_str(f: Fraction) -> str:
    return str(f.numerator) if f.denominator == 1 else f"{f.numerator}/{f.denominator}"


# ---------------------------------------------------------------- 单位

@dataclass(frozen=True)
class UnitDef:
    """单位定义：value_si = factor * value_local + offset。"""
    name: str
    symbol: str
    dim: Dimension
    factor: float = 1.0
    offset: float = 0.0
    cn: str = ""

    def to_si(self, v: float) -> float:
        return v * self.factor + self.offset

    def from_si(self, v: float) -> float:
        return (v - self.offset) / self.factor


def _d(**kw) -> Dimension:
    return Dimension.of(**kw)


# (键名, 符号, 中文名, 量纲, factor, offset) —— factor 表示该单位折合多少 SI 基准单位
_RAW_UNITS = [
    # 质量 (kg)
    ("kilogram", "kg", "千克", _d(M=1), 1.0, 0.0),
    ("gram", "g", "克", _d(M=1), 1e-3, 0.0),
    ("milligram", "mg", "毫克", _d(M=1), 1e-6, 0.0),
    ("tonne", "t", "吨", _d(M=1), 1e3, 0.0),
    ("pound", "lb", "磅", _d(M=1), 0.45359237, 0.0),
    ("ounce", "oz", "盎司", _d(M=1), 0.028349523125, 0.0),
    ("jin", "jin", "斤", _d(M=1), 0.5, 0.0),
    # 长度 (m)
    ("meter", "m", "米", _d(L=1), 1.0, 0.0),
    ("centimeter", "cm", "厘米", _d(L=1), 0.01, 0.0),
    ("millimeter", "mm", "毫米", _d(L=1), 1e-3, 0.0),
    ("kilometer", "km", "千米", _d(L=1), 1e3, 0.0),
    ("micrometer", "um", "微米", _d(L=1), 1e-6, 0.0),
    ("inch", "in", "英寸", _d(L=1), 0.0254, 0.0),
    ("foot", "ft", "英尺", _d(L=1), 0.3048, 0.0),
    # 时间 (s)
    ("second", "s", "秒", _d(T=1), 1.0, 0.0),
    ("millisecond", "ms", "毫秒", _d(T=1), 1e-3, 0.0),
    ("minute", "min", "分钟", _d(T=1), 60.0, 0.0),
    ("hour", "h", "小时", _d(T=1), 3600.0, 0.0),
    ("day", "d", "天", _d(T=1), 86400.0, 0.0),
    # 电流 (A)
    ("ampere", "A", "安培", _d(I=1), 1.0, 0.0),
    ("milliampere", "mA", "毫安", _d(I=1), 1e-3, 0.0),
    # 温度 (K) —— offset 单位只能单独使用，不能参与幂积复合
    ("kelvin", "K", "开尔文", _d(Θ=1), 1.0, 0.0),
    ("celsius", "°C", "摄氏度", _d(Θ=1), 1.0, 273.15),
    ("fahrenheit", "°F", "华氏度", _d(Θ=1), 5.0 / 9.0, 459.67 * 5.0 / 9.0),    # 物质的量 (mol)
    ("mole", "mol", "摩尔", _d(N=1), 1.0, 0.0),
    ("millimole", "mmol", "毫摩尔", _d(N=1), 1e-3, 0.0),
    # 发光强度 (cd)
    ("candela", "cd", "坎德拉", _d(J=1), 1.0, 0.0),
    ("lumen", "lm", "流明", _d(J=1), 1.0, 0.0),
    # 面积/体积
    ("liter", "L", "升", _d(L=3), 1e-3, 0.0),
    ("milliliter", "mL", "毫升", _d(L=3), 1e-6, 0.0),
    ("cubic_meter", "m^3", "立方米", _d(L=3), 1.0, 0.0),
    ("gallon_us", "gal", "美制加仑", _d(L=3), 3.785411784e-3, 0.0),
    ("teaspoon", "tsp", "茶匙", _d(L=3), 5e-6, 0.0),
    ("tablespoon", "tbsp", "汤匙", _d(L=3), 15e-6, 0.0),
    ("cup_us", "cup", "杯", _d(L=3), 240e-6, 0.0),
    # 力学/能量/功率/压强
    ("newton", "N", "牛顿", _d(M=1, L=1, T=-2), 1.0, 0.0),
    ("joule", "J", "焦耳", _d(M=1, L=2, T=-2), 1.0, 0.0),
    ("kilojoule", "kJ", "千焦", _d(M=1, L=2, T=-2), 1e3, 0.0),
    ("calorie", "cal", "卡路里", _d(M=1, L=2, T=-2), 4.184, 0.0),
    ("kilocalorie", "kcal", "千卡", _d(M=1, L=2, T=-2), 4184.0, 0.0),
    ("watt", "W", "瓦特", _d(M=1, L=2, T=-3), 1.0, 0.0),
    ("kilowatt", "kW", "千瓦", _d(M=1, L=2, T=-3), 1e3, 0.0),
    ("pascal", "Pa", "帕斯卡", _d(M=1, L=-1, T=-2), 1.0, 0.0),
    ("kilopascal", "kPa", "千帕", _d(M=1, L=-1, T=-2), 1e3, 0.0),
    ("bar", "bar", "巴", _d(M=1, L=-1, T=-2), 1e5, 0.0),
    ("atmosphere", "atm", "标准大气压", _d(M=1, L=-1, T=-2), 101325.0, 0.0),
    ("psi", "psi", "磅力每平方英寸", _d(M=1, L=-1, T=-2), 6894.757293168, 0.0),
    # 频率
    ("hertz", "Hz", "赫兹", _d(T=-1), 1.0, 0.0),
    ("kilohertz", "kHz", "千赫", _d(T=-1), 1e3, 0.0),
    # 速度
    ("meter_per_second", "m/s", "米每秒", _d(L=1, T=-1), 1.0, 0.0),
    ("kilometer_per_hour", "km/h", "千米每小时", _d(L=1, T=-1),
     1000.0 / 3600.0, 0.0),
    ("mile_per_hour", "mph", "英里每小时", _d(L=1, T=-1),
     1609.344 / 3600.0, 0.0),
    # 电学
    ("coulomb", "C", "库仑", _d(I=1, T=1), 1.0, 0.0),
    ("volt", "V", "伏特", _d(M=1, L=2, T=-3, I=-1), 1.0, 0.0),
    ("ohm", "Ω", "欧姆", _d(M=1, L=2, T=-3, I=-2), 1.0, 0.0),
    ("farad", "F", "法拉", _d(M=-1, L=-2, T=4, I=2), 1.0, 0.0),
    # 浓度/密度
    ("mole_per_liter", "mol/L", "摩尔每升", _d(N=1, L=-3), 1000.0, 0.0),
    ("kilogram_per_m3", "kg/m^3", "千克每立方米", _d(M=1, L=-3), 1.0, 0.0),
    ("gram_per_liter", "g/L", "克每升", _d(M=1, L=-3), 1.0, 0.0),
    ("gram_per_mole", "g/mol", "克每摩尔", _d(M=1, N=-1), 1e-3, 0.0),
    ("kilogram_per_mole", "kg/mol", "千克每摩尔", _d(M=1, N=-1), 1.0, 0.0),
    # 功率衍生（烹饪常用）
    ("watt_hour", "Wh", "瓦时", _d(M=1, L=2, T=-2), 3600.0, 0.0),
    # 无量纲
    ("percent", "%", "百分数", Dimension.scalar(), 0.01, 0.0),
    ("one", "1", "一", Dimension.scalar(), 1.0, 0.0),
    ("mile", "mi", "英里", _d(L=1), 1609.344, 0.0),
]

UNITS: Dict[str, UnitDef] = {}
for _name, _sym, _cn, _dim, _fac, _off in _RAW_UNITS:
    UNITS[_name] = UnitDef(_name, _sym, _dim, _fac, _off, _cn)

# 别名 -> 单位键名（大小写敏感按符号习惯；解析时名称做小写匹配）
_ALIASES = {
    "kg": "kilogram", "g": "gram", "mg": "milligram", "ton": "tonne",
    "lbs": "pound", "poundmass": "pound", "oz": "ounce",
    "m": "meter",
    "cm": "centimeter", "mm": "millimeter", "km": "kilometer",
    "um": "micrometer", "μm": "micrometer",
    "inches": "inch", "ft": "foot", "feet": "foot",
    "s": "second", "sec": "second", "ms": "millisecond",
    "min": "minute", "h": "hour", "hr": "hour", "hour": "hour",
    "day": "day", "days": "day",
    "a": "ampere", "amp": "ampere", "ma": "milliampere",
    "k": "kelvin", "degc": "celsius", "c": "celsius",
    "℃": "celsius", "°c": "celsius",
    "degf": "fahrenheit", "℉": "fahrenheit", "°f": "fahrenheit",
    "mole": "mole", "mol": "mole", "mmol": "millimole",
    "cd": "candela", "lm": "lumen",
    "l": "liter", "liter": "liter", "litre": "liter",
    "ml": "milliliter", "gallon": "gallon_us", "gal": "gallon_us",
    "tsp": "teaspoon", "tbsp": "tablespoon", "cup": "cup_us",
    "n": "newton", "j": "joule", "kj": "kilojoule",
    "cal": "calorie", "kcal": "kilocalorie", "calorie": "calorie",
    "w": "watt", "kw": "kilowatt",
    "pa": "pascal", "kpa": "kilopascal", "bar": "bar", "atm": "atmosphere",
    "psi": "psi",
    "hz": "hertz", "khz": "kilohertz",
    "m/s": "meter_per_second", "km/h": "kilometer_per_hour",
    "mph": "mile_per_hour",
    "coulomb": "coulomb", "v": "volt", "volt": "volt",
    "ohm": "ohm", "ω": "ohm", "farad": "farad",
    "mol/l": "mole_per_liter", "molar": "mole_per_liter",
    "kg/m3": "kilogram_per_m3", "kg/m^3": "kilogram_per_m3",
    "g/l": "gram_per_liter",
    "g/mol": "gram_per_mole", "kg/mol": "kilogram_per_mole",
    "wh": "watt_hour",
    "%": "percent",
}

# 特殊复合别名（分子分母指数列表）: alias -> (unit pieces, factor)
# pieces: [(unit_key, exponent)]；factor 额外倍数
_COMPOUND_ALIASES = {
    "g/ml": ([("gram", 1), ("milliliter", -1)], 1.0),
    "mg/ml": ([("milligram", 1), ("milliliter", -1)], 1.0),
    "ng/ml": ([("milligram", 1), ("milliliter", -1)], 1e-3),
}

# 构建别名查找表（小写）
ALIASES: Dict[str, str] = {}
for a, key in _ALIASES.items():
    if key is not None:
        ALIASES[a.lower()] = key
# 单位正式名称自身也可按小写查到
for key in UNITS:
    ALIASES.setdefault(key.lower(), key)

# 复合别名表（去掉 None 占位）
COMPOUND_ALIASES: Dict[str, Tuple[list, float]] = {
    a: spec for a, spec in _COMPOUND_ALIASES.items() if spec is not None
}


# ---------------------------------------------------------------- 复合单位表达式

@dataclass(frozen=True)
class UnitPiece:
    """单位幂积中的一项：单位定义键 + 指数。"""
    key: str
    exp: int

    @property
    def defn(self) -> UnitDef:
        return UNITS[self.key]


@dataclass(frozen=True)
class UnitExpr:
    """复合单位（单位符号的幂积）。pieces 顺序即书写顺序。"""
    pieces: Tuple[UnitPiece, ...] = ()

    @property
    def dim(self) -> Dimension:
        d = Dimension.scalar()
        for p in self.pieces:
            d = d * (p.defn.dim ** p.exp)
        return d

    @property
    def factor(self) -> float:
        f = 1.0
        for p in self.pieces:
            f *= p.defn.factor ** p.exp
        return f

    def is_simple(self) -> bool:
        return len(self.pieces) == 1 and self.pieces[0].exp == 1

    def simple_def(self) -> Optional[UnitDef]:
        if self.is_simple():
            return self.pieces[0].defn
        return None

    def to_symbol(self) -> str:
        if not self.pieces:
            return ""
        num, den = [], []
        for p in self.pieces:
            sym = p.defn.symbol
            if p.exp == 1:
                num.append(sym)
            elif p.exp > 0:
                num.append(f"{sym}^{p.exp}")
            elif p.exp == -1:
                den.append(sym)
            else:
                den.append(f"{sym}^{-p.exp}")
        head = "·".join(num) if num else "1"
        if den:
            return f"{head}/{'·'.join(den)}"
        return head

    def to_name(self) -> str:
        if not self.pieces:
            return ""
        num, den = [], []
        for p in self.pieces:
            cn = p.defn.cn
            if p.exp == 1:
                num.append(cn)
            elif p.exp > 0:
                num.append(f"{cn}^{p.exp}")
            elif p.exp == -1:
                den.append(cn)
            else:
                den.append(f"{cn}^{-p.exp}")
        head = "·".join(num) if num else "一"
        if den:
            return f"{head}每{'·'.join(den)}"
        return head
