"""Етап 9: повний цикл запитів із журналом -> results/verify_log.md.

    python scripts/verify_flow.py            # цикл запитів
    python scripts/verify_flow.py lifecycle  # + перевірка down/up і down -v/up
"""
import sys as _sys
_sys.stdout.reconfigure(encoding="utf-8")  # консоль Windows: cp1252
import json
import subprocess
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = next((l.split("=", 1)[1].strip() for l in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
             if l.startswith("LB_PORT=")), "8080")
BASE = f"http://127.0.0.1:{PORT}"
LOG = []


def call(method, path, body=None, note=""):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=10)
        status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    text = raw.decode() if raw else ""
    LOG.append(f"### {note}\n`{method} {path}`" + (f"\n```json\n{json.dumps(body, ensure_ascii=False)}\n```" if body else "")
               + f"\n→ **{status}**\n```json\n{text or '(порожнє тіло)'}\n```\n")
    print(f"{status}  {method} {path}  {note}")
    return status, json.loads(text) if text else None


def shift(**kw):
    d = {"doctor": "Smith", "department": "cardiology",
         "date": "2026-09-10", "beginning_time": int(time.time()),
         "duration_hours": 5, "shift_type": "night"}
    d.update(kw)
    return d


def dc(*args):
    subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True, capture_output=True)


def wait():
    while True:
        try:
            if urllib.request.urlopen(BASE + "/healthz", timeout=2).status == 200:
                return
        except Exception:
            time.sleep(0.2)


def flow():
    call("GET", "/healthz", note="готовність")
    st, d = call("POST", "/shifts", shift(), "створення")
    i = d["id"]
    call("POST", "/shifts", shift(duration_hours=3), "400: тривалість чергування 3 години")
    call("POST", "/shifts", shift(duration_hours=27), "400: тривалість чергування 27 годин")
    call("GET", "/shifts?limit=5", note="перелік")
    call("GET", "/donor-registry?available=false&limit=5", note="перелік з фільтром available=false")
    call("GET", "/shifts?limit=1000", note="400: limit понад максимум")
    call("GET", f"/shifts/{i}", note="за ідентифікатором")
    call("PUT", f"/shifts/{i}", shift(beginning_time="13:00", duration_hours=6, shift_type="day"),
         "повна заміна")
    call("PUT", f"/shifts/{i}", shift(duration_hours=2), "400: PUT з невалідною тривалістю")
    call("PUT", "/shifts/999999999", shift(), "404: PUT неіснуючого")
    call("DELETE", f"/shifts/{i}", note="видалення")
    call("DELETE", f"/shifts/{i}", note="повторне видалення → 404")
    call("GET", f"/shifts/{i}", note="GET видаленого → 404")
    return d


def lifecycle():
    st, d = call("POST", "/shifts", shift(department="cardiology"), "запис перед down")
    dc("down"); dc("up", "-d"); wait()
    st, _ = call("GET", f"/shifts/{d['id']}", note="після down + up запис на місці (очікуємо 200)")
    dc("down", "-v"); dc("up", "-d"); wait()
    _, page = call("GET", "/shifts", note="після down -v + up база порожня (total = 0)")
    print("total після down -v:", page["total"])


if __name__ == "__main__":
    flow()
    if len(sys.argv) > 1 and sys.argv[1] == "lifecycle":
        lifecycle()
    (ROOT / "results" / "verify_log.md").write_text("\n".join(LOG), encoding="utf-8")
