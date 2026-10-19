"""E2 成本曲线：从会话 usage 反事实重算缓存与 off-peak 节省。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codelotte.evals.cost_report import analyze_run, render_cost_markdown, write_cost_report
from tests.fake_client import fake_catalog
from tests.support import run_cli


def _run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    session = run_dir / "case.jsonl"
    entries = [
        {"type": "session", "id": "s", "schema": "session/v1"},
        {
            "type": "usage",
            "model": "fake-model",
            "inputTokens": 1_000_000,
            "outputTokens": 10_000,
            "cacheHitTokens": 500_000,
            "cacheMissTokens": 500_000,
            "cost": 0.55,
            "period": "offpeak",
        },
        {
            "type": "usage",
            "model": "fake-model",
            "inputTokens": 1_000_000,
            "outputTokens": 10_000,
            "cacheHitTokens": 900_000,
            "cacheMissTokens": 100_000,
            "cost": 0.158,
            "period": "offpeak",
        },
    ]
    session.write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    payload = {
        "cases": [
            {
                "task_id": "t",
                "repetition": 1,
                "session_path": str(session),
                "harness": "codelotte",
            }
        ]
    }
    (run_dir / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n"
    )
    return run_dir


def test_analyze_run_recomputes_cache_and_peak_counterfactuals(tmp_path: Path) -> None:
    catalog = fake_catalog(off_peak_multiplier=0.5)

    run = analyze_run(catalog, _run_dir(tmp_path))

    assert run.calls == 2
    assert run.cache_hit_tokens == 1_400_000
    assert run.cache_miss_tokens == 600_000
    assert run.cache_hit_rate == pytest.approx(1_400_000 / 2_000_000)
    assert run.actual_cost == pytest.approx(0.708)
    assert run.no_cache_cost == pytest.approx(2.08)
    assert run.peak_cost == pytest.approx(1.416)
    assert run.no_cache_peak_cost == pytest.approx(4.16)
    assert run.cache_saving == pytest.approx(1.372)
    assert run.offpeak_saving == pytest.approx(0.708)
    assert [bucket.index for bucket in run.by_index] == [1, 2]


def test_cost_report_renders_actual_vs_counterfactual(tmp_path: Path) -> None:
    catalog = fake_catalog(off_peak_multiplier=0.5)
    run = analyze_run(catalog, _run_dir(tmp_path))

    markdown = render_cost_markdown(
        [run], catalog=catalog, command="codelotte eval cost --run run"
    )

    assert "成本曲线" in markdown
    assert "缓存命中率" in markdown
    assert "无缓存反事实" in markdown
    assert "全峰价反事实" in markdown
    assert "70.0%" in markdown


def test_write_cost_report_writes_json_and_markdown(tmp_path: Path) -> None:
    catalog = fake_catalog(off_peak_multiplier=0.5)
    run = analyze_run(catalog, _run_dir(tmp_path))

    path = write_cost_report(
        tmp_path / "out", [run], catalog=catalog, command="codelotte eval cost --run run"
    )

    assert path.name == "cost-report.md"
    payload = json.loads((path.parent / "cost-report.json").read_text("utf-8"))
    assert payload["runs"][0]["actual_cost"] == pytest.approx(0.708)


def test_cost_cli_writes_report(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    out = tmp_path / "cost"

    result = run_cli(
        "eval", "cost", "--run", str(run_dir), "--out", str(out)
    )

    assert result.returncode == 0, result.stderr
    assert (out / "cost-report.md").is_file()
    assert "成本曲线" in (out / "cost-report.md").read_text(encoding="utf-8")
