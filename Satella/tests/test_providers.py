from app.providers.manual_import import parse_csv


def test_csv_import_validation_and_dedup_id_stability():
    data = b"date,description,amount,currency,kind,category\n2026-10-01,Coffee,125.50,PHP,expense,Food\n"
    first = parse_csv(data)
    second = parse_csv(data)
    assert first[0].amount == second[0].amount
    assert first[0].external_id == second[0].external_id
    assert first[0].currency == "PHP"


def test_csv_rejects_invalid_data():
    try:
        parse_csv(b"date,description,amount,currency,kind\n2026-10-01,Invalid,-4,PHP,expense\n")
    except ValueError as exc:
        assert "row 2" in str(exc)
    else:
        raise AssertionError("Invalid amount should fail validation")
