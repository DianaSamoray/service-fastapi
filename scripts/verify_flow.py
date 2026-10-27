"""Етап 9: повний цикл запитів із журналом -> results/verify_log.md.

    python scripts/verify_flow.py            # цикл запитів
    python scripts/verify_flow.py lifecycle  # + перевірка down/up і down -v/up
"""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Консоль Windows: cp1252 -> utf-8
sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent


def get_base_url() -> str:
    """Визначає базовий URL сервісу з урахуванням LB_PORT з .env."""
    port = "8080"
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("LB_PORT="):
                port = line.split("=", 1)[1].strip()
                break
    return f"http://127.0.0.1:{port}"


BASE = get_base_url()
LOG = []


def call(method: str, path: str, body: dict = None, note: str = ""):
    """Виконує HTTP-запит та записує лог у форматі Markdown."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()

    text = raw.decode() if raw else ""
    
    body_str = f"\n```json\n{json.dumps(body, ensure_ascii=False, indent=2)}\n```" if body else ""
    response_str = f"\n```json\n{text or '(порожнє тіло)'}\n```\n"
    
    LOG.append(f"### {note}\n`{method} {path}`{body_str}\n→ **{status}**{response_str}")
    print(f"{status}  {method} {path}  {note}")

    return status, json.loads(text) if text else None


def shift(**kw) -> dict:
    """Генерує базовий payload для створення/оновлення чергування."""
    d = {
        "doctor": "Smith",
        "department": "cardiology",
        "shift_date": "2026-09-10",
        "beginning_time": "18:00",
        "duration_hours": 8,
        "shift_type": "night",
    }
    d.update(kw)
    return d


def dc(*args):
    """Виконує docker compose команди."""
    subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True, capture_output=True)


def wait(timeout_seconds: int = 60):
    """Очікує на готовність сервісу /healthz з обмеженням за часом."""
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        try:
            with urllib.request.urlopen(BASE + "/healthz", timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise TimeoutError("Сервіс не став ready у відведений час")


def flow():
    """Перевірка стандартного CRUD-циклу API."""
    call("GET", "/healthz", note="готовність")
    st, d = call("POST", "/shifts", shift(), note="створення")
    i = d["id"]

    # Перевірки валідації duration_hours
    call("POST", "/shifts", shift(duration_hours=3), note="400: тривалість чергування 3 години")
    call("POST", "/shifts", shift(duration_hours=27), note="400: тривалість чергування 27 годин")

    # Списки та фільтрація
    call("GET", "/shifts?limit=5", note="перелік")
    call("GET", "/shifts?department=surgery&limit=5", note="перелік з фільтром department")
    call("GET", "/shifts?limit=1000", note="400: limit понад максимум")

    # Читання та оновлення
    call("GET", f"/shifts/{i}", note="за ідентифікатором")
    call(
        "PUT",
        f"/shifts/{i}",
        shift(beginning_time="13:00", duration_hours=6, shift_type="day"),
        note="повна заміна",
    )
    call("PUT", f"/shifts/{i}", shift(duration_hours=2), note="400: PUT з невалідною тривалістю")
    call("PUT", "/shifts/999999999", shift(), note="404: PUT неіснуючого")

    # Видалення
    call("DELETE", f"/shifts/{i}", note="видалення")
    call("DELETE", f"/shifts/{i}", note="повторне видалення → 404")
    call("GET", f"/shifts/{i}", note="GET видаленого → 404")

    return d


def lifecycle():
    """Перевірка стійкості даних після перезапуску контейнерів та очищення томів."""
    st, d = call("POST", "/shifts", shift(department="cardiology"), note="запис перед down")

    # Перезапуск без видалення томі
    dc("down")
    dc("up", "-d")
    wait()
    call("GET", f"/shifts/{d['id']}", note="після down + up запис на місці (очікуємо 200)")

    # Перезапуск із видаленням томів (персистентних даних)
    dc("down", "-v")
    dc("up", "-d")
    wait()
    _, page = call("GET", "/shifts", note="після down -v + up база порожня (total = 0)")
    if page:
        print("total після down -v:", page.get("total", 0))


def save_log():
    """Зберігає зібраний лог у результати."""
    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    (results_dir / "verify_log.md").write_text("\n".join(LOG), encoding="utf-8")


def main():
    try:
        flow()
        if len(sys.argv) > 1 and sys.argv[1] == "lifecycle":
            lifecycle()
    finally:
        save_log()


if __name__ == "__main__":
    main()
