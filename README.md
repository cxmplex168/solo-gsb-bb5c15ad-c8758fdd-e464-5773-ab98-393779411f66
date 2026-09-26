# ⚗️ 科研配方量纲校验台（dimcheck）

录入**带单位的计算表达式**与变量取值，系统解析括号、幂运算与函数调用，**递归推导量纲**并自动完成单位换算；对**相加异量纲**、**非法幂指数**、**未定义变量**等错误，给出**指向表达式具体片段**的定位信息，并展示 SI 换算结果。支持校验案例的**保存 / 加载 / 删除**与 **JSON 导出**。

技术栈：Python 3.11+ · FastAPI · SQLite · 原生 HTML/JS/CSS（无前端构建）。

---

## 快速开始

### 方式一：Docker Compose（推荐）

```bash
docker compose up --build
```

启动后访问：

- Web 界面：<http://localhost:8000>
- API 文档（Swagger UI）：<http://localhost:8000/docs>

服务固定在 **8000 端口**；SQLite 数据存储在命名卷 `dimcheck-data` 中，容器重建不丢失。

### 方式二：本地运行

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 运行测试

```bash
pip install -r requirements-dev.txt
pytest tests/ -q
```

---

## 表达式语法

| 特性 | 示例 |
| --- | --- |
| 四则运算 / 括号 | `(1 + 2) * 3` |
| 幂运算（右结合，也可用 `**`） | `v^2`、`2^3^2 = 512`、`m^-2` |
| 数字带单位 | `9.8 m/s^2`、`1.5e-3 mol`、`2.5 kJ` |
| 隐式乘法 | `2 m`、`kg m/s^2`、`2(3+4)`、`2π r` |
| Unicode 上标 | `m²`、`x⁻¹`、`5 m³` |
| 符号别名 | `× ÷ · −`（等价于 `* / * -`） |
| 函数 | `sqrt(4 m^2)`、`sin(30 deg)`、`ln(e)`、`log(100)`、`abs(-3 m)` |
| 变量 | 变量值本身是表达式，可相互引用：`F = mass * g0` |
| 内置常量 | `pi π e c g0 G kb NA R qe me eps0 mu0` |

**名称解析顺序**：用户变量 > 内置常量 > 内置单位。变量名与单位/常量同名时按变量解析，并返回非致命**警告**（`warnings` 字段），避免静默错误。

**量纲规则**：

- 加 / 减：两边量纲必须一致，否则报 `dim_mismatch`，错误片段指向右操作数；
- 乘 / 除：量纲指数相应加减，数值自动换算到 SI；
- 幂：指数必须**无量纲**（否则 `bad_exponent`，片段指向指数），底数量纲指数乘以指数（允许分数，如 `(4 m^2)^0.5 = 2 m`）；
- `sin / exp / ln` 等函数参数必须无量纲（否则 `dimless_arg`）；`sqrt` 使量纲指数减半；
- 未定义的名称报 `undefined`，片段指向该标识符；变量循环引用报 `var_cycle`。

完整单位列表见 Web 界面右侧「单位 · 常量 · 函数」面板或 `GET /api/units`。注意：摄氏温度 °C 等带偏移的单位不支持，请使用开尔文 K。

---

## API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/check` | 校验表达式，返回量纲、SI 数值、目标单位换算、错误/警告 |
| GET | `/api/units` | 单位 / 常量 / 函数目录 |
| POST | `/api/cases` | 保存校验案例 |
| GET | `/api/cases` | 案例列表 |
| GET | `/api/cases/{id}` | 读取案例 |
| DELETE | `/api/cases/{id}` | 删除案例 |
| GET | `/api/export` | 导出全部案例（JSON 附件下载） |
| GET | `/api/health` | 健康检查 |

### 示例：校验通过

```bash
curl -s http://localhost:8000/api/check -H 'Content-Type: application/json' -d '{
  "expression": "0.5*mass*v^2 + mass*g0*h0",
  "variables": {"mass": "2 kg", "v": "10 m/s", "h0": "5 m"},
  "target_unit": "kJ"
}'
```

```json
{
  "ok": true,
  "errors": [],
  "warnings": [],
  "result": {
    "si_value": 198.0665,
    "dimension": ["2", "1", "-2", "0", "0", "0", "0"],
    "dimension_names": ["L", "M", "T", "I", "Θ", "N", "J"],
    "dimension_str": "L^2·M·T^-2",
    "si_unit": "m^2·kg·s^-2",
    "derived": ["J"],
    "target": {"unit": "kJ", "value": 0.1980665}
  }
}
```

### 示例：错误定位（相加异量纲）

```bash
curl -s http://localhost:8000/api/check -H 'Content-Type: application/json' -d '{
  "expression": "1 m + 1 s"
}'
```

```json
{
  "ok": false,
  "errors": [{
    "message": "量纲不一致：「L」与「T」不能相加",
    "start": 6, "end": 9,
    "kind": "dim_mismatch",
    "source": "expression"
  }],
  "result": null
}
```

`start` / `end` 是原始表达式字符串中的字符区间（上例即片段 `"1 s"`），`source` 取值：`expression`（主表达式）、`var:<名称>`（某变量的定义式）、`target`（目标单位）。前端据此将出错片段高亮标红。

### 错误类型（`kind`）

| kind | 含义 |
| --- | --- |
| `syntax` | 语法错误（空表达式、括号不配对、多余内容等） |
| `undefined` | 未定义的变量或单位 |
| `dim_mismatch` | 加减法两边量纲不一致 |
| `bad_exponent` | 幂指数不是无量纲量 |
| `dimless_arg` | 函数参数要求无量纲 |
| `arity` | 函数参数个数错误 |
| `var_error` / `var_cycle` | 变量定义出错 / 循环引用 |
| `target_dim` | 目标单位与结果量纲不一致 |
| `value` | 除零、定义域、非有限值等数值错误 |

### 保存与导出案例

```bash
# 保存
curl -s -X POST http://localhost:8000/api/cases -H 'Content-Type: application/json' -d '{
  "name": "自由落体", "expression": "0.5*g0*t^2",
  "variables": {"t": "3 s"}, "target_unit": "m"
}'

# 导出全部案例为 JSON 文件
curl -OJ http://localhost:8000/api/export
```

---

## 项目结构

```
├── app/
│   ├── main.py        # FastAPI 应用：API 路由 + 静态页面
│   ├── engine.py      # 引擎：词法分析 → 递归下降解析 → 量纲/数值求值
│   ├── units.py       # 单位 / 常量 / 函数注册表，量纲格式化
│   ├── db.py          # SQLite 案例存储
│   └── static/        # 原生前端（index.html / app.js / style.css）
├── tests/             # pytest：引擎单元测试 + API 集成测试
├── Dockerfile
├── docker-compose.yml
├── requirements.txt       # 运行依赖
└── requirements-dev.txt   # 测试依赖
```

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DB_PATH` | `./data/app.db`（容器内 `/app/data/app.db`） | SQLite 数据库文件路径 |
