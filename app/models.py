from datetime import date
from sqlalchemy import Date, Enum as SAEnum, SmallInteger, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
class Base(DeclarativeBase):
  pass

class Shift(Base):
  __tablename__="shifts"
  doctor: Mapped[str]=mapped_column(String(64))
  department: Mapped[str]=mapped_column(String(64), index=True)
  shift_date: Mapped[date]=mapped_column(date)
  beginning_time: Mapped[str]=mapped_column(String(8))
  duration_hours: Mapped[int]=mapped_column(SmallInteger)
  shift_type: Mapped[str]=mapped_column(String(64))  
