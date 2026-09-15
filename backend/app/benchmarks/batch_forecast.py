import logging
import time

from app.algorithms.demand import forecast_demand
from app.adapters.generic import ApiAdapter

logger = logging.getLogger(__name__)


def run(size: int = 100_000) -> dict[str, float | int]:
    started = time.perf_counter()
    for index in range(size):
        forecast_demand([index % 12, (index + 1) % 12, (index + 2) % 12, (index + 3) % 12], horizon=12)
    seconds = time.perf_counter() - started
    return {"sku_count": size, "elapsed_seconds": round(seconds, 3), "throughput_per_second": round(size / seconds, 2) if seconds else 0}


def run_sync(size: int = 100_000) -> dict[str, float | int]:
    started = time.perf_counter()
    adapter = ApiAdapter("benchmark", ({"sku": f"SKU-{index}", "quantity": index % 10} for index in range(size)))
    count = adapter.sync()
    seconds = time.perf_counter() - started
    return {"sku_count": count, "elapsed_seconds": round(seconds, 3), "throughput_per_second": round(count / seconds, 2) if seconds else 0}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("batch forecast benchmark: %s", run())
