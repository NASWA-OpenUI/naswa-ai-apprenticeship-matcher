from naswa_matcher.program_ranking import (
    build_program_summary,
    program_group_title,
)


def make_program_group(*, trades: list[dict] | None = None) -> dict:
    return {
        "socCode": "21-1093.00",
        "socTitle": "Social and Human Service Assistants",
        "programCount": 3,
        "regions": [
            "Capital Region",
            "Western New York",
        ],
        "onet": {
            "description": "Assist people in accessing social and community services.",
            "skills": {
                "data": {
                    "element": [
                        {"name": "Active Listening"},
                        {"name": "Social Perceptiveness"},
                        {"name": "Speaking"},
                    ]
                }
            },
            "detailed_work_activities": {
                "data": {
                    "activity": [
                        {
                            "title": (
                                "Help clients get needed services " "or resources."
                            )
                        },
                    ]
                }
            },
            "work_styles": {
                "data": {
                    "element": [
                        {"name": "Empathy"},
                        {"name": "Cooperation"},
                    ]
                }
            },
        },
        "trades": (
            trades
            if trades is not None
            else [
                {
                    "tradeName": "Direct Support Professional",
                    "displayTradeName": "Direct Support Professional",
                    "description": "Helps people with daily living and community support.",
                    "programCount": 3,
                    "programs": [
                        {
                            "programAk": 123,
                            "sponsorName": "Example Sponsor",
                        }
                    ],
                }
            ]
        ),
    }


def make_profile(
    *,
    location: str | None = "Buffalo",
    use_location_matching: bool = True,
) -> dict:
    return {
        "likes": ["helping people"],
        "dislikes": [],
        "location": location,
        "transportation": None,
        "use_location_matching": use_location_matching,
    }


def test_program_group_title_uses_trade_name_for_single_trade():
    group = make_program_group()

    assert program_group_title(group) == "Direct Support Professional"


def test_program_group_title_uses_soc_title_for_multiple_trades():
    group = make_program_group(
        trades=[
            {
                "tradeName": "Direct Support Professional",
                "displayTradeName": "Direct Support Professional",
                "description": "Supports people with daily living.",
            },
            {
                "tradeName": "Social Service Assistant",
                "displayTradeName": "Social Service Assistant",
                "description": "Connects people to social services.",
            },
        ]
    )

    assert program_group_title(group) == "Social and Human Service Assistants"


def test_build_program_summary_extracts_program_and_onet_fields():
    group = make_program_group()

    summary = build_program_summary(make_profile(), group)

    assert summary == {
        "id": "21-1093.00",
        "title": "Direct Support Professional",
        "soc_title": "Social and Human Service Assistants",
        "onet_description": (
            "Assist people in accessing social and community services."
        ),
        "skills": [
            "Active Listening",
            "Social Perceptiveness",
            "Speaking",
        ],
        "activities": [
            "Help clients get needed services or resources.",
        ],
        "work_styles": [
            "Empathy",
            "Cooperation",
        ],
        "trades": [
            {
                "trade_name": "Direct Support Professional",
                "description": (
                    "Helps people with daily living and community support."
                ),
            }
        ],
    }


def test_build_program_summary_excludes_individual_program_records():
    group = make_program_group()

    summary = build_program_summary(make_profile(), group)

    assert "programs" not in summary["trades"][0]
    assert "programCount" not in summary["trades"][0]
    assert "sponsorName" not in summary["trades"][0]


def test_build_program_summary_includes_every_trade_description():
    group = make_program_group(
        trades=[
            {
                "tradeName": "Trade A",
                "displayTradeName": "Trade A",
                "description": "Description A.",
            },
            {
                "tradeName": "Trade B",
                "displayTradeName": "Trade B",
                "description": "Description B.",
            },
            {
                "tradeName": "Trade C",
                "displayTradeName": "Trade C",
                "description": "Description C.",
            },
        ]
    )

    summary = build_program_summary(make_profile(), group)

    assert summary["trades"] == [
        {
            "trade_name": "Trade A",
            "description": "Description A.",
        },
        {
            "trade_name": "Trade B",
            "description": "Description B.",
        },
        {
            "trade_name": "Trade C",
            "description": "Description C.",
        },
    ]
