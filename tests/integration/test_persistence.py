from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base
from app.services.persistence import PersistenceService


@pytest.mark.asyncio
async def test_domain_results_can_be_persisted(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        service = PersistenceService()
        assert await service.save_forecast(session, {"sku": "A", "warehouse_id": "W1", "pattern": "stable", "forecast": [{"period": "1", "value": 2, "lower": 1, "upper": 3}]}) == 1
        assert (await service.save_safety_stock(session, {"category": "紧固件", "quantity": 80})).category == "紧固件"
        assert (await service.save_warning_rule(session, {"warning_type": "stagnant", "threshold": 365, "level": "warning"})).threshold == 365
        assert (await service.save_price_target(session, "A", True)).enabled is True
    await engine.dispose()
