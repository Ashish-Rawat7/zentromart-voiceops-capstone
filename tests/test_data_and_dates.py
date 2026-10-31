from datetime import date
from pathlib import Path
from app.data import Dataset
from app.dates import add_business_days, parse_date
from app.config import settings

def test_dataset_csvs_load_as_strings():
    d = Dataset(settings.dataset_dir)
    assert len(d.table("orders")) == 1000
    assert len(d.table("products")) == 70
    assert isinstance(d.table("orders")[0]["order_id"], str)
    assert isinstance(d.table("orders")[0]["delivery_pincode"], str)

def test_fixed_reference_date_business_days():
    holidays = {"2026-10-19"}
    assert add_business_days(date(2026,10,17), 3, holidays) == date(2026,10,22)

def test_parse_date_formats():
    assert parse_date("refund started on 17 October 2026") == date(2026,10,17)
    assert parse_date("2026-10-12") == date(2026,10,12)

def test_dataset_health():
    assert Dataset(settings.dataset_dir).health()["available"] is True
