import pytest

from app.benchmarks.batch_forecast import run, run_sync


@pytest.mark.performance
def test_batch_forecast_benchmark_smoke() -> None:
    result = run(1000)
    assert result["sku_count"] == 1000
    assert result["elapsed_seconds"] >= 0


@pytest.mark.performance
def test_batch_sync_benchmark_smoke() -> None:
    result = run_sync(1000)
    assert result["sku_count"] == 1000
