import pytest

from app.services.database_profiles import masked_database_url, validate_database_profile


def test_database_profile_validation_supports_mainstream_engines() -> None:
    validate_database_profile("sqlite", "sqlite+aiosqlite:///./storage/demo.db")
    validate_database_profile("mysql", "mysql+aiomysql://user:password@localhost:3306/liku")
    validate_database_profile("postgresql", "postgresql+asyncpg://user:password@localhost:5432/liku")
    validate_database_profile("dameng", "dm+dmPython://user:password@localhost:5236?schema=SYSDBA")
    assert "password" not in masked_database_url("mysql+aiomysql://user:password@localhost:3306/liku")


def test_database_profile_rejects_mismatched_url() -> None:
    with pytest.raises(ValueError):
        validate_database_profile("mysql", "postgresql+asyncpg://user:password@localhost:5432/liku")
