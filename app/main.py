import os
from datetime import date
from typing import Generator

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from psycopg.errors import UniqueViolation
from sqlalchemy import Date, SmallInteger, String, create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

# ==========================================
# 1. DATABASE CONFIGURATION
# ==========================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql+psycopg://user:pass@localhost:5432/db"
)

engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=0,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


# ==========================================
# 2. SQLALCHEMY MODELS
# ==========================================

class Base(DeclarativeBase):
    pass


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor: Mapped[str] = mapped_column(String(64))
    department: Mapped[str] = mapped_column(String(64), index=True)
    shift_date: Mapped[date] = mapped_column(Date)
    beginning_time: Mapped[str] = mapped_column(String(8))
    duration_hours: Mapped[int] = mapped_column(SmallInteger)
    shift_type: Mapped[str] = mapped_column(String(64))


# ==========================================
# 3. PYDANTIC SCHEMAS
# ==========================================

class ShiftIn(BaseModel):
    doctor: str = Field(..., min_length=3, max_length=64)
    department: str = Field(..., min_length=3, max_length=64)
    shift_date: date
    beginning_time: str = Field(..., min_length=4, max_length=8)
    duration_hours: int
    shift_type: str = Field(..., min_length=3, max_length=64)

    @field_validator("duration_hours")
    @classmethod
    def duration_hours_in_range(cls, v: int) -> int:
        if not (4 <= v <= 24):
            raise ValueError("очікується від 4 до 24")
        return v


class ShiftOut(ShiftIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


# ==========================================
# 4. FASTAPI APP & ENDPOINTS
# ==========================================

app = FastAPI()


# 1. POST /shifts — створення (201 / 400)
@app.post("/shifts", response_model=ShiftOut, status_code=201)
def create_shift(body: ShiftIn, session: Session = Depends(get_session)):
    shift = Shift(**body.model_dump())
    session.add(shift)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if isinstance(exc.orig, UniqueViolation):
            raise HTTPException(status_code=400, detail="код уже існує")
        raise HTTPException(status_code=400, detail="Помилка цілісності даних")
    session.refresh(shift)
    return shift


# 2. GET /shifts — перелік із пагінацією та фільтрацією (200 / 400)
@app.get("/shifts")
def list_shifts(
    department: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    if not (1 <= limit <= 200) or offset < 0:
        raise HTTPException(status_code=400, detail="limit від 1 до 200, offset від нуля")

    stat = select(Shift)
    if department:
        stat = stat.where(Shift.department == department)

    total = session.scalar(select(func.count()).select_from(stat.subquery()))
    rows = session.scalars(
        stat.order_by(Shift.id).limit(limit).offset(offset)
    ).all()

    return {
        "items": [ShiftOut.model_validate(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# 3. GET /shifts/{id} — отримати один запис (200 / 404)
@app.get("/shifts/{id}", response_model=ShiftOut)
def get_shift(id: int, session: Session = Depends(get_session)):
    shift = session.get(Shift, id)
    if shift is None:
        raise HTTPException(status_code=404, detail="Зміну не знайдено")
    return shift


# 4. PUT /shifts/{id} — повна заміна запису (200 / 404 / 400)
@app.put("/shifts/{id}", response_model=ShiftOut)
def update_shift(id: int, body: ShiftIn, session: Session = Depends(get_session)):
    shift = session.get(Shift, id)
    if shift is None:
        raise HTTPException(status_code=404, detail="Зміну не знайдено")

    for key, value in body.model_dump().items():
        setattr(shift, key, value)

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if isinstance(exc.orig, UniqueViolation):
            raise HTTPException(status_code=400, detail="код уже існує")
        raise HTTPException(status_code=400, detail="Помилка цілісності даних")

    session.refresh(shift)
    return shift


# 5. DELETE /shifts/{id} — видалення (204 / 404)
@app.delete("/shifts/{id}", status_code=204)
def delete_shift(id: int, session: Session = Depends(get_session)):
    shift = session.get(Shift, id)
    if shift is None:
        raise HTTPException(status_code=404, detail="Зміну не знайдено")
    session.delete(shift)
    session.commit()


# 6. GET /healthz — перевірка готовності сервісу (200 / 503)
@app.get("/healthz")
def healthz(session: Session = Depends(get_session)):
    try:
        session.execute(select(1))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "error": str(exc)},
        )
    return {"status": "ok"}
