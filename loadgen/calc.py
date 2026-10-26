"""Три розрахунки за знятими числами -> results/calculations.md. Спершу aggregate.py."""

import sys as _sys
_sys.stdout.reconfigure(encoding="utf-8")  # консоль Windows: cp1252

import json
import statistics
from pathlib import Path

RESULTS = Path(__file__).resolve().parent.parent / "results"


class KarpFlattCalculator:
    """Обчислення прискорення (Speedup) та метрики Карпа-Флатта."""

    @staticmethod
    def calculate(agg: dict, num_nodes: int = 2) -> list[str]:
        out = [
            "## 1. Прискорення і метрика Карпа-Флатта (N = 2)\n",
            "S = X2 / X1 на тому самому рівні; e = (1/S - 1/N) / (1 - 1/N) = (1/S - 0.5) / 0.5\n",
            "| рівень, rps | X1 | X2 | S | e |\n|---|---|---|---|---|",
        ]

        rates = sorted({v["rate"] for v in agg.values()})
        for rate in rates:
            a, b = agg.get(f"1x/{rate}"), agg.get(f"2x/{rate}")
            if a and b:
                s = b["achieved_rps"] / a["achieved_rps"]
                e = (1 / s - 0.5) / 0.5
                out.append(
                    f"| {rate} | {a['achieved_rps']:.1f} | {b['achieved_rps']:.1f} | {s:.3f} | {e:.3f} |"
                )

        return out


class LittlesLawCalculator:
    """Перевірка Закону Літтла (L = λ * W)."""

    @staticmethod
    def calculate(agg: dict, target_key: str = "1x/100") -> list[str]:
        out = ["\n## 2. Закон Літтла (100 rps, 1 інстанс)\n"]
        a = agg.get(target_key)

        if a:
            lam = a["achieved_rps"]
            w = a["mean_ms"] / 1000.0
            l_calculated = lam * w
            l_measured = a["L_mean"]
            diff_pct = abs(l_calculated - l_measured) / l_measured * 100

            out.append(
                f"λ = {lam:.2f} rps; W = {w * 1000:.2f} мс = {w:.5f} с; λ·W = {l_calculated:.4f}; "
                f"виміряне L = {l_measured:.4f}; розбіжність = {diff_pct:.2f} %"
            )

        return out


class LoopComparisonCalculator:
    """Порівняльний аналіз відкритого та закритого контуру."""

    def __init__(self, results_dir: Path = RESULTS):
        self.results_dir = results_dir

    def calculate(self, agg: dict) -> list[str]:
        out = [
            "\n## 3. Відкритий і закритий контур\n",
            "Кількість одночасних запитів у закритому контурі дорівнює середньому L, виміряному у відкритому контурі на тому самому рівні.\n",
            "| Рівень (відкритий контур) | Контур | Одночасних запитів | Досягнуто, rps | p95, мс | Не-2xx, % |",
            "|---|---|---|---|---|---|",
        ]

        closed_runs = self._load_closed_runs()

        for conc, runs in sorted(closed_runs.items()):
            rate = self._find_rate_for_concurrency(conc)
            o = agg.get(f"1x/{rate}")
            if not o:
                continue

            cx = statistics.median(r["achieved_rps"] for r in runs)
            cp = statistics.median(r["p95_ms"] for r in runs)
            ce = statistics.median(r["non2xx_share"] for r in runs)

            out.append(
                f"| {rate} rps | відкритий | L ≈ {o['L_mean']:.0f} | {o['achieved_rps']:.1f} |"
                f" {o['p95_ms']:.1f} | {o['non2xx_share'] * 100:.2f} |"
            )
            out.append(
                f"| {rate} rps | закритий | {conc} | {cx:.1f} | {cp:.1f} | {ce * 100:.2f} |"
            )

        return out

    def _load_closed_runs(self) -> dict[int, list[dict]]:
        closed = {}
        closed_dir = self.results_dir / "closed"
        if closed_dir.exists():
            for p in sorted(closed_dir.glob("*.json")):
                s = json.loads(p.read_text(encoding="utf-8"))
                closed.setdefault(s["concurrency"], []).append(s)
        return closed

    def _find_rate_for_concurrency(self, conc: int) -> int | None:
        closed_dir = self.results_dir / "closed"
        for q in closed_dir.glob(f"rate*_c{conc}_r1.json"):
            return int(q.name.split("_")[0].removeprefix("rate"))
        return None


class CalculationReport:
    """Генератор підсумкового Markdown-звіту та його збереження."""

    def __init__(self, results_dir: Path = RESULTS):
        self.results_dir = results_dir
        self.loop_calc = LoopComparisonCalculator(results_dir)

    def generate() -> str:
        agg_path = self.results_dir / "aggregate.json"
        if not agg_path.exists():
            raise FileNotFoundError("Спочатку виконайте скрипт aggregate.py")

        agg = json.loads(agg_path.read_text(encoding="utf-8"))

        lines = []
        lines.extend(KarpFlattCalculator.calculate(agg))
        lines.extend(LittlesLawCalculator.calculate(agg))
        lines.extend(self.loop_calc.calculate(agg))

        return "\n".join(lines) + "\n"

    def save_and_print(self):
        report_text = self.generate()
        out_file = self.results_dir / "calculations.md"
        out_file.write_text(report_text, encoding="utf-8")
        print(report_text, end="")


def main():
    report = CalculationReport(RESULTS)
    report.save_and_print()


if __name__ == "__main__":
    main()
