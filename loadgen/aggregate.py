"""Медіани за трьома повторами для кожної конфігурації -> results/aggregate.json і results/table.md."""

import sys as _sys
_sys.stdout.reconfigure(encoding="utf-8")  # консоль Windows: cp1252

import json
import statistics
from pathlib import Path

RESULTS = Path(__file__).resolve().parent.parent / "results"
METRICS = ["achieved_rps", "p50_ms", "p95_ms", "p99_ms", "mean_ms", "non2xx_share", "L_mean", "L_max"]


class ResultsAggregator:
    """Клас для завантаження результатів тестування та розрахунку медіанних метрик."""

    def __init__(self, results_dir: Path = RESULTS, metrics: list[str] = None):
        self.results_dir = results_dir
        self.metrics = metrics or METRICS

    def aggregate_by_instances(self, instance_counts: tuple[int, ...] = (1, 2)) -> dict:
        """Збирає метрики з файлів результатів і розраховує медіани."""
        agg = {}
        for inst in instance_counts:
            by_rate = self._load_runs_for_instance(inst)
            for rate, runs in sorted(by_rate.items()):
                agg[f"{inst}x/{rate}"] = {
                    "instances": inst,
                    "rate": rate,
                    "runs": len(runs),
                    **{m: statistics.median(r[m] for r in runs) for m in self.metrics},
                }
        return agg

    def _load_runs_for_instance(self, instance_count: int) -> dict[int, list[dict]]:
        by_rate: dict[int, list[dict]] = {}
        inst_dir = self.results_dir / f"{instance_count}x"
        
        if inst_dir.exists():
            for path in sorted(inst_dir.glob("rate*_r*.json")):
                run_data = json.loads(path.read_text(encoding="utf-8"))
                rate = int(run_data["rate"])
                by_rate.setdefault(rate, []).append(run_data)
                
        return by_rate


class TableFormatter:
    """Форматування агрегованих даних у текстові звіти та таблиці."""

    @staticmethod
    def to_markdown(agg_data: dict) -> str:
        """Перетворює агреговані дані у Markdown-таблицю."""
        headers = ["| інстансів | задано, rps | досягнуто, rps | p50, мс | p95, мс | p99, мс | не-2xx, % |",
                   "|---|---|---|---|---|---|---|"]
        rows = list(headers)

        for v in agg_data.values():
            non2xx_pct = v["non2xx_share"] * 100
            rows.append(
                f"| {v['instances']} | {v['rate']} | {v['achieved_rps']:.1f} | "
                f"{v['p50_ms']:.1f} | {v['p95_ms']:.1f} | {v['p99_ms']:.1f} | "
                f"{non2xx_pct:.2f} |"
            )

        return "\n".join(rows) + "\n"


class ReportExporter:
    """Збереження агрегованих результатів у файли."""

    def __init__(self, results_dir: Path = RESULTS):
        self.results_dir = results_dir

    def export_json(self, data: dict, filename: str = "aggregate.json"):
        path = self.results_dir / filename
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def export_markdown(self, markdown_text: str, filename: str = "table.md"):
        path = self.results_dir / filename
        path.write_text(markdown_text, encoding="utf-8")


def main():
    aggregator = ResultsAggregator(RESULTS)
    aggregated_results = aggregator.aggregate_by_instances(instance_counts=(1, 2))

    markdown_table = TableFormatter.to_markdown(aggregated_results)

    exporter = ReportExporter(RESULTS)
    exporter.export_json(aggregated_results)
    exporter.export_markdown(markdown_table)

    print(markdown_table.strip())


if __name__ == "__main__":
    main()
