from datetime import datetime, timezone
from uuid import uuid4

from app.adapters.registry import adapter_registry
from app.core.config import get_settings


class IntegrationService:
    def __init__(self) -> None:
        self.jobs: list[dict] = []
        self.alerts: list[dict] = []

    def create_job(self, adapter_name: str, mode: str) -> dict:
        if adapter_name != "jimu_erp" and get_settings().app_env != "test":
            raise ValueError("生产环境只允许使用积木 ERP 只读适配器")
        if adapter_name not in adapter_registry.names():
            raise ValueError(f"未知适配器: {adapter_name}")
        job = {"id": str(uuid4()), "adapter_name": adapter_name, "mode": mode, "status": "pending", "rows_processed": 0, "created_at": datetime.now(timezone.utc).isoformat()}
        self.jobs.append(job)
        return job

    def run_fixture(self, job_id: str) -> dict:
        job = next(item for item in self.jobs if item["id"] == job_id)
        job["status"] = "running"
        try:
            adapter = adapter_registry.get(job["adapter_name"])
            since = None if job["mode"] == "full" else job["created_at"]
            job["rows_processed"] = adapter.sync(since=since)
            job["status"] = "completed"
        except Exception as exc:
            job["status"] = "failed"
            job["error_message"] = str(exc)
            self.alerts.append({"job_id": job["id"], "message": f"同步失败: {exc}", "severity": "critical"})
        return job
