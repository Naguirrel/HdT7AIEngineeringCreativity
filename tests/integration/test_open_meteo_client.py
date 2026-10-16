from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from src.integrations.open_meteo import OpenMeteoClient, OpenMeteoError

BASE_URL = "https://api.open-meteo.com/v1/forecast"
TARGET_DATE = date(2026, 9, 29)


def make_client() -> OpenMeteoClient:
    return OpenMeteoClient(latitude=14.013722, longitude=-90.771611, base_url=BASE_URL)


def daily_payload(date_str: str, **overrides) -> dict:
    values = {
        "wind_speed_10m_max": 15.0,
        "wind_gusts_10m_max": 20.0,
        "precipitation_sum": 0.0,
        "cloud_cover_mean": 40.0,
        "temperature_2m_max": 27.5,
    }
    values.update(overrides)
    return {"daily": {"time": [date_str], **{key: [value] for key, value in values.items()}}}


def test_maps_successful_response_to_snapshot(requests_mock):
    requests_mock.get(BASE_URL, json=daily_payload(TARGET_DATE.isoformat()))
    snapshot = make_client().get_weather(TARGET_DATE)

    assert snapshot.date == TARGET_DATE
    assert snapshot.wind_speed_10m_kmh == 15.0
    assert snapshot.wind_gust_10m_kmh == 20.0
    assert snapshot.precipitation_mm == 0.0
    assert snapshot.cloud_cover_percent == 40.0
    assert snapshot.temperature_2m_c == 27.5
    assert snapshot.source == "open-meteo"


def test_uses_explicit_units_in_request(requests_mock):
    requests_mock.get(BASE_URL, json=daily_payload(TARGET_DATE.isoformat()))
    make_client().get_weather(TARGET_DATE)

    query = parse_qs(urlsplit(requests_mock.last_request.url).query)
    assert query["wind_speed_unit"] == ["kmh"]
    assert query["precipitation_unit"] == ["mm"]
    assert query["temperature_unit"] == ["celsius"]
    assert query["timezone"] == ["America/Guatemala"]


def test_http_error_raises_open_meteo_error(requests_mock):
    requests_mock.get(BASE_URL, status_code=500, text="internal error")
    with pytest.raises(OpenMeteoError):
        make_client().get_weather(TARGET_DATE)


def test_network_failure_raises_open_meteo_error(requests_mock):
    requests_mock.get(BASE_URL, exc=requests.exceptions.ConnectTimeout)
    with pytest.raises(OpenMeteoError):
        make_client().get_weather(TARGET_DATE)


def test_invalid_json_raises_open_meteo_error(requests_mock):
    requests_mock.get(BASE_URL, text="not-json", status_code=200)
    with pytest.raises(OpenMeteoError):
        make_client().get_weather(TARGET_DATE)


def test_missing_daily_section_raises_open_meteo_error(requests_mock):
    requests_mock.get(BASE_URL, json={})
    with pytest.raises(OpenMeteoError):
        make_client().get_weather(TARGET_DATE)


def test_incomplete_payload_raises_open_meteo_error(requests_mock):
    payload = daily_payload(TARGET_DATE.isoformat())
    del payload["daily"]["cloud_cover_mean"]
    requests_mock.get(BASE_URL, json=payload)
    with pytest.raises(OpenMeteoError):
        make_client().get_weather(TARGET_DATE)


def test_null_values_in_payload_raise_open_meteo_error(requests_mock):
    requests_mock.get(BASE_URL, json=daily_payload(TARGET_DATE.isoformat(), precipitation_sum=None))
    with pytest.raises(OpenMeteoError):
        make_client().get_weather(TARGET_DATE)


def test_date_not_included_in_response_raises_open_meteo_error(requests_mock):
    requests_mock.get(BASE_URL, json=daily_payload("2026-01-01"))
    with pytest.raises(OpenMeteoError):
        make_client().get_weather(TARGET_DATE)
