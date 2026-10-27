"""Збирає доказові виводи команд у results/evidence.md (стенд має бути піднятий).

    python scripts/collect_evidence.py
"""
import socket
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent

# Читання .env файлу
ENV = {}
env_file = ROOT / ".env"
if env_file.exists():
    ENV = dict(
        line.split("=", 1)
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.startswith("#")
    )

PASSWORD = ENV.get("POSTGRES_PASSWORD", "").strip()
PORT = ENV.get("LB_PORT", "8080").strip()
OUT = []


def sh(title, cmd, note=""):
    r = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    text = (r.stdout + r.stderr).strip() or "(порожній вивід)"
    if PASSWORD:
        text = text.replace(PASSWORD, "***")  # пароль не потрапляє у звіт
    OUT.append(
        f"## {title}\n`{' '.join(cmd)}`\n"
        + (f"\n{note}\n" if note else "")
        + f"\n```\n{text}\n```\n"
    )


def web():
    names = subprocess.run(
        ["docker", "compose", "ps", "--format", "{{.Name}}", "web"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout.split()
    return names[0] if names else "shifts-web-1"


w = web()

# 1. Стан контейнерів та портів
sh(
    "Контейнери, порти і стан здоровʼя (публікує порт лише lb)",
    [
        "docker",
        "compose",
        "ps",
        "--format",
        "table {{.Name}}\t{{.Status}}\t{{.Ports}}",
    ],
)

# 2. Метрики та шари образу
sh(
    "Розмір фінального образу",
    ["docker", "image", "inspect", "shifts:latest", "--format", "{{.Size}} байт"],
)
sh(
    "Шари образу",
    [
        "docker",
        "image",
        "history",
        "shifts:latest",
        "--format",
        "{{.Size}}\t{{.CreatedBy}}",
    ],
)

# 3. Безпека у контейнері
sh("Процес у контейнері: uid і користувач", ["docker", "exec", w, "id"])

# 4. Обмеження драйвера логування (додаткова вимога: max-size та max-file)
sh(
    "Додаткова вимога: обмеження драйвера логів (max-size і max-file)",
    [
        "docker",
        "inspect",
        w,
        "--format",
        "LogConfig Type={{.HostConfig.LogConfig.Type}} Config={{json .HostConfig.LogConfig.Config}}",
    ],
)

# 5. Конфігурація Healthcheck та обмеження ресурсів
sh(
    "Healthcheck сервісу (команда і стан)",
    [
        "docker",
        "inspect",
        w,
        "--format",
        "{{json .Config.Healthcheck.Test}} => {{.State.Health.Status}}",
    ],
)
sh(
    "Обмеження ресурсів web",
    [
        "docker",
        "inspect",
        w,
        "--format",
        "NanoCpus={{.HostConfig.NanoCpus}} Memory={{.HostConfig.Memory}}",
    ],
)

# 6. Перевірка відсутності пароля у відкритому вигляді
hist = subprocess.run(
    ["docker", "image", "history", "shifts:latest", "--no-trunc"],
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
).stdout

tracked = subprocess.run(
    ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True
).stdout.split()

found_in = []
if PASSWORD:
    found_in = [
        f
        for f in tracked
        if (ROOT / f).is_file()
        and PASSWORD in (ROOT / f).read_text(encoding="utf-8", errors="ignore")
    ]

env_in_img = subprocess.run(
    ["docker", "image", "inspect", "shifts:latest", "--format", "{{.Config.Env}}"],
    capture_output=True,
    text=True,
).stdout

pass_in_hist = "ЗНАЙДЕНО" if PASSWORD and PASSWORD in hist else "не знайдено"
pass_in_env = "ЗНАЙДЕНО" if PASSWORD and PASSWORD in env_in_img else "не знайдено"

OUT.append(
    "## Пароль не в образі, не в історії збірки, не в репозиторії\n```\n"
    f"у history образу: {pass_in_hist}\n"
    f"у змінних образу: {pass_in_env}\n"
    f"у файлах репозиторію (git ls-files): {found_in or 'не знайдено'}\n```\n"
)

sh(".env не комітиться", ["git", "check-ignore", "-v", ".env"])

# 7. Перевірка мережевої ізоляції з хоста
def reachable(port):
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


OUT.append(
    "## Порти бази і вебінстансів з хоста недоступні, балансувальник доступний\n```\n"
    f"127.0.0.1:5432 (Postgres): {'ДОСТУПНО' if reachable(5432) else 'підключення немає'}\n"
    f"127.0.0.1:8000 (web):      {'ДОСТУПНО' if reachable(8000) else 'підключення немає'}\n"
    f"127.0.0.1:{PORT} (lb):       {'доступно' if reachable(int(PORT)) else 'НЕДОСТУПНО'}\n```\n"
)

# 8. Внутрішня комунікація та масштабування
sh(
    "База доступна з контейнера сервісу за іменем db",
    [
        "docker",
        "exec",
        w,
        "python",
        "-c",
        "import socket;s=socket.create_connection(('db',5432),2);print('db:5432 підключення є')",
    ],
)
sh(
    "Репліки: скільки вебінстансів зараз",
    ["docker", "compose", "ps", "web", "--format", "{{.Name}}"],
)

# Збереження результатів
results_dir = ROOT / "results"
results_dir.mkdir(exist_ok=True)
(results_dir / "evidence.md").write_text(
    "# Докази\n\n" + "\n".join(OUT), encoding="utf-8"
)
print("\n".join(OUT))
