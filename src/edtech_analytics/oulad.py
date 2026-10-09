"""Facts about the OULAD release that the rest of the code relies on."""

from __future__ import annotations

# Column order exactly as published (header row of each CSV).
EXPECTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "courses": ("code_module", "code_presentation", "module_presentation_length"),
    "assessments": (
        "code_module",
        "code_presentation",
        "id_assessment",
        "assessment_type",
        "date",
        "weight",
    ),
    "vle": ("id_site", "code_module", "code_presentation", "activity_type", "week_from", "week_to"),
    "studentInfo": (
        "code_module",
        "code_presentation",
        "id_student",
        "gender",
        "region",
        "highest_education",
        "imd_band",
        "age_band",
        "num_of_prev_attempts",
        "studied_credits",
        "disability",
        "final_result",
    ),
    "studentRegistration": (
        "code_module",
        "code_presentation",
        "id_student",
        "date_registration",
        "date_unregistration",
    ),
    "studentAssessment": ("id_assessment", "id_student", "date_submitted", "is_banked", "score"),
    "studentVle": (
        "code_module",
        "code_presentation",
        "id_student",
        "id_site",
        "date",
        "sum_click",
    ),
}

# Row counts stated in the data descriptor (Kuzilek, Hlosta & Zdrahal, Sci Data 4:170171, 2017).
PUBLISHED_ROW_COUNTS: dict[str, int] = {
    "courses": 22,
    "assessments": 206,
    "vle": 6364,
    "studentInfo": 32593,
    "studentRegistration": 32593,
    "studentAssessment": 173912,
    "studentVle": 10655280,
}

# Table 1 of the same paper: module -> (domain, presentations, students).
PUBLISHED_MODULE_SUMMARY: dict[str, tuple[str, int, int]] = {
    "AAA": ("Social Sciences", 2, 748),
    "BBB": ("Social Sciences", 4, 7909),
    "CCC": ("STEM", 2, 4434),
    "DDD": ("STEM", 4, 6272),
    "EEE": ("STEM", 3, 2934),
    "FFF": ("STEM", 4, 7762),
    "GGG": ("Social Sciences", 3, 2534),
}

PAPER_URL = "https://doi.org/10.1038/sdata.2017.171"
DATA_DOI_URL = "https://doi.org/10.6084/m9.figshare.5081998.v1"
LICENCE = "CC BY 4.0"
