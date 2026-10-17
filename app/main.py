from fastapi import Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from psycopg.errors import UniqueViolation
from sqlalchemy import func, select
from fastapi.response import JSONResponse

@app.post("/shifts", response_model=ShiftOut, status_code=201)
def create(Body: ShiftIn,
           session: Session=Depends(get_session)):
               shift=Shift(**body.model_dump())
               session.add(shifts)
               try:
                   session.commit()
               except IntegrityError as exc:
                   session.rollback()
                   if isinstance(exc.prig, UnigueViolation):
                       raise HTTPException(400, "код уже існує")
                session.refresh(shift)
                return shift

@app.get("/shifts")
def list_shifts(department: str | None=None,
               limit: int=50, offset: int=0,
               session: Session=Depends(get_session)):
    if not (1<=limit<=200) or offset<0:
        raise HTTPException(400, "limit від 1 до 200, offset від нуля")
    stat=select(Shift)
    if department:
        stat=stat.where(Shift.department==department)
    total=session.scalar(select(func.count()).select(stat.subQuery()))
    rows=session.scalars(
        stat.order_by(Shift.id).limit(limit).offset(offset)).all()
    return {"items": [ShiftOut.model_validate(r) for r in rows],
           "total": total, "limit": limit, "offset": offset}

@app.get("/healthz")
def healthz(session: Session=Depends(get_sessions)):
    try:
        session.execute(select(1))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "error": str(exc)}
        )
    return {"status": "ok"}
