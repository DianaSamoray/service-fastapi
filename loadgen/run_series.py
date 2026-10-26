"""Оркестрація вимірювань: піднімає стенд і проганяє серії. Команди див. HOWTO.md."""
import sys as _sys
_sys.stdout.reconfigure(encoding="utf-8")  # консоль Windows: cp1252
import argparse
import json
import os
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import gen  # noqa: E402
import seed  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
RATES = (10, 100, 500)
REPEATS = 3
PATH = "/shifts/{id}"


class Config:
    """Конфігурація та змінні оточення."""

    @staticmethod
    def get_base_url() -> str:
        env_file = ROOT / ".env"
        port = "8080"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("LB_PORT="):
                    port = line.split("=", 1)[1].strip()
                    break
        return f"http://127.0.0.1:{port}"


BASE = Config.get_base_url()


class DockerEnvironmentManager:
    """Клас для керування docker-compose стендом."""

    @staticmethod
    def compose(*args, replicas: int = None, capture: bool = False) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        if replicas is not None:
            env["WEB_REPLICAS"] = str(replicas)
        return subprocess.run(
            ["docker", "compose", *args],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=capture,
            text=True,
        )

    @classmethod
    def wait_health(cls, timeout: float = 120.0):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if urllib.request.urlopen(f"{BASE}/healthz", timeout=2).status == 200:
                    return
            except Exception:
                time.sleep(0.2)
        raise SystemExit("стенд не став готовим")

    @classmethod
    def bring_up(cls, instances: int):
        cls.compose("up", "-d", replicas=instances)
        cls.compose("restart", "lb")  # nginx резолвить web лише на старті
        cls.wait_health()
        time.sleep(2)


class StatsSampler:
    """Пише docker stats у CSV, поки триває прогін."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.stop = threading.Event()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("t,name,cpu_percent,mem\n")
            t0 = time.time()
            while not self.stop.is_set():
                out = subprocess.run(
                    ["docker", "stats", "--no-stream", "--format", "{{.Name}},{{.CPUPerc}},{{.MemUsage}}"],
                    capture_output=True,
                    text=True,
                ).stdout
                for line in out.strip().splitlines():
                    f.write(f"{time.time() - t0:.1f},{line}\n")
                f.flush()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join()


class BenchmarkRunner:
    """Набір сценаріїв для прогону вимірювань."""

    @staticmethod
    def selfcheck(args):
        """Генератор проти порожнього ендпоінта: показує межу самого генератора."""
        DockerEnvironmentManager.bring_up(1)
        for rate in args.rates:
            s = gen.run_open(BASE, "/_null", [], rate, 5, 15, out=RESULTS / "selfcheck" / f"rate{rate}")
            print(
                f"/_null  задано {rate}  досягнуто {s['achieved_rps']:.1f}  "
                f"p95 {s['p95_ms']:.2f} мс  non-2xx {s['non2xx_share']:.3f}"
            )

    @staticmethod
    def series(args):
        DockerEnvironmentManager.bring_up(args.instances)
        ids = seed.ensure_ids(BASE, 100)
        outdir = RESULTS / f"{args.instances}x"

        for rate in args.rates:
            for rep in range(1, REPEATS + 1):
                stats_path = RESULTS / "stats" / f"{args.instances}x_rate{rate}_r{rep}.csv"
                sampler = StatsSampler(stats_path) if args.stats else None

                if sampler:
                    with sampler:
                        s = gen.run_open(BASE, PATH, ids, rate, args.warmup, args.duration, out=outdir / f"rate{rate}_r{rep}")
                else:
                    s = gen.run_open(BASE, PATH, ids, rate, args.warmup, args.duration, out=outdir / f"rate{rate}_r{rep}")

                print(
                    f"{args.instances} інст. задано {rate} повтор {rep}: "
                    f"досягнуто {s['achieved_rps']:.1f} p50 {s['p50_ms']:.1f} "
                    f"p95 {s['p95_ms']:.1f} p99 {s['p99_ms']:.1f} "
                    f"non-2xx {s['non2xx_share']:.3f}"
                )
                time.sleep(5)

    @staticmethod
    def distribution(args):
        DockerEnvironmentManager.bring_up(2)
        ids = seed.ensure_ids(BASE, 100)
        since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        counts = Counter()

        for i in range(args.n):
            r = urllib.request.urlopen(f"{BASE}/shifts/{ids[i % len(ids)]}", timeout=5)
            counts[r.headers["X-Instance"]] += 1

        logs = DockerEnvironmentManager.compose("logs", "lb", "--since", since, capture=True).stdout
        upstream = Counter(
            w.split("=", 1)[1]
            for l in logs.splitlines()
            for w in l.split()
            if w.startswith("upstream=") and w != "upstream=-"
        )
        out = {
            "requests": args.n,
            "by_X-Instance_header": counts,
            "by_nginx_upstream_addr": upstream,
        }
        (RESULTS / "distribution.json").write_text(json.dumps(out, indent=2))
        print(json.dumps(out, indent=2))

    @staticmethod
    def closed(args):
        runs = sorted((RESULTS / "1x").glob(f"rate{args.rate}_r*.json"))
        if not runs:
            raise SystemExit("спершу зніміть серію на одному інстансі")

        conc = round(statistics.median(json.loads(p.read_text())["L_mean"] for p in runs))
        print(f"рівень {args.rate}, у відкритому контурі L_mean (медіана) = {conc} -> одночасних запитів {conc}")

        DockerEnvironmentManager.bring_up(1)
        ids = seed.ensure_ids(BASE, 100)
        for rep in range(1, REPEATS + 1):
            s = gen.run_closed(
                BASE, PATH, ids, conc, args.warmup, args.duration,
                out=RESULTS / "closed" / f"rate{args.rate}_c{conc}_r{rep}"
            )
            print(
                f"закритий, {conc} одночасних, повтор {rep}: "
                f"досягнуто {s['achieved_rps']:.1f} p95 {s['p95_ms']:.1f} мс"
            )
            time.sleep(5)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_selfcheck = sub.add_parser("selfcheck")
    p_selfcheck.add_argument("--rates", type=int, nargs="+", default=[500, 1000])
    p_selfcheck.set_defaults(fn=BenchmarkRunner.selfcheck)

    p_series = sub.add_parser("series")
    p_series.add_argument("--instances", type=int, required=True)
    p_series.add_argument("--rates", type=int, nargs="+", default=list(RATES))
    p_series.add_argument("--stats", action="store_true", help="писати docker stats у results/stats/")
    p_series.add_argument("--warmup", type=float, default=10)
    p_series.add_argument("--duration", type=float, default=30)
    p_series.set_defaults(fn=BenchmarkRunner.series)

    p_dist = sub.add_parser("distribution")
    p_dist.add_argument("--n", type=int, default=300)
    p_dist.set_defaults(fn=BenchmarkRunner.distribution)

    p_closed = sub.add_parser("closed")
    p_closed.add_argument("--rate", type=int, default=500)
    p_closed.add_argument("--warmup", type=float, default=10)
    p_closed.add_argument("--duration", type=float, default=30)
    p_closed.set_defaults(fn=BenchmarkRunner.closed)

    return ap


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    args.fn(args)
