import os
import socket
from contextlib import asynccontextmanager
from datetime import date, time

from fastapi import FastAPI, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from psycopg import errors
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, PoolTimeout
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

HOSTNAME = socket.gethostname()
CONNINFO = (
    f"host={os.environ.get('DB_HOST', 'db')} port={os.environ.get('DB_PORT', '5432')} "
    f"dbname={os.environ['POSTGRES_DB']} user={os.environ['POSTGRES_USER']} "
    f"password={os.environ['POSTGRES_PASSWORD']} connect_timeout=3"
)
POOL_MAX = int(os.environ.get("POOL_MAX", "10"))
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MIN_DURATION, MAX_DURATION=4, 24
COLS="doctor, department, shift_date, beginning_time, duration_hours, shift_type"
pool = AsyncConnectionPool(
    CONNINFO, min_size=2, max_size=POOL_MAX, open=False, kwargs={"row_factory": dict_row}
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await pool.open()
    try:
        await pool.wait(timeout=60)  # поки база стартує, /healthz віддає 503
    except PoolTimeout:
        pass
    yield
    await pool.close()


app = FastAPI(
    lifespan=lifespan,
    title="Чергування лікаря",
    version="1.0.0",
    description=(
        "CRUD-сервіс лабораторної роботи 1, варіант 22.\n\n"
        "Валідація: тривалість чергування має бути від 4 до 24 годин. "
        "Фільтр у переліку — за відділенням. "
        "`limit` за замовчуванням 20, максимум 100."
    ),
)

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/docs")


class ShiftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doctor: str = Field(min_length=1, max_length=64)
    department: str = Field(min_length=1, max_length=64)
    shift_date: date
    beginning_time: time
    duration_hours: StrictInt
    shift_type: str = Field(min_length=1, max_length=64)

    @field_validator("duration_hours")
    @classmethod
    def duration_in_range(cls, v: int) -> int:
        duration = duration_hours
        if not MIN_DURATION <= duration <= MAX_DURATION:
            raise ValueError(
                f"duration {v} gives {duration_hours}; duration must be between {MIN_DURATION} and {MAX_DURATION}"
            )
        return v


def error(status: int, field: str, message: str) -> JSONResponse:
    return JSONResponse({"errors": [{"field": field, "message": message}]}, status_code=status)


@app.middleware("http")
async def add_instance_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Instance"] = HOSTNAME
    return response

 @app.exception_handler(RequestValidationError)
async def on_validation_error(_: Request, exc: RequestValidationError):
    errors_out = []
    for e in exc.errors():
        loc = [str(p) for p in e["loc"] if p not in ("body", "query", "path")]
        errors_out.append(
            {"field": ".".join(loc) or "body", "message": e["msg"].removeprefix("Value error, ")}
        )
    return JSONResponse({"errors": errors_out}, status_code=400)


@app.get("/healthz", summary="Готовність сервісу: 200, або 503 поки база недоступна")
async def healthz():
    try:
        async with pool.connection(timeout=2) as conn:
            await conn.execute("SELECT 1")
    except Exception:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ok"}


@app.post("/shifts", status_code=201, summary="Створити запис")
async def create(body: ShiftIn):
    async with pool.connection() as conn:
        cur = await conn.execute(
            f"INSERT INTO shifts (doctor, department, shift_date, beginning_time, "
            f"duration_hours, shift_type) VALUES (%s, %s, %s, %s, %s, %s) RETURNING {COLS}",
            [body.doctor, body.department, body.shift_date, body.beginning_time,
                body.duration_hours, body.shift_type],
        )
        return await cur.fetchone()

@app.get("/shifts", summary="Перелік із пагінацією і фільтром за відділенням")
async def list_doctors(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    department: str = Field(min_length=1, max_length=64) | None = None,
):
    where, params = ("WHERE department = %s", [department]) if department is not None else ("", [])
    async with pool.connection() as conn:
        cur = await conn.execute(
            f"SELECT {COLS} FROM shifts {where} ORDER BY id LIMIT %s OFFSET %s",
            [*params, limit, offset],
        )
        items = await cur.fetchall()
        cur = await conn.execute(f"SELECT count(*) AS n FROM shifts {where}", params)
        total = (await cur.fetchone())["n"]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


ID = Path(ge=1, le=2**63 - 1)


@app.get("/shifts/{id}", summary="Один запис за ідентифікатором")
async def get_one(id: int = ID):
    async with pool.connection() as conn:
        cur = await conn.execute(f"SELECT {COLS} FROM shifts WHERE id = %s", [id])
        row = await cur.fetchone()
    return row if row else error(404, "id", "shift not found")


@app.put("/shifts/{id}", summary="Повна заміна запису")
async def replace(body: ShiftIn, id: int = ID):
    async with pool.connection() as conn:
        cur = await conn.execute(
            f"UPDATE shifts SET doctor = %s, department = %s, shift_date = %s, "
            f"beginning_time = %s, duration_hours = %s, shift_type = %s WHERE id = %s "
            f"RETURNING {COLS}",
            [body.doctor, body.department, body.shift_date, body.beginning_time,
                body.duration_hours, body.shift_type, id],
        )
        row = await cur.fetchone()

    return row if row else error(404, "id", "shift not found")


@app.delete("/shifts/{id}", status_code=204, summary="Видалити запис")
async def delete(id: int = ID):
    async with pool.connection() as conn:
        cur = await conn.execute("DELETE FROM shifts WHERE id = %s RETURNING id", [id])
        row = await cur.fetchone()
    if row is None:
        return error(404, "id", "shift not found")
