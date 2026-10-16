from datetime import date

import pytest

from src.domain.weather_models import Decision, WeatherSnapshot
from src.domain.weather_policy import assess_jump_conditions

BASE_DATE = date(2026, 9, 29)


def make_weather(
    wind=10.0,
    gust=10.0,
    precipitation=0.0,
    clouds=10.0,
    temperature=25.0,
) -> WeatherSnapshot:
    return WeatherSnapshot(
        date=BASE_DATE,
        wind_speed_10m_kmh=wind,
        wind_gust_10m_kmh=gust,
        precipitation_mm=precipitation,
        cloud_cover_percent=clouds,
        temperature_2m_c=temperature,
    )


@pytest.mark.parametrize(
    "speed,expected",
    [
        (19.9, Decision.IDEAL),
        (20, Decision.MARGINAL),
        (28, Decision.MARGINAL),
        (28.1, Decision.PROHIBITED),
    ],
)
def test_wind_thresholds(speed, expected):
    assessment = assess_jump_conditions(make_weather(wind=speed))
    assert assessment.decision == expected


@pytest.mark.parametrize(
    "gust,expected",
    [
        (35, Decision.IDEAL),
        (35.1, Decision.PROHIBITED),
    ],
)
def test_gust_thresholds(gust, expected):
    assessment = assess_jump_conditions(make_weather(gust=gust))
    assert assessment.decision == expected


@pytest.mark.parametrize(
    "precipitation,expected",
    [
        (0.0, Decision.IDEAL),
        (0.1, Decision.PROHIBITED),
    ],
)
def test_precipitation_thresholds(precipitation, expected):
    assessment = assess_jump_conditions(make_weather(precipitation=precipitation))
    assert assessment.decision == expected


@pytest.mark.parametrize(
    "clouds,expected",
    [
        (29.9, Decision.IDEAL),
        (30, Decision.MARGINAL),
        (75, Decision.MARGINAL),
        (75.1, Decision.PROHIBITED),
    ],
)
def test_cloud_cover_thresholds(clouds, expected):
    assessment = assess_jump_conditions(make_weather(clouds=clouds))
    assert assessment.decision == expected


def test_all_ideal_yields_ideal():
    assessment = assess_jump_conditions(make_weather())
    assert assessment.decision == Decision.IDEAL
    assert assessment.reasons == []


def test_ideal_plus_one_marginal_yields_marginal():
    assessment = assess_jump_conditions(make_weather(wind=22))
    assert assessment.decision == Decision.MARGINAL
    assert len(assessment.reasons) == 1


def test_marginal_plus_one_prohibited_yields_prohibited():
    assessment = assess_jump_conditions(make_weather(wind=22, precipitation=1.0))
    assert assessment.decision == Decision.PROHIBITED


def test_multiple_prohibited_reports_all_reasons():
    assessment = assess_jump_conditions(make_weather(wind=30, gust=40, precipitation=2.0, clouds=90))
    assert assessment.decision == Decision.PROHIBITED
    assert len(assessment.reasons) == 4


def test_temperature_never_drives_decision():
    cold = assess_jump_conditions(make_weather(temperature=-10))
    hot = assess_jump_conditions(make_weather(temperature=45))
    assert cold.decision == Decision.IDEAL
    assert hot.decision == Decision.IDEAL
    assert cold.weather.temperature_2m_c == -10
    assert hot.weather.temperature_2m_c == 45


def test_marginal_requires_experienced_tandem_flag():
    assessment = assess_jump_conditions(make_weather(wind=25))
    assert assessment.requires_experienced_tandem is True
    assert assessment.allows_appointment is True


def test_prohibited_never_allows_appointment():
    assessment = assess_jump_conditions(make_weather(precipitation=5.0))
    assert assessment.allows_appointment is False
