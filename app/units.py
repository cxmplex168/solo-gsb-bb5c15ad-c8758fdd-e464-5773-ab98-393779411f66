"""单位、常量与函数注册表，以及量纲（dimension）的表示与格式化。

量纲用 7 元组表示，顺序为国际单位制七个基本量：
    L  长度        M  质量        T  时间        I  电流
    Θ  热力学温度  N  物质的量    J  发光强度
每个分量是 fractions.Fraction，允许出现分数次幂（如 sqrt 的结果）。
"""
from __future__ import annotations

from fractions import Fraction

DIM_NAMES = ["L", "M", "T", "I", "Θ", "N", "J"]
DIM_LABELS = {
    "L": "长度", "M": "质量", "T": "时间", "I": "电流",
    "Θ": "温度", "N": "物质的量", "J": "发光强度",
}
SI_SYMBOLS = ["m", "kg", "s", "A", "K", "mol", "cd"]

_IDX = {"L": 0, "M": 1, "T": 2, "I": 3, "Theta": 4, "N": 5, "J": 6}


def dim(**kw) -> tuple:
    """构造量纲向量，例如 dim(L=1, T=-2)。温度用 Theta 关键字。"""
    v = [Fraction(0)] * 7
    for key, val in kw.items():
        v[_IDX[key]] = Fraction(val)
    return tuple(v)


DIMLESS = dim()

# ---------------------------------------------------------------------------
# 单位表：名称 -> (量纲, 换算到 SI 的因子, 分类, 说明)
# ---------------------------------------------------------------------------
UNITS: dict[str, tuple] = {}


def _u(names: str, d: tuple, factor: float, cat: str, desc: str) -> None:
    for n in names.split("|"):
        UNITS[n] = (d, float(factor), cat, desc)


# 基本单位
_u("m", dim(L=1), 1, "基本单位", "米（长度）")
_u("kg", dim(M=1), 1, "基本单位", "千克（质量）")
_u("s", dim(T=1), 1, "基本单位", "秒（时间）")
_u("A", dim(I=1), 1, "基本单位", "安培（电流）")
_u("K", dim(Theta=1), 1, "基本单位", "开尔文（温度）")
_u("mol", dim(N=1), 1, "基本单位", "摩尔（物质的量）")
_u("cd", dim(J=1), 1, "基本单位", "坎德拉（发光强度）")

# 长度
_u("km", dim(L=1), 1e3, "长度", "千米")
_u("dm", dim(L=1), 1e-1, "长度", "分米")
_u("cm", dim(L=1), 1e-2, "长度", "厘米")
_u("mm", dim(L=1), 1e-3, "长度", "毫米")
_u("um|µm|μm", dim(L=1), 1e-6, "长度", "微米")
_u("nm", dim(L=1), 1e-9, "长度", "纳米")
_u("pm", dim(L=1), 1e-12, "长度", "皮米")
_u("ang|Å", dim(L=1), 1e-10, "长度", "埃")
_u("in|inch", dim(L=1), 0.0254, "长度", "英寸")
_u("ft", dim(L=1), 0.3048, "长度", "英尺")
_u("yd", dim(L=1), 0.9144, "长度", "码")
_u("mi|mile", dim(L=1), 1609.344, "长度", "英里")
_u("nmi", dim(L=1), 1852.0, "长度", "海里")
_u("AU", dim(L=1), 1.495978707e11, "长度", "天文单位")
_u("ly", dim(L=1), 9.4607304725808e15, "长度", "光年")
_u("pc", dim(L=1), 3.0856775814913673e16, "长度", "秒差距")

# 质量
_u("g", dim(M=1), 1e-3, "质量", "克")
_u("mg", dim(M=1), 1e-6, "质量", "毫克")
_u("ug|µg|μg", dim(M=1), 1e-9, "质量", "微克")
_u("t|tonne", dim(M=1), 1e3, "质量", "吨")
_u("lb", dim(M=1), 0.45359237, "质量", "磅")
_u("oz", dim(M=1), 0.028349523125, "质量", "盎司")
_u("u|Da", dim(M=1), 1.66053906660e-27, "质量", "原子质量单位")

# 时间
_u("ms", dim(T=1), 1e-3, "时间", "毫秒")
_u("us|µs|μs", dim(T=1), 1e-6, "时间", "微秒")
_u("ns", dim(T=1), 1e-9, "时间", "纳秒")
_u("ps", dim(T=1), 1e-12, "时间", "皮秒")
_u("min", dim(T=1), 60, "时间", "分钟")
_u("h|hr", dim(T=1), 3600, "时间", "小时")
_u("d|day", dim(T=1), 86400, "时间", "天")
_u("week", dim(T=1), 604800, "时间", "周")
_u("yr", dim(T=1), 365.25 * 86400, "时间", "年（365.25 天）")

# 电流 / 温度 / 物质的量
_u("mA", dim(I=1), 1e-3, "电磁学", "毫安")
_u("uA|µA|μA", dim(I=1), 1e-6, "电磁学", "微安")
_u("kA", dim(I=1), 1e3, "电磁学", "千安")
_u("mK", dim(Theta=1), 1e-3, "热学", "毫开尔文")
_u("mmol", dim(N=1), 1e-3, "化学", "毫摩尔")
_u("umol|µmol", dim(N=1), 1e-6, "化学", "微摩尔")
_u("kmol", dim(N=1), 1e3, "化学", "千摩尔")

# 角度与无量纲
_u("rad", DIMLESS, 1, "角度/无量纲", "弧度")
_u("mrad", DIMLESS, 1e-3, "角度/无量纲", "毫弧度")
_u("deg|°", DIMLESS, 3.141592653589793 / 180, "角度/无量纲", "度")
_u("arcmin", DIMLESS, 3.141592653589793 / 10800, "角度/无量纲", "角分")
_u("arcsec", DIMLESS, 3.141592653589793 / 648000, "角度/无量纲", "角秒")
_u("rev", DIMLESS, 2 * 3.141592653589793, "角度/无量纲", "转")
_u("sr", DIMLESS, 1, "角度/无量纲", "球面度")
_u("%", DIMLESS, 0.01, "角度/无量纲", "百分数")
_u("ppm", DIMLESS, 1e-6, "角度/无量纲", "百万分之一")
_u("ppb", DIMLESS, 1e-9, "角度/无量纲", "十亿分之一")

# 体积
_u("L|l", dim(L=3), 1e-3, "体积", "升")
_u("dL", dim(L=3), 1e-4, "体积", "分升")
_u("mL|ml", dim(L=3), 1e-6, "体积", "毫升")
_u("uL|µL|μL", dim(L=3), 1e-9, "体积", "微升")

# 力学导出单位
_u("N", dim(L=1, M=1, T=-2), 1, "导出单位", "牛顿（力）")
_u("kN", dim(L=1, M=1, T=-2), 1e3, "力学", "千牛")
_u("mN", dim(L=1, M=1, T=-2), 1e-3, "力学", "毫牛")
_u("dyn", dim(L=1, M=1, T=-2), 1e-5, "力学", "达因")
_u("kgf", dim(L=1, M=1, T=-2), 9.80665, "力学", "千克力")
_u("lbf", dim(L=1, M=1, T=-2), 4.4482216152605, "力学", "磅力")
_u("Pa", dim(L=-1, M=1, T=-2), 1, "导出单位", "帕斯卡（压强）")
_u("hPa", dim(L=-1, M=1, T=-2), 1e2, "压强", "百帕")
_u("kPa", dim(L=-1, M=1, T=-2), 1e3, "压强", "千帕")
_u("MPa", dim(L=-1, M=1, T=-2), 1e6, "压强", "兆帕")
_u("GPa", dim(L=-1, M=1, T=-2), 1e9, "压强", "吉帕")
_u("bar", dim(L=-1, M=1, T=-2), 1e5, "压强", "巴")
_u("mbar", dim(L=-1, M=1, T=-2), 1e2, "压强", "毫巴")
_u("atm", dim(L=-1, M=1, T=-2), 101325, "压强", "标准大气压")
_u("mmHg", dim(L=-1, M=1, T=-2), 133.322387415, "压强", "毫米汞柱")
_u("torr", dim(L=-1, M=1, T=-2), 133.32236842105263, "压强", "托")
_u("psi", dim(L=-1, M=1, T=-2), 6894.757293168, "压强", "磅每平方英寸")
_u("Hz", dim(T=-1), 1, "导出单位", "赫兹（频率）")
_u("kHz", dim(T=-1), 1e3, "频率", "千赫")
_u("MHz", dim(T=-1), 1e6, "频率", "兆赫")
_u("GHz", dim(T=-1), 1e9, "频率", "吉赫")
_u("rpm", dim(T=-1), 1 / 60, "频率", "转每分钟")
_u("kn|knot", dim(L=1, T=-1), 1852 / 3600, "力学", "节（速度）")

# 能量与功率
_u("J", dim(L=2, M=1, T=-2), 1, "导出单位", "焦耳（能量）")
_u("kJ", dim(L=2, M=1, T=-2), 1e3, "能量", "千焦")
_u("MJ", dim(L=2, M=1, T=-2), 1e6, "能量", "兆焦")
_u("GJ", dim(L=2, M=1, T=-2), 1e9, "能量", "吉焦")
_u("mJ", dim(L=2, M=1, T=-2), 1e-3, "能量", "毫焦")
_u("eV", dim(L=2, M=1, T=-2), 1.602176634e-19, "能量", "电子伏特")
_u("keV", dim(L=2, M=1, T=-2), 1.602176634e-16, "能量", "千电子伏特")
_u("MeV", dim(L=2, M=1, T=-2), 1.602176634e-13, "能量", "兆电子伏特")
_u("GeV", dim(L=2, M=1, T=-2), 1.602176634e-10, "能量", "吉电子伏特")
_u("cal", dim(L=2, M=1, T=-2), 4.184, "能量", "卡（热化学）")
_u("kcal", dim(L=2, M=1, T=-2), 4184, "能量", "千卡")
_u("Wh", dim(L=2, M=1, T=-2), 3600, "能量", "瓦时")
_u("kWh", dim(L=2, M=1, T=-2), 3.6e6, "能量", "千瓦时（度）")
_u("erg", dim(L=2, M=1, T=-2), 1e-7, "能量", "尔格")
_u("BTU", dim(L=2, M=1, T=-2), 1055.05585262, "能量", "英热单位")
_u("W", dim(L=2, M=1, T=-3), 1, "导出单位", "瓦特（功率）")
_u("mW", dim(L=2, M=1, T=-3), 1e-3, "功率", "毫瓦")
_u("kW", dim(L=2, M=1, T=-3), 1e3, "功率", "千瓦")
_u("MW", dim(L=2, M=1, T=-3), 1e6, "功率", "兆瓦")
_u("GW", dim(L=2, M=1, T=-3), 1e9, "功率", "吉瓦")
_u("hp", dim(L=2, M=1, T=-3), 745.6998715822702, "功率", "马力")

# 电磁学
_u("C", dim(T=1, I=1), 1, "导出单位", "库仑（电荷）")
_u("mC", dim(T=1, I=1), 1e-3, "电磁学", "毫库仑")
_u("uC|µC", dim(T=1, I=1), 1e-6, "电磁学", "微库仑")
_u("Ah", dim(T=1, I=1), 3600, "电磁学", "安时")
_u("mAh", dim(T=1, I=1), 3.6, "电磁学", "毫安时")
_u("V", dim(L=2, M=1, T=-3, I=-1), 1, "导出单位", "伏特（电压）")
_u("mV", dim(L=2, M=1, T=-3, I=-1), 1e-3, "电磁学", "毫伏")
_u("uV|µV", dim(L=2, M=1, T=-3, I=-1), 1e-6, "电磁学", "微伏")
_u("kV", dim(L=2, M=1, T=-3, I=-1), 1e3, "电磁学", "千伏")
_u("MV", dim(L=2, M=1, T=-3, I=-1), 1e6, "电磁学", "兆伏")
_u("Ω|ohm", dim(L=2, M=1, T=-3, I=-2), 1, "导出单位", "欧姆（电阻）")
_u("mΩ|mohm", dim(L=2, M=1, T=-3, I=-2), 1e-3, "电磁学", "毫欧")
_u("kΩ|kohm", dim(L=2, M=1, T=-3, I=-2), 1e3, "电磁学", "千欧")
_u("MΩ|Mohm", dim(L=2, M=1, T=-3, I=-2), 1e6, "电磁学", "兆欧")
_u("S", dim(L=-2, M=-1, T=3, I=2), 1, "导出单位", "西门子（电导）")
_u("mS", dim(L=-2, M=-1, T=3, I=2), 1e-3, "电磁学", "毫西门子")
_u("F", dim(L=-2, M=-1, T=4, I=2), 1, "导出单位", "法拉（电容）")
_u("mF", dim(L=-2, M=-1, T=4, I=2), 1e-3, "电磁学", "毫法")
_u("uF|µF|μF", dim(L=-2, M=-1, T=4, I=2), 1e-6, "电磁学", "微法")
_u("nF", dim(L=-2, M=-1, T=4, I=2), 1e-9, "电磁学", "纳法")
_u("pF", dim(L=-2, M=-1, T=4, I=2), 1e-12, "电磁学", "皮法")
_u("H", dim(L=2, M=1, T=-2, I=-2), 1, "导出单位", "亨利（电感）")
_u("mH", dim(L=2, M=1, T=-2, I=-2), 1e-3, "电磁学", "毫亨")
_u("uH|µH", dim(L=2, M=1, T=-2, I=-2), 1e-6, "电磁学", "微亨")
_u("Wb", dim(L=2, M=1, T=-2, I=-1), 1, "导出单位", "韦伯（磁通量）")
_u("T", dim(M=1, T=-2, I=-1), 1, "导出单位", "特斯拉（磁感应强度）")
_u("mT", dim(M=1, T=-2, I=-1), 1e-3, "电磁学", "毫特斯拉")
_u("uT|µT", dim(M=1, T=-2, I=-1), 1e-6, "电磁学", "微特斯拉")
_u("Gs", dim(M=1, T=-2, I=-1), 1e-4, "电磁学", "高斯")

# 光学 / 放射 / 化学导出单位
_u("lm", dim(J=1), 1, "导出单位", "流明（光通量）")
_u("lx", dim(L=-2, J=1), 1, "导出单位", "勒克斯（照度）")
_u("Bq", dim(T=-1), 1, "导出单位", "贝可勒尔（放射性活度）")
_u("Gy", dim(L=2, T=-2), 1, "导出单位", "戈瑞（吸收剂量）")
_u("Sv", dim(L=2, T=-2), 1, "导出单位", "希沃特（当量剂量）")
_u("kat", dim(T=-1, N=1), 1, "导出单位", "卡塔尔（催化活性）")

# ---------------------------------------------------------------------------
# 常量：名称 -> (数值, 量纲, 说明)
# ---------------------------------------------------------------------------
CONSTANTS: dict[str, tuple] = {
    "pi": (3.141592653589793, DIMLESS, "圆周率 π"),
    "π": (3.141592653589793, DIMLESS, "圆周率 π"),
    "e": (2.718281828459045, DIMLESS, "自然常数 e"),
    "c": (299792458.0, dim(L=1, T=-1), "真空光速 (m/s)"),
    "g0": (9.80665, dim(L=1, T=-2), "标准重力加速度 (m/s²)"),
    "G": (6.67430e-11, dim(L=3, M=-1, T=-2), "万有引力常量"),
    "kb": (1.380649e-23, dim(L=2, M=1, T=-2, Theta=-1), "玻尔兹曼常量 (J/K)"),
    "NA": (6.02214076e23, dim(N=-1), "阿伏伽德罗常量 (1/mol)"),
    "R": (8.31446261815324, dim(L=2, M=1, T=-2, Theta=-1, N=-1), "气体常量 (J/(mol·K))"),
    "qe": (1.602176634e-19, dim(T=1, I=1), "元电荷 (C)"),
    "me": (9.1093837015e-31, dim(M=1), "电子质量 (kg)"),
    "eps0": (8.8541878128e-12, dim(L=-3, M=-1, T=4, I=2), "真空介电常数 (F/m)"),
    "mu0": (1.25663706212e-6, dim(L=1, M=1, T=-2, I=-2), "真空磁导率 (H/m)"),
}

# ---------------------------------------------------------------------------
# 函数表：名称 -> 元数据（求值逻辑在 engine 中实现）
# ---------------------------------------------------------------------------
FUNCTIONS: dict[str, dict] = {
    "sqrt": {"arity": 1, "desc": "平方根，量纲指数减半，如 sqrt(4 m^2) = 2 m"},
    "abs": {"arity": 1, "desc": "绝对值，量纲不变"},
    "sin": {"arity": 1, "dimless": True, "desc": "正弦（参数须无量纲，可用 deg）"},
    "cos": {"arity": 1, "dimless": True, "desc": "余弦（参数须无量纲）"},
    "tan": {"arity": 1, "dimless": True, "desc": "正切（参数须无量纲）"},
    "asin": {"arity": 1, "dimless": True, "desc": "反正弦（参数须无量纲）"},
    "acos": {"arity": 1, "dimless": True, "desc": "反余弦（参数须无量纲）"},
    "atan": {"arity": 1, "dimless": True, "desc": "反正切（参数须无量纲）"},
    "exp": {"arity": 1, "dimless": True, "desc": "自然指数（参数须无量纲）"},
    "ln": {"arity": 1, "dimless": True, "desc": "自然对数（参数须无量纲）"},
    "log": {"arity": 1, "dimless": True, "desc": "常用对数 log10（参数须无量纲）"},
    "log2": {"arity": 1, "dimless": True, "desc": "以 2 为底的对数（参数须无量纲）"},
}

# 用于“等价导出单位”提示：所有换算因子为 1 的导出单位
_DERIVED = sorted(
    (name, entry[0]) for name, entry in UNITS.items()
    if entry[2] == "导出单位" and entry[1] == 1.0 and entry[0] != DIMLESS
)


def format_fraction(fr: Fraction) -> str:
    if fr.denominator == 1:
        return str(fr.numerator)
    return f"{fr.numerator}/{fr.denominator}"


def dim_str(d: tuple) -> str:
    """量纲符号串，如 L·M·T^-2；无量纲返回 '无量纲'。"""
    parts = []
    for name, e in zip(DIM_NAMES, d):
        if e == 0:
            continue
        parts.append(name if e == 1 else f"{name}^{format_fraction(e)}")
    return "·".join(parts) if parts else "无量纲"


def si_unit_str(d: tuple) -> str:
    """量纲对应的 SI 基本单位串，如 kg·m·s^-2。"""
    parts = []
    for sym, e in zip(SI_SYMBOLS, d):
        if e == 0:
            continue
        parts.append(sym if e == 1 else f"{sym}^{format_fraction(e)}")
    return "·".join(parts) if parts else "1"


def derived_matches(d: tuple) -> list[str]:
    """与该量纲等价的导出单位名称列表（如 [N]、[J]）。"""
    return [name for name, dd in _DERIVED if dd == d]


def catalog() -> dict:
    """供前端帮助面板使用的单位/常量/函数目录。"""
    units = [
        {"name": n, "dimension": dim_str(e[0]), "factor": e[1],
         "category": e[2], "description": e[3]}
        for n, e in sorted(UNITS.items(), key=lambda kv: (kv[1][2], kv[0]))
    ]
    constants = [
        {"name": n, "value": v, "dimension": dim_str(d), "description": desc}
        for n, (v, d, desc) in CONSTANTS.items()
    ]
    functions = [
        {"name": n, "arity": m["arity"], "description": m["desc"]}
        for n, m in FUNCTIONS.items()
    ]
    return {
        "dim_names": DIM_NAMES,
        "dim_labels": DIM_LABELS,
        "units": units,
        "constants": constants,
        "functions": functions,
    }
