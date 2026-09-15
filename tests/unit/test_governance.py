from app.services.governance import DataGovernanceService


def test_governance_separates_invalid_rows_and_counts_missing() -> None:
    result = DataGovernanceService().validate_rows([{"sku": "A", "quantity": 2}, {"sku": "B", "quantity": -1}, {"sku": "C", "quantity": None}], ["quantity"])
    assert len(result["valid"]) == 2
    assert len(result["errors"]) == 1
    assert result["missing_count"] == 1
