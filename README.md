# 科研配方量纲校验台（DimLab）

用 **Python + FastAPI + SQLite + 原生前端** 实现的带单位表达式量纲校验工具。
录入计算表达式与变量值后，系统会：

1. **解析**括号、幂运算（`^` / `**`，右结合）与函数调用；
2. 在 AST 上**递归推导量纲**（SI 七个基本量纲 M/L/T/I/Θ/N/J，分数指数精确表示）；
3. 对带单位数值进行**单位换算**（含线性因子与温标偏移，如 °C/°F）；
4. 对三类典型错误给出**指向表达式片段**的诊断（错误 span 直接用于前端高亮）：
   - 相加/相减的两个量**量纲不一致**；
   - **非法幂指数**（带量纲的底使用非整数次幂、sqrt 量纲指数为奇数、指数带量纲等）；
   - 引用**未定义变量**；
5. 展示 SI 基准值、显示单位结果与**同量纲单位换算表**，以及逐步量纲推导轨迹；
6. 支持校验案例的**保存 / 加载 / 搜索 / 删除**（SQLite）与 **JSON 导出**。

---

## 快速开始

### Docker Compose（推荐）

```bash
docker compose up -d --build
```

启动后固定监听 **8000 端口**：

| 入口 | 地址 |
| --- | --- |
| Web 界面 | http://localhost:8000/ |
| OpenAPI / Swagger | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| 健康检查 | `GET http://localhost:8000/api/units` |

数据保存在命名卷 `dimlab-data`（容器内 `/data/cases.db`）中，容器重建不丢失。

仅用 Docker：

```bash
docker build -t dimlab .
docker run -d --name dimlab -p 8000:8000 -v dimlab-data:/data dimlab
```

### 本地开发

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

---

## 表达式语法

| 运算 | 写法 | 说明 |
| --- | --- | --- |
| 括号 | `(a+b)` | 支持全角 `（）` |
| 幂 | `x^2`、`x**2` | 右结合，如 `2^3^2` |
| 乘除 | `a*b`、`a/b`、`a·b` | 也支持隐式乘法 `2x`、`2(a+b)` |
| 加减 | `a+b-c` | 两侧必须同量纲 |
| 一元负号 | `-x` | |
| 函数 | `sqrt(x)`、`ln(x)`、`min(a,b)` 等 | 见下表 |
| 常数 | `pi`、`e`、`R`、`NA`、`c0`、`k_B` | `R`、`c0` 等自带量纲 |

支持的函数：

- 量纲保持：`abs`、`round`、`floor`、`ceil`、`min`、`max`（多参数须同量纲）
- 要求无量纲参数：`exp`、`ln`、`log10`、`log2`、`log(x[, base])`、`sin`、`cos`、`tan`
- 开方：`sqrt(x)`（被开方量各量纲指数必须为偶数，如 `sqrt(16 m^2)` 合法、`sqrt(16 m)` 非法）
- 二元幂：`pow(a, b)`

数字可以直接带单位：

```
25 °C          3 kg + 500 g        60 km/h * 2 h
9.8 m/s^2      25 J/(mol·K)        100 km / 2 h
```

内置 60+ 常用单位，覆盖质量、长度、时间、温度、体积、力学、能量、功率、压强、
频率、电学、浓度等（完整列表见界面「单位/函数手册」或 `GET /api/units`）。
复合单位可自由组合，如 `kg·m^2/s^2`、`mol/L`、`g/mL`。

> 量纲判定规则：数字后的名称按单位解释；表达式中裸标识符按变量解释；
> 若变量名与单位符号恰好重名（如 `m`），建议改用更具描述性的变量名（`mass`、`m_rate`）。

---

## 量纲与换算规则

- 量纲为 SI 七基本量纲上的**稀疏指数向量**（质量 M、长度 L、时间 T、电流 I、
  热力学温度 Θ、物质的量 N、发光强度 J），幂指数用 `Fraction` 精确运算。
- 单位到 SI 的线性换算：`y_SI = factor · x + offset`。
  温标单位 `°C`、`°F` 带偏移，只允许单独使用与加减；参与乘除/幂运算会被拒绝
  （请先换算为 `K`）。
- 乘除：量纲向量相加减；复合单位自动合并相同单位的幂指数。
- 幂：
  - 指数必须无量纲；
  - 底带量纲时指数必须是整数（如 `m^1.5` 非法，应写 `sqrt` 形式）。
- 相加：量纲必须完全一致；结果沿用左操作数的显示单位，数值自动做换算
  （如 `3 kg + 500 g = 3.5 kg`）。

---

## HTTP API

### `POST /api/validate` — 量纲校验

```json
{
  "expression": "P*V/(n*R*T)",
  "variables": {
    "P": {"value": 1, "unit": "atm"},
    "V": {"value": 22.4, "unit": "L"},
    "n": {"value": 1, "unit": "mol"},
    "T": {"value": 273.15, "unit": "K"}
  }
}
```

成功响应（节选）：

```json
{
  "ok": true,
  "result": {
    "display_value": 0.999,
    "unit_symbol": "atm·L/(mol·K)",
    "dim_name": "摩尔能量",
    "dim_symbol": "M·L^2·T^-2·Θ^-1·N^-1",
    "conversions": [ {"symbol": "J/(mol·K)", "value": 8.314, "...": "..."} ]
  },
  "steps": [ {"label": "变量", "expr": "P", "start": 0, "end": 1, "...": "..."} ],
  "errors": []
}
```

错误响应（HTTP 200，`ok=false`；错误可定位）：

```json
{
  "ok": false,
  "errors": [{
    "code": "dim_mismatch",
    "message": "相加的两个量量纲不一致：质量（M）与 长度（L）",
    "start": 7, "end": 10
  }]
}
```

错误码：`syntax`（语法/单位无法识别）、`dim_mismatch`（量纲冲突）、
`bad_power`（非法幂）、`undef_var`（未定义变量）、`domain`（除零、负数开方等数值域错误）。

### 案例库

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/cases?q=` | 列表 / 关键字搜索 |
| POST | `/api/cases` | 新建案例 |
| GET | `/api/cases/{id}` | 读取案例 |
| PUT | `/api/cases/{id}` | 更新案例 |
| DELETE | `/api/cases/{id}` | 删除案例 |
| GET | `/api/cases/{id}/export` | 导出单个案例 JSON（附件下载） |
| POST | `/api/validate/export` | 直接导出“表达式 + 变量 + 校验结果”JSON |

### 其他

- `GET /api/units`：单位分组、函数与内置常数清单。
- `POST /api/parse-check`：仅做语法解析，返回带 span 的 AST（调试用）。

JSON 导出格式：

```json
{ "format": "dimlab-case", "version": 1, "id": 1, "name": "…", "expression": "…", "variables": { "…": "…" } }
{ "format": "dimlab-result", "version": 1, "ok": true, "result": { "…": "…" } }
```

---

## 目录结构

```
.
├── app/
│   ├── __init__.py
│   ├── dimensions.py   # 量纲向量、单位定义、复合单位、换算
│   ├── parser.py       # 词法分析 + 递归下降解析器（带 span）
│   ├── validator.py    # AST 递归量纲推导、数值换算、诊断、换算表
│   ├── database.py     # SQLite 案例持久化
│   ├── main.py         # FastAPI 路由
│   └── static/         # 原生前端（index.html / style.css / app.js）
├── data/               # 本地运行时的 SQLite 文件（容器内挂载到 /data）
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 设计要点

- **错误可定位**：词法/语法/AST 每个节点都携带 `(start, end)` 字符偏移；
  量纲错误发生在哪个运算或变量上，span 就指向表达式中的那段文本，前端用叠加层高亮。
- **递归推导**：量纲与数值在同一次 AST 后序遍历中得到，每个节点生成一条
  「片段 / 类型 / 数值 / 单位 / 量纲」轨迹，悬停轨迹行会在表达式上联动高亮。
- **纯原生前端**：无构建步骤、无外部 CDN，离线可用。

## 可配置环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DIMLAB_DB` | `data/cases.db`（代码相对路径） | SQLite 数据库路径，容器中为 `/data/cases.db` |
