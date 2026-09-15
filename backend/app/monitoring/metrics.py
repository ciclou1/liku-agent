from prometheus_client import Counter, Gauge, Histogram, Info


REQUEST_COUNT = Counter("liku_http_requests_total", "HTTP request count", ("method", "path", "status"))
REQUEST_LATENCY = Histogram("liku_http_request_duration_seconds", "HTTP request latency", ("method", "path"))
ACTIVE_REQUESTS = Gauge("liku_http_active_requests", "Active HTTP requests")
DATABASE_READY = Gauge("liku_database_ready", "Database readiness", ("database",))
REDIS_READY = Gauge("liku_redis_ready", "Redis readiness", ("redis",))
APPLICATION_INFO = Info("liku_application", "Application build information")


def configure_metrics(environment: str, version: str) -> None:
    APPLICATION_INFO.info({"environment": environment, "version": version})


def set_database_ready(database: str, ready: bool) -> None:
    DATABASE_READY.labels(database=database).set(1 if ready else 0)


def set_redis_ready(redis: str, ready: bool) -> None:
    REDIS_READY.labels(redis=redis).set(1 if ready else 0)


def redis_is_ready(redis: str = "broker") -> bool:
    return REDIS_READY.labels(redis=redis)._value.get() == 1
