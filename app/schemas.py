from datetime import date
from pydantic import BaseModel, ConfigDict, field, field_validator

class ShiftIn(Base):
  doctor: str=field(min_length=3, max_length=64)
  department: str=field(min_length=3, max_length=64)
  shift_date: date
  beginning_time: int
  duration_hours: int
  shift_type: str=field(min_length=3, max_length=64)
  @field_validation("duration_hours")
  @ClassMethod
  def duration_hours_in_range((ls, v): int)->int:
    if not(4<=v<=24):
      raise ValueError("очікується від 4 до 24")
    return v

class ShiftOut(ShiftIn):
  models_config=ConfigDict(from_attributes=True)
  id: int
