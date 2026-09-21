"""量纲校验台核心引擎测试（无需启动服务）。

运行: python -m pytest -q
   或: python tests/test_engine.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.parser import ParseError, parse, resolve_unit_phrase, tokenize
from app.validator import (
    Variable, parse_variable_unit, validate_expression,
)


def V(value, unit):
    return Variable(value,
                    parse_variable_unit(unit) if unit else None)


class TestUnitPhrases(unittest.TestCase):
    def test_simple_units(self):
        expr, _, ok = resolve_unit_phrase("kg")
        self.assertTrue(ok)
        self.assertEqual(expr.dim.to_symbol(), "M")

    def test_powered(self):
        expr, _, ok = resolve_unit_phrase("m^2")
        self.assertTrue(ok)
        self.assertEqual(expr.dim.to_symbol(), "L^2")

    def test_fraction(self):
        expr, _, ok = resolve_unit_phrase("kg/m^3")
        self.assertTrue(ok)
        self.assertEqual(expr.dim.to_symbol(), "M·L^-3")

    def test_dot_negative_exponents(self):
        expr, _, ok = resolve_unit_phrase("kg·m^-2·s^-2")
        self.assertTrue(ok)
        self.assertEqual(expr.dim.to_symbol(), "M·L^-2·T^-2")
        # 压强量纲 kg·m^-1·s^-2
        expr2, _, ok2 = resolve_unit_phrase("kg·m^-1·s^-2")
        self.assertTrue(ok2)
        self.assertEqual(expr2.dim.to_symbol(), "M·L^-1·T^-2")

    def test_parenthesized_denominator(self):
        expr, _, ok = resolve_unit_phrase("J/(mol·K)")
        self.assertTrue(ok)
        self.assertEqual(expr.dim.to_symbol(), "M·L^2·T^-2·Θ^-1·N^-1")

    def test_offset_only_alone(self):
        self.assertTrue(resolve_unit_phrase("°C")[2])
        self.assertFalse(resolve_unit_phrase("°C/s")[2])

    def test_trailing_operator_rejected(self):
        self.assertFalse(resolve_unit_phrase("J/")[2])

    def test_temperature_aliases(self):
        for s in ("°C", "℃", "°F", "℉"):
            self.assertTrue(resolve_unit_phrase(s)[2], s)


class TestTokenizer(unittest.TestCase):
    def kinds(self, text):
        return [(t.kind, t.value) for t in tokenize(text) if t.kind != "EOF"]

    def test_number_with_spaced_unit(self):
        self.assertEqual(self.kinds("25 °C")[0], ("NUM", "25"))
        self.assertEqual(self.kinds("25 °C")[1][0], "UNIT")

    def test_compound_after_number(self):
        self.assertEqual(self.kinds("9.8 m/s^2")[1],
                         ("UNIT", "m/s^2"))

    def test_spaced_slash_is_expression(self):
        toks = self.kinds("100 km / 2 h")
        self.assertIn(("OP", "/"), toks)
        self.assertEqual([t for t in toks if t[0] == "UNIT"],
                         [("UNIT", "km"), ("UNIT", "h")])

    def test_variables_after_star_stay_names(self):
        toks = self.kinds("rho*V")
        self.assertIn(("NAME", "V"), toks)
        self.assertIn(("NAME", "rho"), toks)

    def test_bare_compound_unit_at_start(self):
        self.assertEqual(self.kinds("m/s^2"), [("UNIT", "m/s^2")])


class TestParser(unittest.TestCase):
    def test_power_right_assoc(self):
        tree = parse("2^3^2")
        # 2 ^ (3 ^ 2)
        from app.parser import BinaryNode
        self.assertEqual(tree.op, "^")
        self.assertEqual(tree.right.op, "^")

    def test_precedence_and_parens(self):
        from app.parser import BinaryNode
        # 2+3*4 => 顶层是 +，右侧是 *
        a = parse("2+3*4")
        self.assertEqual(a.op, "+")
        self.assertEqual(a.right.op, "*")
        # (2+3)*4 => 顶层是 *，左侧是 +
        b = parse("(2+3)*4")
        self.assertEqual(b.op, "*")
        self.assertEqual(b.left.op, "+")

    def test_unclosed_paren(self):
        with self.assertRaises(ParseError):
            parse("(2+3")


class TestValidationOK(unittest.TestCase):
    def test_addition_with_conversion(self):
        r = validate_expression("3 kg + 500 g", {})
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.display_value, 3.5)
        self.assertEqual(r.unit_symbol, "kg")
        self.assertEqual(r.dim_name, "质量")

    def test_speed_times_time(self):
        r = validate_expression("60 km/h * 2 h", {})
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.value_si, 120_000)
        self.assertEqual(r.unit_symbol, "km")

    def test_speed_division_named_unit(self):
        r = validate_expression("100 km / 2 h", {})
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.display_value, 50.0)
        self.assertEqual(r.unit_symbol, "km/h")

    def test_density_ratio(self):
        r = validate_expression("m/(rho*V)", {
            "m": V(100, "g"), "rho": V(1, "g/mL"), "V": V(50, "mL")})
        self.assertTrue(r.ok)
        self.assertTrue(r.dim_symbol == "1")
        self.assertAlmostEqual(r.display_value, 2.0)

    def test_sqrt_even_dimension(self):
        r = validate_expression("sqrt(area)", {"area": V(16, "m^2")})
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.display_value, 4.0)
        self.assertEqual(r.dim_name, "长度")

    def test_kinetic_energy(self):
        r = validate_expression("0.5*m*v^2",
                                {"m": V(2, "kg"), "v": V(3, "m/s")})
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.display_value, 9.0)
        self.assertEqual(r.unit_symbol, "J")

    def test_ideal_gas_z(self):
        r = validate_expression("P*V/(n*R*T)", {
            "P": V(1, "atm"), "V": V(22.4, "L"),
            "n": V(1, "mol"), "T": V(273.15, "K")})
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.display_value, 1.0, delta=0.01)
        self.assertEqual(r.dim_name, "无量纲")

    def test_pv_is_energy(self):
        r = validate_expression("1 atm * 22.4 L", {})
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.value_si, 2269.68, delta=0.1)
        self.assertEqual(r.unit_symbol, "J")

    def test_molar_mass(self):
        r = validate_expression("mass/amount",
                                {"mass": V(5.85, "g"), "amount": V(0.1, "mol")})
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.display_value, 58.5)
        self.assertEqual(r.unit_symbol, "g/mol")

    def test_volume_sum_mixed_units(self):
        r = validate_expression("V1 + V2 + V3", {
            "V1": V(10, "mL"), "V2": V(2.5, "mL"), "V3": V(0.1, "L")})
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.display_value, 112.5)
        self.assertEqual(r.unit_symbol, "mL")

    def test_dimensionless_functions(self):
        self.assertTrue(validate_expression("sin(pi/2)", {}).ok)
        self.assertAlmostEqual(
            validate_expression("log10(1000)", {}).display_value, 3.0)
        self.assertTrue(validate_expression("exp(1)", {}).ok)

    def test_min_keeps_dimension(self):
        r = validate_expression("min(3 kg, 500 g)", {})
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.value_si, 0.5)

    def test_temperature_absolute_and_difference(self):
        # 20°C + 15 K = 35°C
        r = validate_expression("T0 + dT",
                                {"T0": V(20, "°C"), "dT": V(15, "K")})
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.value_si, 308.15)
        self.assertAlmostEqual(r.display_value, 35.0)

        # 温差 100°C - 20°C = 80°C = 80 K
        r = validate_expression("T2-T1",
                                {"T1": V(20, "°C"), "T2": V(100, "°C")})
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.value_si, 80.0)
        self.assertAlmostEqual(r.display_value, 80.0)

        # 212°F = 100°C
        r = validate_expression("Tf", {"Tf": V(212, "°F")})
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.value_si, 373.15)

    def test_offset_temperature_rejected_in_product(self):
        r = validate_expression("100 °C * 2", {})
        self.assertFalse(r.ok)
        self.assertEqual(r.errors[0]["code"], "dim_mismatch")


class TestValidationErrors(unittest.TestCase):
    def first(self, text, variables=None):
        r = validate_expression(text, variables or {})
        self.assertFalse(r.ok, f"expected error for {text!r}")
        return r.errors[0]

    def test_addition_dimension_mismatch(self):
        e = self.first("2 kg + 3 m")
        self.assertEqual(e["code"], "dim_mismatch")
        # 错误指向右操作数
        self.assertEqual("3 m", "2 kg + 3 m"[e["start"]:e["end"]])

    def test_fractional_power_on_dimension(self):
        e = self.first("x^1.5", {"x": V(2, "m")})
        self.assertEqual(e["code"], "bad_power")

    def test_dimensionful_exponent(self):
        e = self.first("2^(3 kg)")
        self.assertEqual(e["code"], "bad_power")

    def test_sqrt_odd_dimension(self):
        e = self.first("sqrt(x)", {"x": V(16, "m")})
        self.assertEqual(e["code"], "bad_power")

    def test_undefined_variable(self):
        e = self.first("foo + 1")
        self.assertEqual(e["code"], "undef_var")
        self.assertEqual("foo + 1"[e["start"]:e["end"]], "foo")

    def test_function_dimension_argument(self):
        e = self.first("ln(10 m)")
        self.assertEqual(e["code"], "dim_mismatch")

    def test_min_arg_dimension_mismatch(self):
        e = self.first("min(1 kg, 2 m)")
        self.assertEqual(e["code"], "dim_mismatch")

    def test_division_by_zero(self):
        e = self.first("1/0")
        self.assertEqual(e["code"], "domain")

    def test_sqrt_negative(self):
        e = self.first("sqrt(-4)")
        self.assertEqual(e["code"], "domain")

    def test_syntax_unrecognized_char(self):
        e = self.first("abc @ 1")
        self.assertEqual(e["code"], "syntax")

    def test_unknown_function(self):
        e = self.first("foo(1)")
        self.assertEqual(e["code"], "syntax")

    def test_concentration_plus_volume(self):
        e = self.first("C + Vv",
                       {"C": V(0.1, "mol/L"), "Vv": V(50, "mL")})
        self.assertEqual(e["code"], "dim_mismatch")

    def test_undefined_unit_name_hint(self):
        e = self.first("m + 1")
        self.assertEqual(e["code"], "undef_var")
        self.assertIn("单位", e["message"])


class TestConversions(unittest.TestCase):
    def test_includes_same_dimension_units(self):
        r = validate_expression("1 kg", {})
        syms = {c["symbol"] for c in r.conversions}
        self.assertIn("g", syms)
        self.assertIn("lb", syms)
        self.assertIn("kg", syms)

    def test_temperature_conversions(self):
        r = validate_expression("0 °C", {})
        vals = {c["symbol"]: c["value"] for c in r.conversions}
        self.assertAlmostEqual(vals["K"], 273.15)
        self.assertAlmostEqual(vals["°F"], 32.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
