from pathlib import Path

import pytest

from app.adapters.config import MappingConfig
from app.adapters.generic import WebServiceAdapter


def test_mapping_config_loads_and_applies(tmp_path: Path) -> None:
    path = tmp_path / "mapping.json"
    path.write_text('{"external_code": "sku"}', encoding="utf-8")
    assert MappingConfig.load(path).apply({"external_code": "A", "qty": 2}) == {"sku": "A", "qty": 2}


def test_webservice_adapter_parses_records() -> None:
    rows = WebServiceAdapter().parse_response("<response><record><sku>A</sku><qty>2</qty></record></response>")
    assert rows == [{"sku": "A", "qty": "2"}]
