"""Час від `docker compose up` до першого 200 на /healthz: образи зібрані, томи порожні, 3 повтори."""

import json
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Консоль Windows: cp1252 -> utf-8
sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent


def get_lb_port(default_port: str = "8080") -> str:
    """Отримує значення LB_PORT з .env файлу або повертає дефолтне значення."""
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("LB_PORT="):
                return line.split("=", 1)[1].strip()
    return default_port


def dc(*args):
    """Виконує docker compose команди."""
    subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True, capture_output=True)


def measure_startup_time(runs: int = 3, port: str = "8080", max_wait_seconds: int = 60) -> list[float]:
    """Вимірює час від docker compose up -d до успішного healthz відгуку."""
    dc("build")
    times = []

    for i in range(runs):
        dc("down", "-v")
        t_start = time.perf_counter()
        dc("up", "-d")

        health_url = f"http://127.0.0.1:{port}/healthz"
        while True:
            # Захист від нескінченного циклу
            if time.perf_counter() - t_start > max_wait_seconds:
                raise TimeoutError(f"Сервіс не став ready протягом {max_wait_seconds} секунд")

            try:
                with urllib.request.urlopen(health_url, timeout=2) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                time.sleep(0.05)

        elapsed = time.perf_counter() - t_start
        times.append(elapsed)
        print(f"повтор {i + 1}: {elapsed:.2f} с")

    return times


def save_results(times: list[float]):
    """Зберігає результати замірів у JSON-файл."""
    median_val = statistics.median(times)
    print(f"медіана: {median_val:.2f} с")

    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    
    output_file = results_dir / "startup_time.json"
    payload = {
        "runs_s": times,
        "median_s": median_val,
    }
    output_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main():
    port = get_lb_port()
    times = measure_startup_time(runs=3, port=port)
    save_results(times)


if __name__ == "__main__":
    main()
