"""Заносить N записів у реєстр через API і зберігає їх ідентифікатори в loadgen/ids.json."""
import sys as _sys
_sys.stdout.reconfigure(encoding="utf-8")  # консоль Windows: cp1252
import argparse
import http.client
import json
import random
import uuid
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

IDS_FILE = Path(__file__).with_name("ids.json")

class APIClient:
    """Клієнт для виконання HTTP-запитів до API."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.parsed_url = urlparse(base_url)
        self.host = self.parsed_url.hostname
        self.port = self.parsed_url.port or 80

    def request(self, method: str, path: str, body: dict = None) -> tuple[int, dict | list | None]:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10)
        headers = {"Content-Type": "application/json"}
        payload = json.dumps(body) if body is not None else None

        conn.request(method, path, payload, headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()

        parsed_data = json.loads(data) if data else None
        return response.status, parsed_data


class ShiftDataGenerator:
    """Генератор тестових даних для чергувань відповідно до правил валідації."""

    @staticmethod
    def generate_fake_shift() -> dict:
        duration = random.randint(4, 24)
        random_days = random.randint(0, 1000)
        shift_date = (date.today() - timedelta(days=random_days)).isoformat()

        return {
            "doctor": "Watson",
            "department": "surgery",
            "date": shift_date,
            "beginning_time": "14:38",
            "duration_hours": duration,
            "shift_type": "all-day",
        }


class SeedService:
    """Сервіс для наповнення бази даних і збереження ідентифікаторів."""

    def __init__(self, api_client: APIClient, ids_file: Path = IDS_FILE):
        self.client = api_client
        self.ids_file = ids_file

    def ensure_ids(self, n: int = 100) -> list[str]:
        """Гарантує наявність n записів, повертає їхні id та зберігає в файл."""
        _, page = self.client.request("GET", f"/shifts?limit={n}")
        ids = [x["id"] for x in page["items"]] if page and "items" in page else []

        _tag = uuid.uuid4().hex[:6]
        needed = n - len(ids)

        for _ in range(needed):
            fake_data = ShiftDataGenerator.generate_fake_shift()
            status, body = self.client.request("POST", "/shifts", fake_data)
            assert status == 201, (status, body)
            ids.append(body["id"])

        self.ids_file.write_text(json.dumps(ids), encoding="utf-8")
        return ids

    @staticmethod
    def get_default_base_url() -> str:
        """Визначає адресу стенду з .env файлу."""
        env_file = Path(__file__).resolve().parent.parent / ".env"
        port = "18080"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("LB_PORT="):
                    port = line.split("=", 1)[1].strip()
                    break
        return f"http://127.0.0.1:{port}"


# Сумісність зі старими імпортами
def call(base: str, method: str, path: str, body: dict = None):
    return APIClient(base).request(method, path, body)


def fake_shift() -> dict:
    return ShiftDataGenerator.generate_fake_shift()


def ensure_ids(base: str, n: int = 100) -> list[str]:
    client = APIClient(base)
    service = SeedService(client)
    return service.ensure_ids(n)


def default_base() -> str:
    return SeedService.get_default_base_url()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=SeedService.get_default_base_url())
    ap.add_argument("--n", type=int, default=100)
    args = ap.parse_args()

    api_client = APIClient(args.base)
    seeder = SeedService(api_client)
    generated_ids = seeder.ensure_ids(args.n)

    print(f"{len(generated_ids)} ids -> {IDS_FILE}")
