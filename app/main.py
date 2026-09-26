"""FastAPI 应用：量纲校验 API、案例管理、JSON 导出与静态前端。"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from .engine import analyze
from .units import catalog

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="科研配方量纲校验台", version="1.0.0")


class CheckRequest(BaseModel):
    expression: str = ""
    variables: dict[str, str] = {}
    target_unit: str | None = None


class CaseRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    expression: str = ""
    variables: dict[str, str] = {}
    target_unit: str = ""


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/check")
def check(req: CheckRequest) -> dict:
    """校验表达式：递归推导量纲、换算 SI、可选目标单位换算。"""
    return analyze(req.expression, req.variables, req.target_unit)


@app.get("/api/units")
def get_units() -> dict:
    """单位 / 常量 / 函数目录（供前端帮助面板）。"""
    return catalog()


@app.post("/api/cases", status_code=201)
def create_case(req: CaseRequest) -> dict:
    case_id = db.create_case(
        req.name.strip(), req.expression, req.variables, req.target_unit.strip()
    )
    return db.get_case(case_id)


@app.get("/api/cases")
def list_cases() -> dict:
    return {"cases": db.list_cases()}


@app.get("/api/cases/{case_id}")
def get_case(case_id: int) -> dict:
    case = db.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="案例不存在")
    return case


@app.delete("/api/cases/{case_id}", status_code=204)
def delete_case(case_id: int) -> None:
    if not db.delete_case(case_id):
        raise HTTPException(status_code=404, detail="案例不存在")


@app.get("/api/export")
def export_cases() -> JSONResponse:
    """导出全部案例为 JSON 文件。"""
    payload = {
        "app": "dimcheck",
        "kind": "cases",
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cases": db.list_cases(),
    }
    return JSONResponse(
        payload,
        headers={"Content-Disposition": 'attachment; filename="dimcheck_cases.json"'},
    )


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
