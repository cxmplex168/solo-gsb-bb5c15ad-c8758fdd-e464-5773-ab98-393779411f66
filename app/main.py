"""FastAPI 入口：量纲校验 Web/API。"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import database
from .dimensions import DERIVED_NAMES, UNITS
from .parser import FUNCTIONS, ParseError
from .validator import (
    CONSTANT_VALUES, Variable, parse_variable_unit, validate_expression,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield


app = FastAPI(
    title="科研配方量纲校验台",
    description="解析带单位的表达式，递归推导量纲、执行单位换算并定位错误。",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------- 模型

class VarIn(BaseModel):
    value: float
    unit: str = ""


class ValidateIn(BaseModel):
    expression: str = Field(..., examples=["m/(rho*V)"])
    variables: Dict[str, VarIn] = Field(default_factory=dict)


class CaseIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = ""
    expression: str = ""
    variables: Dict[str, VarIn] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------- 辅助

def _build_variables(raw: Dict[str, VarIn]) -> Dict[str, Variable]:
    out: Dict[str, Variable] = {}
    for name, v in raw.items():
        try:
            unit = parse_variable_unit(v.unit) if v.unit.strip() else None
        except ParseError as e:
            raise HTTPException(
                status_code=400,
                detail={"code": "bad_unit", "variable": name,
                        "message": e.message})
        out[name] = Variable(v.value, unit, raw_value=str(v.value),
                             raw_unit=v.unit)
    return out


def _case_jsonable(case: Dict[str, Any]) -> Dict[str, Any]:
    """数据库里的 variables 是 {name:{value,unit}}，直接透传。"""
    return case


# ---------------------------------------------------------------- 业务 API

@app.post("/api/validate")
def api_validate(body: ValidateIn):
    variables = _build_variables(body.variables)
    result = validate_expression(body.expression, variables)
    return {
        "ok": result.ok,
        "expression": body.expression,
        "result": {
            "value_si": result.value_si,
            "display_value": result.display_value,
            "unit_symbol": result.unit_symbol,
            "unit_name": result.unit_name,
            "dim_symbol": result.dim_symbol,
            "dim_name": result.dim_name,
            "conversions": result.conversions,
        },
        "steps": [
            {"label": s.label, "expr": s.expr, "value": s.value,
             "unit": s.unit, "dim": s.dim,
             "start": s.span[0], "end": s.span[1], "kind": s.kind}
            for s in result.steps
        ],
        "errors": result.errors,
    }


@app.post("/api/parse-check")
def api_parse_check(body: ValidateIn):
    """仅做语法解析，返回 AST 摘要，便于调试。"""
    from .parser import parse

    def dump(node):
        from .parser import (BinaryNode, CallNode, NumberNode, UnaryNode,
                             VarNode)
        if isinstance(node, NumberNode):
            return {"type": "num", "text": str(node.value),
                    "unit": node.unit.to_symbol() if node.unit else None,
                    "span": node.span}
        if isinstance(node, VarNode):
            return {"type": "var", "name": node.name,
                    "unit": node.unit.to_symbol() if node.unit else None,
                    "span": node.span}
        if isinstance(node, UnaryNode):
            return {"type": "unary", "op": node.op,
                    "operand": dump(node.operand), "span": node.span}
        if isinstance(node, BinaryNode):
            return {"type": "binary", "op": node.op,
                    "left": dump(node.left), "right": dump(node.right),
                    "span": node.span}
        if isinstance(node, CallNode):
            return {"type": "call", "name": node.name,
                    "args": [dump(a) for a in node.args], "span": node.span}
        return {"type": "?"}

    try:
        tree = parse(body.expression)
    except ParseError as e:
        return {"ok": False,
                "error": {"message": e.message, "start": e.start,
                          "end": e.end}}
    return {"ok": True, "ast": dump(tree)}


@app.get("/api/units")
def api_units():
    groups: Dict[str, List[dict]] = {}
    for key, d in UNITS.items():
        sig = d.dim.signature()
        group = DERIVED_NAMES.get(sig)
        if group is None:
            # 基本量纲分组
            from .dimensions import BASE_NAMES
            if d.dim.is_dimensionless():
                group = "无量纲"
            elif len(d.dim.exps) == 1:
                only = next(iter(d.dim.exps))
                group = BASE_NAMES[only]
            else:
                group = "其他"
        groups.setdefault(group, []).append({
            "key": key, "symbol": d.symbol, "name": d.cn,
            "dim": d.dim.to_symbol(),
        })
    return {"groups": groups,
            "functions": sorted(FUNCTIONS),
            "constants": [{"name": k, "desc": v[2],
                           "unit": v[1].to_symbol() if v[1] else "",
                           "dim": v[1].dim.to_name() if v[1] else "无量纲"}
                          for k, v in CONSTANT_VALUES.items()]}


# ---------------------------------------------------------------- 案例

@app.get("/api/cases")
def api_list_cases(q: Optional[str] = None):
    return database.list_cases(q)


@app.post("/api/cases", status_code=201)
def api_create_case(body: CaseIn):
    data = _case_payload(body)
    return database.create_case(data)


@app.get("/api/cases/{case_id}")
def api_get_case(case_id: int):
    case = database.get_case(case_id)
    if case is None:
        raise HTTPException(404, "案例不存在")
    return case


@app.put("/api/cases/{case_id}")
def api_update_case(case_id: int, body: CaseIn):
    case = database.update_case(case_id, _case_payload(body))
    if case is None:
        raise HTTPException(404, "案例不存在")
    return case


@app.delete("/api/cases/{case_id}")
def api_delete_case(case_id: int):
    if not database.delete_case(case_id):
        raise HTTPException(404, "案例不存在")
    return {"ok": True}


@app.get("/api/cases/{case_id}/export")
def api_export_case(case_id: int):
    case = database.get_case(case_id)
    if case is None:
        raise HTTPException(404, "案例不存在")
    payload = {"format": "dimlab-case", "version": 1, **case}
    filename = f"case-{case_id}.json"
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.post("/api/validate/export")
def api_validate_export(body: ValidateIn):
    """校验结果直接导出 JSON（不入库）。"""
    variables = _build_variables(body.variables)
    result = validate_expression(body.expression, variables)
    return {
        "format": "dimlab-result",
        "version": 1,
        "expression": body.expression,
        "variables": {k: v.model_dump() for k, v in body.variables.items()},
        "ok": result.ok,
        "result": {
            "value_si": result.value_si,
            "display_value": result.display_value,
            "unit_symbol": result.unit_symbol,
            "unit_name": result.unit_name,
            "dim_symbol": result.dim_symbol,
            "dim_name": result.dim_name,
            "conversions": result.conversions,
        },
        "errors": result.errors,
    }


def _case_payload(body: CaseIn) -> Dict[str, Any]:
    return {
        "name": body.name,
        "description": body.description,
        "expression": body.expression,
        "variables": {k: v.model_dump() for k, v in body.variables.items()},
        "tags": body.tags,
    }


# ---------------------------------------------------------------- 前端

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
