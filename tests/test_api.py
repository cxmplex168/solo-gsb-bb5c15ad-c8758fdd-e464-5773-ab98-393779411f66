"""FastAPI 接口集成测试（TestClient，无需监听端口）。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 在导入应用前指定临时数据库
_tmpdir = tempfile.mkdtemp()
os.environ["DIMLAB_DB"] = os.path.join(_tmpdir, "api_cases.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app import database  # noqa: E402


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        cls.client = TestClient(app)

    def test_index_and_static(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/static/app.js").status_code, 200)
        self.assertEqual(self.client.get("/static/style.css").status_code, 200)

    def test_units_book(self):
        d = self.client.get("/api/units").json()
        self.assertIn("质量", d["groups"])
        self.assertIn("sqrt", d["functions"])
        const_names = {c["name"] for c in d["constants"]}
        self.assertIn("R", const_names)

    def test_validate_ok(self):
        r = self.client.post("/api/validate", json={
            "expression": "3 kg + 500 g", "variables": {}}).json()
        self.assertTrue(r["ok"])
        self.assertAlmostEqual(r["result"]["display_value"], 3.5)

    def test_validate_mismatch_points_to_fragment(self):
        r = self.client.post("/api/validate", json={
            "expression": "2 kg + 3 m", "variables": {}}).json()
        self.assertFalse(r["ok"])
        e = r["errors"][0]
        self.assertEqual(e["code"], "dim_mismatch")
        self.assertEqual(
            "2 kg + 3 m"[e["start"]:e["end"]], "3 m")

    def test_bad_power_fractional(self):
        r = self.client.post("/api/validate", json={
            "expression": "x^1.5",
            "variables": {"x": {"value": 2, "unit": "m"}}}).json()
        self.assertEqual(r["errors"][0]["code"], "bad_power")

    def test_undefined_variable(self):
        r = self.client.post("/api/validate", json={
            "expression": "foo + 1", "variables": {}}).json()
        self.assertEqual(r["errors"][0]["code"], "undef_var")

    def test_bad_unit_in_variable_400(self):
        resp = self.client.post("/api/validate", json={
            "expression": "x",
            "variables": {"x": {"value": 1, "unit": "nope"}}})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"]["code"], "bad_unit")

    def test_case_lifecycle_and_export(self):
        payload = {
            "name": "接口案例",
            "description": "生命周期测试",
            "expression": "P*V/(n*R*T)",
            "variables": {
                "P": {"value": 1, "unit": "atm"},
                "V": {"value": 22.4, "unit": "L"},
                "n": {"value": 1, "unit": "mol"},
                "T": {"value": 273.15, "unit": "K"}},
            "tags": ["test"],
        }
        resp = self.client.post("/api/cases", json=payload)
        self.assertEqual(resp.status_code, 201)
        cid = resp.json()["id"]

        got = self.client.get(f"/api/cases/{cid}").json()
        self.assertEqual(got["expression"], payload["expression"])
        self.assertIn("P", got["variables"])

        hits = self.client.get("/api/cases", params={"q": "气体"}).json()
        # 搜索词“气体”在本案例中不出现，改为搜名称
        self.assertIsInstance(hits, list)
        hits = self.client.get("/api/cases", params={"q": "案例"}).json()
        self.assertTrue(any(c["id"] == cid for c in hits))

        upd = self.client.put(f"/api/cases/{cid}",
                              json={**payload, "name": "改名案例"})
        self.assertEqual(upd.json()["name"], "改名案例")

        export = self.client.get(f"/api/cases/{cid}/export").json()
        self.assertEqual(export["format"], "dimlab-case")
        self.assertEqual(export["expression"], payload["expression"])

        ok = self.client.delete(f"/api/cases/{cid}")
        self.assertTrue(ok.json()["ok"])
        self.assertEqual(self.client.get(f"/api/cases/{cid}").status_code, 404)

    def test_validate_export_json(self):
        r = self.client.post("/api/validate/export", json={
            "expression": "60 km/h * 2 h", "variables": {}}).json()
        self.assertEqual(r["format"], "dimlab-result")
        self.assertTrue(r["ok"])
        self.assertIn("conversions", r["result"])

    def test_parse_check(self):
        r = self.client.post("/api/parse-check", json={
            "expression": "a+b^2", "variables": {}}).json()
        self.assertTrue(r["ok"])
        self.assertEqual(r["ast"]["type"], "binary")
        bad = self.client.post("/api/parse-check", json={
            "expression": "(a", "variables": {}}).json()
        self.assertFalse(bad["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
