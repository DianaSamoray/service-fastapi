@app.delete("/shifts/{id}")
def delete(
  pid: int,
  session: Session=Depends(get_session)
):
  row=session.get(Shift, pid)
  if row is None:
    raise HTTPException(404)
  session.delete(row)
  session.commit()
