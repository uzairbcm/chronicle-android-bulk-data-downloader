from __future__ import annotations

from enum import StrEnum


class FilterType(StrEnum):
    """
    Enum for filter types used in the application.
    """

    INCLUSIVE = "Inclusive"
    EXCLUSIVE = "Exclusive"


class ChronicleDeviceType(StrEnum):
    """
    Enum for different types of devices supported by Chronicle.
    """

    AMAZON = "Amazon Fire"
    ANDROID = "Android"
    IPHONE = "iPhone"


class ChronicleDownloadDataType(StrEnum):
    """
    Enum for different types of data collected by Chronicle.
    """

    RAW = "UsageEvents"
    SURVEY = "AppUsageSurvey"
    PREPROCESSED = "Preprocessed"
    IOSSENSOR = "IOSSensor"
    TIME_USE_DIARY_DAYTIME = "DayTime"
    TIME_USE_DIARY_NIGHTTIME = "NightTime"
    TIME_USE_DIARY_SUMMARIZED = "Summarized"
