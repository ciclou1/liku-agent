from celery import Celery

from app.core.config import get_settings
from app.core.storage.paths import StoragePaths
import json
import os
import sys

settings = get_settings()
celery_app = Celery("liku", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_track_started=True, result_expires=86400, timezone="Asia/Shanghai", enable_utc=False)


@celery_app.task(bind=True, autoretry_for=(RuntimeError,), retry_backoff=True, max_retries=3)
def execute_task(self, task_id: str) -> dict:
    paths = StoragePaths()
    paths.task_pid(task_id).write_text(str(os.getpid()), encoding="utf-8")
    config_path = paths.task_config(task_id)
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    stdout_path = paths.task_dir(task_id) / "stdout.log"
    stderr_path = paths.task_dir(task_id) / "stderr.log"
    original_stdout, original_stderr = sys.stdout, sys.stderr
    stdout_file = stdout_path.open("a", encoding="utf-8")
    stderr_file = stderr_path.open("a", encoding="utf-8")
    sys.stdout, sys.stderr = stdout_file, stderr_file
    paths.task_progress(task_id).write_text(json.dumps({"progress": 10}), encoding="utf-8")
    try:
        result = {"task_id": task_id, "task_type": config.get("task_type", "generic"), "status": "completed"}
        paths.task_progress(task_id).write_text(json.dumps({"progress": 100}), encoding="utf-8")
        paths.task_result(task_id).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return result
    except Exception as exc:
        result = {"task_id": task_id, "status": "failed", "error": str(exc)}
        paths.task_result(task_id).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        raise
    finally:
        sys.stdout, sys.stderr = original_stdout, original_stderr
        stdout_file.close()
        stderr_file.close()


@celery_app.task(bind=True, autoretry_for=(RuntimeError,), retry_backoff=True, max_retries=3)
def run_fixture_sync(self, adapter_name: str = "api") -> dict:
    from app.adapters.registry import adapter_registry

    adapter = adapter_registry.get(adapter_name)
    if self.request.id:
        self.update_state(state="PROGRESS", meta={"progress": 10})
    count = adapter.sync()
    if self.request.id:
        self.update_state(state="PROGRESS", meta={"progress": 100})
    return {"adapter": adapter_name, "count": count, "status": "completed"}


@celery_app.task
def run_scheduled_sync(adapter_name: str = "api") -> dict:
    return run_fixture_sync.run(adapter_name)


@celery_app.task
def run_warning_scan() -> dict:
    from app.services.warning import WarningService

    return {"count": len(WarningService().list()), "status": "completed"}


@celery_app.task(bind=True, autoretry_for=(RuntimeError,), retry_backoff=True, max_retries=3)
def run_batch_forecast(self, items: list[dict]) -> dict:
    from app.algorithms.demand import forecast_demand

    results = []
    total = len(items)
    for index, item in enumerate(items):
        pattern, values = forecast_demand(item.get("values", []), horizon=int(item.get("horizon", 12)), category=item.get("category", ""))
        results.append({"sku": item.get("sku"), "warehouse_id": item.get("warehouse_id"), "pattern": pattern, "forecast": [point.__dict__ for point in values]})
        if total and self.request.id and index % max(1, total // 10) == 0:
            self.update_state(state="PROGRESS", meta={"progress": round(index / total * 100)})
    return {"count": len(results), "results": results, "status": "completed"}


celery_app.conf.beat_schedule = {
    "nightly-warning-scan": {"task": "app.celery_app.run_warning_scan", "schedule": 86400},
    "daily-fixture-sync": {"task": "app.celery_app.run_scheduled_sync", "schedule": 86400},
}
