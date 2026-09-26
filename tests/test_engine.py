"""量纲引擎单元测试。"""
import math

import pytest

from app.engine import analyze


def ok(expr, variables=None, target=None):
    res = analyze(expr, variables or {}, target)
    assert res["ok"], res["errors"]
    assert res["result"] is not None
    return res["result"]


def fail(expr, variables=None, target=None):
    res = analyze(expr, variables or {}, target)
    assert not res["ok"]
    assert res["errors"], "应当返回错误"
    return res["errors"]


# ---------------- 基本运算与量纲推导 ----------------

def test_simple_addition_same_dim():
    r = ok("1 m + 2 m")
    assert r["si_value"] == pytest.approx(3.0)
    assert r["dimension_str"] == "L"
    assert r["si_unit"] == "m"


def test_unit_conversion_in_addition():
    r = ok("1 km + 2 m")
    assert r["si_value"] == pytest.approx(1002.0)
    r = ok("1 h + 30 min")
    assert r["si_value"] == pytest.approx(5400.0)
    assert r["si_unit"] == "s"


def test_acceleration_expression():
    r = ok("9.8 m/s^2")
    assert r["si_value"] == pytest.approx(9.8)
    assert r["dimension_str"] == "L·T^-2"
    assert r["si_unit"] == "m·s^-2"


def test_newton_derived():
    r = ok("1 kg*m/s^2")
    assert r["dimension_str"] == "L·M·T^-2"
    assert "N" in r["derived"]


def test_energy_with_variables():
    r = ok("0.5*mass*v^2 + mass*g0*h0", {"mass": "2 kg", "v": "10 m/s", "h0": "5 m"})
    # 0.5*2*100 + 2*9.80665*5 = 100 + 98.0665
    assert r["si_value"] == pytest.approx(198.0665)
    assert r["dimension_str"] == "L^2·M·T^-2"
    assert "J" in r["derived"]


def test_power_precedence_and_associativity():
    assert ok("2^3^2")["si_value"] == pytest.approx(512.0)   # 右结合
    assert ok("-2^2")["si_value"] == pytest.approx(-4.0)     # 一元负号优先级低于 ^
    assert ok("2^-2")["si_value"] == pytest.approx(0.25)
    assert ok("(2^3)^2")["si_value"] == pytest.approx(64.0)


def test_power_dimension_scaling():
    r = ok("(4 m^2)^0.5")
    assert r["si_value"] == pytest.approx(2.0)
    assert r["dimension_str"] == "L"
    r = ok("(1 m)^3")
    assert r["dimension_str"] == "L^3"


def test_sqrt_and_functions():
    assert ok("sqrt(4 m^2)")["si_value"] == pytest.approx(2.0)
    assert ok("sqrt(9 m^2/s^2)")["si_unit"] == "m·s^-1"
    assert ok("sin(30 deg)")["si_value"] == pytest.approx(0.5)
    assert ok("cos(pi)")["si_value"] == pytest.approx(-1.0)
    assert ok("log(100)")["si_value"] == pytest.approx(2.0)
    assert ok("ln(e)")["si_value"] == pytest.approx(1.0)
    assert ok("abs(-3 m)")["si_value"] == pytest.approx(3.0)


def test_implicit_multiplication_and_unicode():
    assert ok("2(3+4)")["si_value"] == pytest.approx(14.0)
    assert ok("2π r", {"r": "3 m"})["si_value"] == pytest.approx(2 * math.pi * 3)
    assert ok("5 m²")["dimension_str"] == "L^2"
    assert ok("5 m²")["si_value"] == pytest.approx(5.0)
    assert ok("2×3")["si_value"] == pytest.approx(6.0)
    assert ok("6÷2")["si_value"] == pytest.approx(3.0)
    assert ok("1 kg·m/s²")["dimension_str"] == "L·M·T^-2"
    assert ok("10 m⁻¹")["dimension_str"] == "L^-1"


def test_constants():
    assert ok("c")["si_value"] == pytest.approx(299792458.0)
    assert ok("c")["dimension_str"] == "L·T^-1"
    assert ok("kb * 300 K")["dimension_str"] == "L^2·M·T^-2"


def test_dimensionless_and_percent():
    r = ok("50%")
    assert r["si_value"] == pytest.approx(0.5)
    assert r["dimension_str"] == "无量纲"


# ---------------- 错误定位 ----------------

def test_dim_mismatch_points_to_right_operand():
    errs = fail("1 m + 1 s")
    e = errs[0]
    assert e["kind"] == "dim_mismatch"
    assert e["source"] == "expression"
    assert "1 m + 1 s"[e["start"]:e["end"]] == "1 s"
    assert "L" in e["message"] and "T" in e["message"]


def test_dim_mismatch_in_subtraction_with_units():
    errs = fail("3 kg - 2 m")
    assert errs[0]["kind"] == "dim_mismatch"
    assert "3 kg - 2 m"[errs[0]["start"]:errs[0]["end"]] == "2 m"


def test_bad_exponent_points_to_exponent():
    errs = fail("(1 m)^(1 s)")
    e = errs[0]
    assert e["kind"] == "bad_exponent"
    assert "(1 m)^(1 s)"[e["start"]:e["end"]] == "(1 s)"
    assert "无量纲" in e["message"]


def test_bad_exponent_via_variable():
    errs = fail("2^t", {"t": "3 s"})
    assert any(e["kind"] == "bad_exponent" for e in errs)


def test_undefined_variable_span():
    errs = fail("foo + 1")
    e = errs[0]
    assert e["kind"] == "undefined"
    assert "foo + 1"[e["start"]:e["end"]] == "foo"
    assert "foo" in e["message"]


def test_undefined_inside_variable_definition():
    errs = fail("a * 2", {"a": "zz"})
    kinds = {e["kind"] for e in errs}
    assert "undefined" in kinds
    var_err = next(e for e in errs if e["source"] == "var:a")
    assert "zz"[var_err["start"]:var_err["end"]] == "zz"


def test_variable_cycle_detected():
    errs = fail("a", {"a": "b", "b": "a"})
    assert any(e["kind"] == "var_cycle" for e in errs)


def test_trig_requires_dimensionless():
    errs = fail("sin(1 m)")
    e = errs[0]
    assert e["kind"] == "dimless_arg"
    assert "sin(1 m)"[e["start"]:e["end"]] == "1 m"


def test_division_by_zero():
    errs = fail("1 / 0")
    assert errs[0]["kind"] == "value"


def test_syntax_error_span():
    errs = fail("1 + * 2")
    assert errs[0]["kind"] == "syntax"


def test_empty_expression():
    errs = fail("")
    assert errs[0]["kind"] == "syntax"


def test_function_arity():
    errs = fail("sqrt(1, 2)")
    assert errs[0]["kind"] == "arity"


# ---------------- 目标单位换算 ----------------

def test_target_unit_conversion():
    r = ok("10 m/s", target="km/h")
    assert r["target"]["value"] == pytest.approx(36.0)
    assert r["target"]["unit"] == "km/h"


def test_target_unit_energy():
    r = ok("0.5*mass*v^2", {"mass": "2 kg", "v": "10 m/s"}, "kJ")
    assert r["target"]["value"] == pytest.approx(0.1)


def test_target_unit_dim_mismatch():
    errs = fail("10 m/s", target="kg")
    e = errs[0]
    assert e["kind"] == "target_dim"
    assert e["source"] == "target"


def test_target_unit_unknown():
    errs = fail("10 m/s", target="furlong")
    assert errs[0]["source"] == "target"
    assert errs[0]["kind"] == "undefined"


# ---------------- 变量进阶 ----------------

def test_variables_can_reference_each_other():
    r = ok("F / A", {
        "mass": "80 kg",
        "F": "mass * g0",
        "A": "0.05 m^2",
    })
    assert r["dimension_str"] == "L^-1·M·T^-2"
    assert "Pa" in r["derived"]
    assert r["si_value"] == pytest.approx(80 * 9.80665 / 0.05)


def test_variable_shadows_unit_with_warning():
    # 用户变量优先于同名单位，并返回遮蔽警告
    res = analyze("min + 1", {"min": "2"})
    assert res["ok"]
    assert res["result"]["si_value"] == pytest.approx(3.0)
    assert any(w["name"] == "min" and w["kind"] == "shadow_unit" for w in res["warnings"])


def test_fractional_dimension_via_sqrt():
    r = ok("sqrt(2 m)")
    assert r["dimension"] == ["1/2", "0", "0", "0", "0", "0", "0"]
