from datetime import date

import pytest

from naswa_matcher.template_filters import (
    TEMPLATE_FILTERS,
    chat_markdown,
    format_date,
    format_wage,
    percent_of,
    program_hiring_stats,
    trades_by_program_count,
    typical_program_length,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-06-29", "June 29, 2026"),
        ("2026-01-01", "January 1, 2026"),
        ("2026-12-31", "December 31, 2026"),
        (None, "—"),
        ("", "—"),
    ],
)
def test_format_date_formats_valid_dates(value, expected):
    """Verifies that valid ISO date strings are formatted for display and that
    missing values use the fallback dash."""
    assert format_date(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "not-a-date",
        "2026-13-01",
        "2026-06-nope",
        "2026-06-29-extra",
        "2026-00-01",
    ],
)
def test_format_date_returns_original_value_for_invalid_dates(value):
    """Verifies that invalid or unexpected date strings are returned unchanged
    instead of raising an error."""
    assert format_date(value) == value


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (59092, "$59,092"),
        (59092.4, "$59,092"),
        (59092.6, "$59,093"),
        (0, "$0"),
        (None, "—"),
    ],
)
def test_format_wage(value, expected):
    """Verifies that wage values are rounded to whole dollars, formatted with
    commas, and missing values use the fallback dash."""
    assert format_wage(value) == expected


@pytest.mark.parametrize(
    ("value", "maximum", "expected"),
    [
        (50, 100, 50),
        (59_092, 98_200, 60),
        (78_450, 98_200, 80),
        (98_200, 98_200, 100),
        (150, 100, 100),
        (-10, 100, 0),
        (50, 0, 0),
        (50, -100, 0),
        (None, 100, 0),
        (50, None, 0),
        ("not-a-number", 100, 0),
        (50, "not-a-number", 0),
    ],
)
def test_percent_of(value, maximum, expected):
    """Verifies that percent_of returns a clamped integer percentage and safely
    handles invalid, missing, zero, or negative maximum values."""
    assert percent_of(value, maximum) == expected


def test_chat_markdown_renders_paragraphs_lists_and_bold_text():
    """Verifies that chat Markdown is converted into the expected HTML."""
    value = """\
Just to confirm:

- **Likes:** computers, pizza, soccer
"""

    assert str(chat_markdown(value)) == (
        "<p>Just to confirm:</p>\n"
        "<ul>\n"
        "<li><strong>Likes:</strong> computers, pizza, soccer</li>\n"
        "</ul>\n"
    )


def test_chat_markdown_escapes_raw_html():
    """Verifies that raw HTML in chat content is displayed rather than executed."""
    value = "<script>alert('hello')</script>"

    assert str(chat_markdown(value)) == (
        "<p>&lt;script&gt;alert('hello')&lt;/script&gt;</p>\n"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("", ""),
    ],
)
def test_chat_markdown_handles_missing_content(value, expected):
    """Verifies that missing or empty chat content produces no HTML."""
    assert str(chat_markdown(value)) == expected


def test_typical_program_length_returns_most_common_length():
    programs = [
        {"programLength": 60},
        {"programLength": 48},
        {"programLength": 60},
    ]

    assert typical_program_length(programs) == 60


def test_typical_program_length_prefers_shorter_length_on_tie():
    programs = [
        {"programLength": 60},
        {"programLength": 48},
    ]

    assert typical_program_length(programs) == 48


def test_typical_program_length_ignores_missing_lengths():
    programs = [
        {"programLength": None},
        {"programLength": None},
        {"programLength": 36},
    ]

    assert typical_program_length(programs) == 36


def test_typical_program_length_returns_none_when_all_lengths_missing():
    programs = [
        {"programLength": None},
        {"programLength": None},
    ]

    assert typical_program_length(programs) is None


def test_program_hiring_stats_counts_current_and_upcoming_opportunities():
    program_group = {
        "trades": [
            {
                "tradeName": "Electrician",
                "programs": [
                    {
                        "programAk": 100,
                        "socCode": "47-2111.00",
                        "opportunities": [
                            {
                                "id": "current",
                                "socCode": "47-2111.00",
                                "applicationStartDate": "2026-01-01",
                                "applicationEndDate": "2026-12-31",
                                "numberOfOpenings": 2,
                            },
                            {
                                "id": "upcoming",
                                "socCode": "47-2111.00",
                                "applicationStartDate": "2026-09-01",
                                "applicationEndDate": "2027-08-31",
                                "numberOfOpenings": 3,
                            },
                        ],
                    }
                ],
            }
        ]
    }

    stats = program_hiring_stats(
        program_group,
        today=date(2026, 8, 20),
    )

    assert stats == {
        "programs_hiring": 1,
        "open_positions": 5,
        "hiring_trade_names": ["Electrician"],
    }


def test_program_hiring_stats_excludes_expired_opportunities():
    program_group = {
        "trades": [
            {
                "tradeName": "Electrician",
                "programs": [
                    {
                        "programAk": 100,
                        "socCode": "47-2111.00",
                        "opportunities": [
                            {
                                "id": "expired",
                                "socCode": "47-2111.00",
                                "applicationEndDate": "2026-08-19",
                                "numberOfOpenings": 10,
                            }
                        ],
                    }
                ],
            }
        ]
    }

    stats = program_hiring_stats(
        program_group,
        today=date(2026, 8, 20),
    )

    assert stats == {
        "programs_hiring": 0,
        "open_positions": 0,
        "hiring_trade_names": [],
    }


def test_program_hiring_stats_includes_opportunity_ending_today():
    program_group = {
        "trades": [
            {
                "tradeName": "Electrician",
                "programs": [
                    {
                        "programAk": 100,
                        "socCode": "47-2111.00",
                        "opportunities": [
                            {
                                "id": "ends-today",
                                "socCode": "47-2111.00",
                                "applicationEndDate": "2026-08-20",
                                "numberOfOpenings": 4,
                            }
                        ],
                    }
                ],
            }
        ]
    }

    stats = program_hiring_stats(
        program_group,
        today=date(2026, 8, 20),
    )

    assert stats == {
        "programs_hiring": 1,
        "open_positions": 4,
        "hiring_trade_names": ["Electrician"],
    }


def test_program_hiring_stats_counts_program_once_with_multiple_opportunities():
    program_group = {
        "trades": [
            {
                "tradeName": "Electrician",
                "programs": [
                    {
                        "programAk": 100,
                        "socCode": "47-2111.00",
                        "opportunities": [
                            {
                                "id": "posting-one",
                                "socCode": "47-2111.00",
                                "applicationEndDate": "2026-12-31",
                                "numberOfOpenings": 8,
                            },
                            {
                                "id": "posting-two",
                                "socCode": "47-2111.00",
                                "applicationEndDate": "2027-12-31",
                                "numberOfOpenings": 10,
                            },
                        ],
                    }
                ],
            }
        ]
    }

    stats = program_hiring_stats(
        program_group,
        today=date(2026, 8, 20),
    )

    assert stats == {
        "programs_hiring": 1,
        "open_positions": 18,
        "hiring_trade_names": ["Electrician"],
    }


def test_program_hiring_stats_counts_multiple_hiring_programs():
    program_group = {
        "trades": [
            {
                "tradeName": "Electrician",
                "programs": [
                    {
                        "programAk": 100,
                        "socCode": "47-2111.00",
                        "opportunities": [
                            {
                                "id": "first-program",
                                "socCode": "47-2111.00",
                                "applicationEndDate": "2026-12-31",
                                "numberOfOpenings": 5,
                            }
                        ],
                    },
                    {
                        "programAk": 200,
                        "socCode": "47-2111.00",
                        "opportunities": [
                            {
                                "id": "second-program",
                                "socCode": "47-2111.00",
                                "applicationEndDate": "2027-01-31",
                                "numberOfOpenings": 7,
                            }
                        ],
                    },
                ],
            }
        ]
    }

    stats = program_hiring_stats(
        program_group,
        today=date(2026, 8, 20),
    )

    assert stats == {
        "programs_hiring": 2,
        "open_positions": 12,
        "hiring_trade_names": ["Electrician"],
    }


def test_program_hiring_stats_marks_each_hiring_trade():
    program_group = {
        "trades": [
            {
                "tradeName": "Electrician",
                "programs": [
                    {
                        "programAk": 100,
                        "socCode": "47-2111.00",
                        "opportunities": [
                            {
                                "id": "electrician",
                                "socCode": "47-2111.00",
                                "applicationEndDate": "2026-12-31",
                                "numberOfOpenings": 5,
                            }
                        ],
                    }
                ],
            },
            {
                "tradeName": "Plant Maintenance-Electrician",
                "programs": [
                    {
                        "programAk": 200,
                        "socCode": "47-2111.00",
                        "opportunities": [
                            {
                                "id": "maintenance",
                                "socCode": "47-2111.00",
                                "applicationEndDate": "2027-01-31",
                                "numberOfOpenings": 2,
                            }
                        ],
                    }
                ],
            },
            {
                "tradeName": "Electrical Maintenance Technician",
                "programs": [
                    {
                        "programAk": 300,
                        "socCode": "47-2111.00",
                        "opportunities": [],
                    }
                ],
            },
        ]
    }

    stats = program_hiring_stats(
        program_group,
        today=date(2026, 8, 20),
    )

    assert stats == {
        "programs_hiring": 2,
        "open_positions": 7,
        "hiring_trade_names": [
            "Electrician",
            "Plant Maintenance-Electrician",
        ],
    }


def test_program_hiring_stats_ignores_opportunity_for_different_soc():
    program_group = {
        "trades": [
            {
                "tradeName": "Plumber",
                "programs": [
                    {
                        "programAk": 100,
                        "socCode": "47-2152.00",
                        "opportunities": [
                            {
                                "id": "plumber",
                                "socCode": "47-2152.00",
                                "applicationEndDate": "2026-12-31",
                                "numberOfOpenings": 2,
                            },
                            {
                                "id": "glazier",
                                "socCode": "47-2121.00",
                                "applicationEndDate": "2026-12-31",
                                "numberOfOpenings": 4,
                            },
                        ],
                    }
                ],
            }
        ]
    }

    stats = program_hiring_stats(
        program_group,
        today=date(2026, 8, 20),
    )

    assert stats == {
        "programs_hiring": 1,
        "open_positions": 2,
        "hiring_trade_names": ["Plumber"],
    }


def test_program_hiring_stats_does_not_double_count_duplicate_opportunity_ids():
    program_group = {
        "trades": [
            {
                "tradeName": "Electrician",
                "programs": [
                    {
                        "programAk": 100,
                        "socCode": "47-2111.00",
                        "opportunities": [
                            {
                                "id": "same-opportunity",
                                "socCode": "47-2111.00",
                                "applicationEndDate": "2026-12-31",
                                "numberOfOpenings": 10,
                            },
                            {
                                "id": "same-opportunity",
                                "socCode": "47-2111.00",
                                "applicationEndDate": "2026-12-31",
                                "numberOfOpenings": 10,
                            },
                        ],
                    }
                ],
            }
        ]
    }

    stats = program_hiring_stats(
        program_group,
        today=date(2026, 8, 20),
    )

    assert stats == {
        "programs_hiring": 1,
        "open_positions": 10,
        "hiring_trade_names": ["Electrician"],
    }


def test_program_hiring_stats_handles_invalid_dates_and_opening_counts():
    program_group = {
        "trades": [
            {
                "tradeName": "Electrician",
                "programs": [
                    {
                        "programAk": 100,
                        "socCode": "47-2111.00",
                        "opportunities": [
                            {
                                "id": "missing-date",
                                "socCode": "47-2111.00",
                                "applicationEndDate": None,
                                "numberOfOpenings": 5,
                            },
                            {
                                "id": "invalid-date",
                                "socCode": "47-2111.00",
                                "applicationEndDate": "not-a-date",
                                "numberOfOpenings": 5,
                            },
                            {
                                "id": "invalid-openings",
                                "socCode": "47-2111.00",
                                "applicationEndDate": "2026-12-31",
                                "numberOfOpenings": "unknown",
                            },
                            {
                                "id": "negative-openings",
                                "socCode": "47-2111.00",
                                "applicationEndDate": "2026-12-31",
                                "numberOfOpenings": -5,
                            },
                        ],
                    }
                ],
            }
        ]
    }

    stats = program_hiring_stats(
        program_group,
        today=date(2026, 8, 20),
    )

    assert stats == {
        "programs_hiring": 1,
        "open_positions": 0,
        "hiring_trade_names": ["Electrician"],
    }


def test_program_hiring_stats_handles_empty_group():
    assert program_hiring_stats(
        None,
        today=date(2026, 8, 20),
    ) == {
        "programs_hiring": 0,
        "open_positions": 0,
        "hiring_trade_names": [],
    }


def test_program_hiring_stats_is_registered_as_template_filter():
    assert TEMPLATE_FILTERS["program_hiring_stats"] is program_hiring_stats


def test_trades_by_program_count_sorts_largest_first():
    trades = [
        {
            "displayTradeName": "Electrical Maintenance Technician",
            "programCount": 1,
        },
        {
            "displayTradeName": "Electrician",
            "programCount": 111,
        },
        {
            "displayTradeName": "Plant Maintenance-Electrician",
            "programCount": 29,
        },
        {
            "displayTradeName": "Electronics Mechanic",
            "programCount": 3,
        },
    ]

    sorted_trades = trades_by_program_count(trades)

    assert [trade["displayTradeName"] for trade in sorted_trades] == [
        "Electrician",
        "Plant Maintenance-Electrician",
        "Electronics Mechanic",
        "Electrical Maintenance Technician",
    ]


def test_trades_by_program_count_sorts_ties_alphabetically():
    trades = [
        {
            "displayTradeName": "Instrument and Electrical Mechanic",
            "programCount": 1,
        },
        {
            "displayTradeName": "Electrician",
            "programCount": 5,
        },
        {
            "displayTradeName": "Electrical Maintenance Technician",
            "programCount": 1,
        },
    ]

    sorted_trades = trades_by_program_count(trades)

    assert [trade["displayTradeName"] for trade in sorted_trades] == [
        "Electrician",
        "Electrical Maintenance Technician",
        "Instrument and Electrical Mechanic",
    ]
