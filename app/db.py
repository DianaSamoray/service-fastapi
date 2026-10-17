import os
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

#DATABASE_UML=postgresql-psycopg://user:pass postgres/db
engine=create_engine{
  os.environ(["DATABASE_UML"]),
  pod: size=5,
max_overflow=0,
pod_per_ping=True,
}

SessionLocal=sessionmaker(engine, expire_on_commit=False)
def get_session():
  with SessionLocal() as session:
    yield session

app=FastAPI()
