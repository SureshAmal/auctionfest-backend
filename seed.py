"""
Unified seed script for AuctionFest.

Seeds teams (30 named teams with unique 4-char passcodes), plots (98 plots),
policy cards (120 cards for rounds 2, 3, 5, 6), and the auction state.
All data is inline — no CSV files required.
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from database import _ensure_enum_values, engine
from models import AuctionState, AuctionStatus, Plot, PolicyCard, SQLModel, Team

# ---------------------------------------------------------------------------
# 31 Named Teams with unique 4-character passcodes
# ---------------------------------------------------------------------------
TEAMS_DATA = [
    {"name": "Titan", "passcode": "tn01"},
    {"name": "Crown", "passcode": "cw02"},
    {"name": "Apex", "passcode": "ax03"},
    {"name": "Prime", "passcode": "pm04"},
    {"name": "Summit", "passcode": "sm05"},
    {"name": "Atlas", "passcode": "at06"},
    {"name": "Legacy", "passcode": "lg07"},
    {"name": "Pinnacle", "passcode": "pc08"},
    {"name": "Sterling", "passcode": "st09"},
    {"name": "Royal", "passcode": "rl10"},
    {"name": "Vector", "passcode": "vc11"},
    {"name": "Valor", "passcode": "vl12"},
    {"name": "Imperial", "passcode": "im13"},
    {"name": "Noble", "passcode": "nb14"},
    {"name": "Citadel", "passcode": "cd15"},
    {"name": "Crest", "passcode": "cr16"},
    {"name": "Horizon", "passcode": "hz17"},
    {"name": "Hridaya", "passcode": "hr18"},
    {"name": "Triumph", "passcode": "tp19"},
    {"name": "Vertex", "passcode": "vx20"},
    {"name": "Frontier", "passcode": "ft21"},
    {"name": "Helios", "passcode": "hl22"},
    {"name": "Nova", "passcode": "nv23"},
    {"name": "Orbit", "passcode": "ob24"},
    {"name": "Keystone", "passcode": "ks25"},
    {"name": "Northstar", "passcode": "ns26"},
    {"name": "Landmark", "passcode": "lm27"},
    {"name": "Beacon", "passcode": "bc28"},
    {"name": "Empire", "passcode": "ep29"},
    {"name": "Regal", "passcode": "rg30"},
    {"name": "Skyline", "passcode": "sk31"},
    {"name": "suresh", "passcode": "sh09"},
    {"name": "mihir", "passcode": "mi75"},
]

# ---------------------------------------------------------------------------
# 98 Plot records (from PLANOMIC PLOT DETAILS)
# Fields: number, plot_type, total_area, actual_area, base_price, total_plot_price
# ---------------------------------------------------------------------------
PLOTS_DATA = [
    {
        "number": 1,
        "plot_type": "AGRICULTURE",
        "total_area": 13342,
        "actual_area": 9066,
        "base_price": 1500,
        "total_plot_price": 20013000,
    },
    {
        "number": 2,
        "plot_type": "RESIDENTIAL",
        "total_area": 30862,
        "actual_area": 26028,
        "base_price": 1500,
        "total_plot_price": 46293000,
    },
    {
        "number": 3,
        "plot_type": "AGRICULTURE",
        "total_area": 9193,
        "actual_area": 6874,
        "base_price": 1500,
        "total_plot_price": 13789500,
    },
    {
        "number": 4,
        "plot_type": "RESIDENTIAL",
        "total_area": 5919,
        "actual_area": 5784,
        "base_price": 1500,
        "total_plot_price": 8878500,
    },
    {
        "number": 5,
        "plot_type": "GOLF COURSE",
        "total_area": 43021,
        "actual_area": 29398,
        "base_price": 1500,
        "total_plot_price": 64531500,
    },
    {
        "number": 6,
        "plot_type": "RAILWAY STATION",
        "total_area": 34717,
        "actual_area": 14105,
        "base_price": 1500,
        "total_plot_price": 52075500,
    },
    {
        "number": 7,
        "plot_type": "RAILWAY STATION",
        "total_area": 25468,
        "actual_area": 17413,
        "base_price": 1500,
        "total_plot_price": 38202000,
    },
    {
        "number": 8,
        "plot_type": "MARKETING YARD",
        "total_area": 40162,
        "actual_area": 34001,
        "base_price": 1500,
        "total_plot_price": 60243000,
    },
    {
        "number": 9,
        "plot_type": "MARKETING YARD",
        "total_area": 12554,
        "actual_area": 9640,
        "base_price": 1500,
        "total_plot_price": 18831000,
    },
    {
        "number": 10,
        "plot_type": "RESIDENTIAL",
        "total_area": 40451,
        "actual_area": 34323,
        "base_price": 1500,
        "total_plot_price": 60676500,
    },
    {
        "number": 11,
        "plot_type": "HOTEL",
        "total_area": 34408,
        "actual_area": 26313,
        "base_price": 1500,
        "total_plot_price": 51612000,
    },
    {
        "number": 12,
        "plot_type": "SCHOOL",
        "total_area": 14557,
        "actual_area": 9955,
        "base_price": 1500,
        "total_plot_price": 21835500,
    },
    {
        "number": 13,
        "plot_type": "RESIDENTIAL",
        "total_area": 11473,
        "actual_area": 7659,
        "base_price": 1500,
        "total_plot_price": 17209500,
    },
    {
        "number": 14,
        "plot_type": "TEMPLE",
        "total_area": 13383,
        "actual_area": 9815,
        "base_price": 1500,
        "total_plot_price": 20074500,
    },
    {
        "number": 15,
        "plot_type": "RESIDENTIAL",
        "total_area": 13653,
        "actual_area": 9852,
        "base_price": 1500,
        "total_plot_price": 20479500,
    },
    {
        "number": 16,
        "plot_type": "GARDEN",
        "total_area": 5139,
        "actual_area": 3428,
        "base_price": 1500,
        "total_plot_price": 7708500,
    },
    {
        "number": 17,
        "plot_type": "RESIDENTIAL",
        "total_area": 5771,
        "actual_area": 3853,
        "base_price": 1500,
        "total_plot_price": 8656500,
    },
    {
        "number": 18,
        "plot_type": "SCHOOL",
        "total_area": 15541,
        "actual_area": 11019,
        "base_price": 1500,
        "total_plot_price": 23311500,
    },
    {
        "number": 19,
        "plot_type": "RESIDENTIAL",
        "total_area": 16664,
        "actual_area": 11765,
        "base_price": 1500,
        "total_plot_price": 24996000,
    },
    {
        "number": 20,
        "plot_type": "COMMERCIAL",
        "total_area": 15127,
        "actual_area": 11545,
        "base_price": 1500,
        "total_plot_price": 22690500,
    },
    {
        "number": 21,
        "plot_type": "GARDEN",
        "total_area": 7988,
        "actual_area": 5795,
        "base_price": 1500,
        "total_plot_price": 11982000,
    },
    {
        "number": 22,
        "plot_type": "BUS STATION",
        "total_area": 8444,
        "actual_area": 6153,
        "base_price": 1500,
        "total_plot_price": 12666000,
    },
    {
        "number": 23,
        "plot_type": "HOSPITAL",
        "total_area": 16410,
        "actual_area": 11858,
        "base_price": 1500,
        "total_plot_price": 24615000,
    },
    {
        "number": 24,
        "plot_type": "RAILWAY STATION",
        "total_area": 12052,
        "actual_area": 7790,
        "base_price": 1500,
        "total_plot_price": 18078000,
    },
    {
        "number": 25,
        "plot_type": "RESIDENTIAL",
        "total_area": 11774,
        "actual_area": 7782,
        "base_price": 1500,
        "total_plot_price": 17661000,
    },
    {
        "number": 26,
        "plot_type": "HAZARDOUS",
        "total_area": 20622,
        "actual_area": 14189,
        "base_price": 1500,
        "total_plot_price": 30933000,
    },
    {
        "number": 27,
        "plot_type": "RAILWAY STATION",
        "total_area": 11949,
        "actual_area": 8335,
        "base_price": 1500,
        "total_plot_price": 17923500,
    },
    {
        "number": 28,
        "plot_type": "METRO STATION",
        "total_area": 3347,
        "actual_area": 1731,
        "base_price": 1500,
        "total_plot_price": 5020500,
    },
    {
        "number": 29,
        "plot_type": "MERCHANTILE",
        "total_area": 5332,
        "actual_area": 3578,
        "base_price": 1500,
        "total_plot_price": 7998000,
    },
    {
        "number": 30,
        "plot_type": "RESIDENTIAL",
        "total_area": 9447,
        "actual_area": 4667,
        "base_price": 1500,
        "total_plot_price": 14170500,
    },
    {
        "number": 31,
        "plot_type": "SLUM AREA",
        "total_area": 5418,
        "actual_area": 3801,
        "base_price": 1500,
        "total_plot_price": 8127000,
    },
    {
        "number": 32,
        "plot_type": "METRO STATION",
        "total_area": 1179,
        "actual_area": 514,
        "base_price": 1500,
        "total_plot_price": 1768500,
    },
    {
        "number": 33,
        "plot_type": "HOSPITAL",
        "total_area": 1984,
        "actual_area": 970,
        "base_price": 1500,
        "total_plot_price": 2976000,
    },
    {
        "number": 34,
        "plot_type": "COMMERCIAL",
        "total_area": 2881,
        "actual_area": 1745,
        "base_price": 1500,
        "total_plot_price": 4321500,
    },
    {
        "number": 35,
        "plot_type": "MERCHANTILE",
        "total_area": 10166,
        "actual_area": 7189,
        "base_price": 1500,
        "total_plot_price": 15249000,
    },
    {
        "number": 36,
        "plot_type": "GOVERNMENT",
        "total_area": 10363,
        "actual_area": 6713,
        "base_price": 1500,
        "total_plot_price": 15544500,
    },
    {
        "number": 37,
        "plot_type": "RESIDENTIAL",
        "total_area": 15009,
        "actual_area": 11510,
        "base_price": 1500,
        "total_plot_price": 22513500,
    },
    {
        "number": 38,
        "plot_type": "GRAVEYARD",
        "total_area": 13701,
        "actual_area": 8135,
        "base_price": 1500,
        "total_plot_price": 20551500,
    },
    {
        "number": 39,
        "plot_type": "RESIDENTIAL",
        "total_area": 9258,
        "actual_area": 6729,
        "base_price": 1500,
        "total_plot_price": 13887000,
    },
    {
        "number": 40,
        "plot_type": "OFF STREET PARKING",
        "total_area": 11835,
        "actual_area": 8211,
        "base_price": 1500,
        "total_plot_price": 17752500,
    },
    {
        "number": 41,
        "plot_type": "GOVERNMENT",
        "total_area": 12655,
        "actual_area": 9209,
        "base_price": 1500,
        "total_plot_price": 18982500,
    },
    {
        "number": 42,
        "plot_type": "RESIDENTIAL",
        "total_area": 7213,
        "actual_area": 5343,
        "base_price": 1500,
        "total_plot_price": 10819500,
    },
    {
        "number": 43,
        "plot_type": "AFFORDABLE HOUSE SCHEME",
        "total_area": 13648,
        "actual_area": 9440,
        "base_price": 1500,
        "total_plot_price": 20472000,
    },
    {
        "number": 44,
        "plot_type": "HOTEL",
        "total_area": 14551,
        "actual_area": 11774,
        "base_price": 1500,
        "total_plot_price": 21826500,
    },
    {
        "number": 45,
        "plot_type": "AGRICULTURE",
        "total_area": 13275,
        "actual_area": 10484,
        "base_price": 1500,
        "total_plot_price": 19912500,
    },
    {
        "number": 46,
        "plot_type": "HAZARDOUS",
        "total_area": 16124,
        "actual_area": 10630,
        "base_price": 1500,
        "total_plot_price": 24186000,
    },
    {
        "number": 47,
        "plot_type": "GARDEN",
        "total_area": 6423,
        "actual_area": 4129,
        "base_price": 1500,
        "total_plot_price": 9634500,
    },
    {
        "number": 48,
        "plot_type": "RESIDENTIAL",
        "total_area": 10431,
        "actual_area": 8890,
        "base_price": 1500,
        "total_plot_price": 15646500,
    },
    {
        "number": 49,
        "plot_type": "SCHOOL",
        "total_area": 7256,
        "actual_area": 5614,
        "base_price": 1500,
        "total_plot_price": 10884000,
    },
    {
        "number": 50,
        "plot_type": "GARDEN",
        "total_area": 11738,
        "actual_area": 8603,
        "base_price": 1500,
        "total_plot_price": 17607000,
    },
    {
        "number": 51,
        "plot_type": "THEATRE",
        "total_area": 5109,
        "actual_area": 3738,
        "base_price": 1500,
        "total_plot_price": 7663500,
    },
    {
        "number": 52,
        "plot_type": "HOTEL",
        "total_area": 7992,
        "actual_area": 5771,
        "base_price": 1500,
        "total_plot_price": 11988000,
    },
    {
        "number": 53,
        "plot_type": "OFF STREET PARKING",
        "total_area": 13022,
        "actual_area": 8785,
        "base_price": 1500,
        "total_plot_price": 19533000,
    },
    {
        "number": 54,
        "plot_type": "RESIDENTIAL",
        "total_area": 6503,
        "actual_area": 3296,
        "base_price": 1500,
        "total_plot_price": 9754500,
    },
    {
        "number": 55,
        "plot_type": "FIRE STATION",
        "total_area": 6714,
        "actual_area": 4448,
        "base_price": 1500,
        "total_plot_price": 10071000,
    },
    {
        "number": 56,
        "plot_type": "COMMERCIAL",
        "total_area": 9984,
        "actual_area": 7061,
        "base_price": 1500,
        "total_plot_price": 14976000,
    },
    {
        "number": 57,
        "plot_type": "HOTEL",
        "total_area": 6247,
        "actual_area": 3705,
        "base_price": 1500,
        "total_plot_price": 9370500,
    },
    {
        "number": 58,
        "plot_type": "RESIDENTIAL",
        "total_area": 10148,
        "actual_area": 7484,
        "base_price": 1500,
        "total_plot_price": 15222000,
    },
    {
        "number": 59,
        "plot_type": "AFFORDABLE HOUSE SCHEME",
        "total_area": 10511,
        "actual_area": 6881,
        "base_price": 1500,
        "total_plot_price": 15766500,
    },
    {
        "number": 60,
        "plot_type": "BUS STATION",
        "total_area": 6229,
        "actual_area": 3954,
        "base_price": 1500,
        "total_plot_price": 9343500,
    },
    {
        "number": 61,
        "plot_type": "MERCHANTILE",
        "total_area": 13926,
        "actual_area": 10191,
        "base_price": 1500,
        "total_plot_price": 20889000,
    },
    {
        "number": 62,
        "plot_type": "GARDEN",
        "total_area": 15586,
        "actual_area": 10962,
        "base_price": 1500,
        "total_plot_price": 23379000,
    },
    {
        "number": 63,
        "plot_type": "CENTRAL LAKE",
        "total_area": 18246,
        "actual_area": 11658,
        "base_price": 1500,
        "total_plot_price": 27369000,
    },
    {
        "number": 64,
        "plot_type": "COMMERCIAL",
        "total_area": 7729,
        "actual_area": 5573,
        "base_price": 1500,
        "total_plot_price": 11593500,
    },
    {
        "number": 65,
        "plot_type": "RESIDENTIAL",
        "total_area": 11088,
        "actual_area": 7622,
        "base_price": 1500,
        "total_plot_price": 16632000,
    },
    {
        "number": 66,
        "plot_type": "SCHOOL",
        "total_area": 10119,
        "actual_area": 7293,
        "base_price": 1500,
        "total_plot_price": 15178500,
    },
    {
        "number": 67,
        "plot_type": "THEATRE",
        "total_area": 5132,
        "actual_area": 3135,
        "base_price": 1500,
        "total_plot_price": 7698000,
    },
    {
        "number": 68,
        "plot_type": "POLICE STATION",
        "total_area": 4590,
        "actual_area": 3198,
        "base_price": 1500,
        "total_plot_price": 6885000,
    },
    {
        "number": 69,
        "plot_type": "RESIDENTIAL",
        "total_area": 4243,
        "actual_area": 2936,
        "base_price": 1500,
        "total_plot_price": 6364500,
    },
    {
        "number": 70,
        "plot_type": "METRO STATION",
        "total_area": 4168,
        "actual_area": 2863,
        "base_price": 1500,
        "total_plot_price": 6252000,
    },
    {
        "number": 71,
        "plot_type": "HOSPITAL",
        "total_area": 7128,
        "actual_area": 4570,
        "base_price": 1500,
        "total_plot_price": 10692000,
    },
    {
        "number": 72,
        "plot_type": "RESIDENTIAL",
        "total_area": 9756,
        "actual_area": 6075,
        "base_price": 1500,
        "total_plot_price": 14634000,
    },
    {
        "number": 73,
        "plot_type": "GOVERNMENT",
        "total_area": 14632,
        "actual_area": 11366,
        "base_price": 1500,
        "total_plot_price": 21948000,
    },
    {
        "number": 74,
        "plot_type": "INDUSTRIAL",
        "total_area": 7960,
        "actual_area": 6592,
        "base_price": 1500,
        "total_plot_price": 11940000,
    },
    {
        "number": 75,
        "plot_type": "SLUM AREA",
        "total_area": 8394,
        "actual_area": 5503,
        "base_price": 1500,
        "total_plot_price": 12591000,
    },
    {
        "number": 76,
        "plot_type": "TEMPLE",
        "total_area": 8656,
        "actual_area": 6224,
        "base_price": 1500,
        "total_plot_price": 12984000,
    },
    {
        "number": 77,
        "plot_type": "ELECTRIC SUB STATION",
        "total_area": 9680,
        "actual_area": 6040,
        "base_price": 1500,
        "total_plot_price": 14520000,
    },
    {
        "number": 78,
        "plot_type": "SOLID WASTE SITE",
        "total_area": 11847,
        "actual_area": 7352,
        "base_price": 1500,
        "total_plot_price": 17770500,
    },
    {
        "number": 79,
        "plot_type": "WATER TREATMENT",
        "total_area": 10714,
        "actual_area": 7080,
        "base_price": 1500,
        "total_plot_price": 16071000,
    },
    {
        "number": 80,
        "plot_type": "HOTEL",
        "total_area": 8500,
        "actual_area": 4999,
        "base_price": 1500,
        "total_plot_price": 12750000,
    },
    {
        "number": 81,
        "plot_type": "METRO STATION",
        "total_area": 10071,
        "actual_area": 6355,
        "base_price": 1500,
        "total_plot_price": 15106500,
    },
    {
        "number": 82,
        "plot_type": "BUS STATION",
        "total_area": 12775,
        "actual_area": 11095,
        "base_price": 1500,
        "total_plot_price": 19162500,
    },
    {
        "number": 83,
        "plot_type": "MARKETING YARD",
        "total_area": 17830,
        "actual_area": 13344,
        "base_price": 1500,
        "total_plot_price": 26745000,
    },
    {
        "number": 84,
        "plot_type": "HOSPITAL",
        "total_area": 2629,
        "actual_area": 1845,
        "base_price": 1500,
        "total_plot_price": 3943500,
    },
    {
        "number": 85,
        "plot_type": "OFF STREET PARKING",
        "total_area": 8402,
        "actual_area": 4150,
        "base_price": 1500,
        "total_plot_price": 12603000,
    },
    {
        "number": 86,
        "plot_type": "GARDEN",
        "total_area": 12058,
        "actual_area": 8972,
        "base_price": 1500,
        "total_plot_price": 18087000,
    },
    {
        "number": 87,
        "plot_type": "GRAVEYARD",
        "total_area": 11123,
        "actual_area": 8420,
        "base_price": 1500,
        "total_plot_price": 16684500,
    },
    {
        "number": 88,
        "plot_type": "SCHOOL",
        "total_area": 10233,
        "actual_area": 7480,
        "base_price": 1500,
        "total_plot_price": 15349500,
    },
    {
        "number": 89,
        "plot_type": "METRO STATION",
        "total_area": 4550,
        "actual_area": 2861,
        "base_price": 1500,
        "total_plot_price": 6825000,
    },
    {
        "number": 90,
        "plot_type": "AGRICULTURE",
        "total_area": 5219,
        "actual_area": 3713,
        "base_price": 1500,
        "total_plot_price": 7828500,
    },
    {
        "number": 91,
        "plot_type": "GOVERNMENT",
        "total_area": 18455,
        "actual_area": 14902,
        "base_price": 1500,
        "total_plot_price": 27682500,
    },
    {
        "number": 92,
        "plot_type": "THEATRE",
        "total_area": 8077,
        "actual_area": 4478,
        "base_price": 1500,
        "total_plot_price": 12115500,
    },
    {
        "number": 93,
        "plot_type": "BUS STATION",
        "total_area": 10568,
        "actual_area": 8343,
        "base_price": 1500,
        "total_plot_price": 15852000,
    },
    {
        "number": 94,
        "plot_type": "METRO STATION",
        "total_area": 8312,
        "actual_area": 5065,
        "base_price": 1500,
        "total_plot_price": 12468000,
    },
    {
        "number": 95,
        "plot_type": "INDUSTRIAL",
        "total_area": 24620,
        "actual_area": 19859,
        "base_price": 1500,
        "total_plot_price": 36930000,
    },
    {
        "number": 96,
        "plot_type": "AIRPORT",
        "total_area": 13789,
        "actual_area": 11356,
        "base_price": 1500,
        "total_plot_price": 20683500,
    },
    {
        "number": 97,
        "plot_type": "AIRPORT",
        "total_area": 8359,
        "actual_area": 6453,
        "base_price": 1500,
        "total_plot_price": 12538500,
    },
    {
        "number": 98,
        "plot_type": "AGRICULTURE",
        "total_area": 14817,
        "actual_area": 10495,
        "base_price": 1500,
        "total_plot_price": 22225500,
    },
]

# ---------------------------------------------------------------------------
# 120 Policy Cards for rounds 2, 3, 5, 6 (30 questions per round)
# ---------------------------------------------------------------------------
POLICY_CARDS_DATA = [
    # Round 2
    {
        "round_id": 2,
        "question_id": 1,
        "policy_description": "Slum conditions worsen on Plot 31, so its value decreases by 30%, and nearby Plots 27, 33, 32, 35 decrease by 20%.",
    },
    {
        "round_id": 2,
        "question_id": 2,
        "policy_description": "Hazardous activity intensifies on Plot 26 (national highway), so its value decreases by 35%, and nearby Plots 19, 20, 25, 21 decrease by 22%.",
    },
    {
        "round_id": 2,
        "question_id": 3,
        "policy_description": "Central lake pollution increases on Plot 63 (river zone), so its value decreases by 28%, and nearby Plots 54, 55, 64, 66, 62, 61 decrease by 18%.",
    },
    {
        "round_id": 2,
        "question_id": 4,
        "policy_description": "New flyover junction opens near Plot 24 (railway track + flyover), so its value increases by 32%, and nearby Plots 25, 21, 23, 27 increase by 20%.",
    },
    {
        "round_id": 2,
        "question_id": 5,
        "policy_description": "Canal overflow affects Plot 79, so its value decreases by 34%, and nearby Plots 75, 71, 72, 60, 47, 46 decrease by 22%.",
    },
    {
        "round_id": 2,
        "question_id": 6,
        "policy_description": "Hazardous leakage reported at Plot 46 (canal + flyover + highway), so its value decreases by 36%, and nearby Plots 45, 48, 47 decrease by 22%.",
    },
    {
        "round_id": 2,
        "question_id": 7,
        "policy_description": "Metro interchange opens at Plot 81 (river + ring road), so its value increases by 30%, and nearby Plots 11, 62, 82 increase by 18%.",
    },
    {
        "round_id": 2,
        "question_id": 8,
        "policy_description": "Forest buffer is strengthened near Plot 5, so its value increases by 26%, and nearby Plots 3, 94 increase by 15%.",
    },
    {
        "round_id": 2,
        "question_id": 9,
        "policy_description": "Railway noise complaints rise at Plot 10 (railway + flyover + highway), so its value decreases by 24%, and nearby Plots 8, 9 decrease by 14%.",
    },
    {
        "round_id": 2,
        "question_id": 10,
        "policy_description": "Marketing yard congestion increases at Plot 8, so its value decreases by 21%, and nearby Plots 6, 7, 9 decrease by 13%.",
    },
    {
        "round_id": 2,
        "question_id": 11,
        "policy_description": "Airport night operations increase at Plot 96, so its value decreases by 28%, and nearby Plots 95, 97 decrease by 18%.",
    },
    {
        "round_id": 2,
        "question_id": 12,
        "policy_description": "Ring road service lane opens near Plot 93, so its value increases by 24%, and nearby Plots 81, 82 increase by 14%.",
    },
    {
        "round_id": 2,
        "question_id": 13,
        "policy_description": "Industrial emissions rise at Plot 74, so its value decreases by 31%, and nearby Plots 71, 73, 88 decrease by 20%.",
    },
    {
        "round_id": 2,
        "question_id": 14,
        "policy_description": "Garden redevelopment completes at Plot 47, so its value increases by 22%, and nearby Plots 48, 60 increase by 13%.",
    },
    {
        "round_id": 2,
        "question_id": 15,
        "policy_description": "Hospital trauma unit opens at Plot 71, so its value increases by 29%, and nearby Plots 72, 69, 70 increase by 17%.",
    },
    {
        "round_id": 2,
        "question_id": 16,
        "policy_description": "Graveyard expansion near Plot 38, so its value decreases by 23%, and nearby Plots 37, 41 decrease by 14%.",
    },
    {
        "round_id": 2,
        "question_id": 17,
        "policy_description": "Bus terminal congestion increases at Plot 22, so its value decreases by 19%, and nearby Plots 21, 23 decrease by 11%.",
    },
    {
        "round_id": 2,
        "question_id": 18,
        "policy_description": "Theatre renovation opens at Plot 51, so its value increases by 21%, and nearby Plots 38, 52 increase by 12%.",
    },
    {
        "round_id": 2,
        "question_id": 19,
        "policy_description": "Solid waste odour rises at Plot 78 (river + highway), so its value decreases by 33%, and nearby Plots 77, 80 decrease by 21%.",
    },
    {
        "round_id": 2,
        "question_id": 20,
        "policy_description": "Police station expansion improves safety at Plot 68, so its value increases by 25%, and nearby Plots 65, 67, 69 increase by 15%.",
    },
    {
        "round_id": 2,
        "question_id": 21,
        "policy_description": "Government office complex opens at Plot 36 (railway + ring road), so its value increases by 27%, and nearby Plots 35, 37, 53 increase by 17%.",
    },
    {
        "round_id": 2,
        "question_id": 22,
        "policy_description": "Off-street parking shortage occurs at Plot 40, so its value decreases by 18%, and nearby Plots 39, 41 decrease by 11%.",
    },
    {
        "round_id": 2,
        "question_id": 23,
        "policy_description": "Hotel convention centre opens at Plot 57, so its value increases by 23%, and nearby Plots 56, 65 increase by 14%.",
    },
    {
        "round_id": 2,
        "question_id": 24,
        "policy_description": "Metro construction noise increases at Plot 70, so its value decreases by 20%, and nearby Plots 69, 71 decrease by 12%.",
    },
    {
        "round_id": 2,
        "question_id": 25,
        "policy_description": "Water treatment breakdown occurs at Plot 79, so its value decreases by 32%, and nearby Plot 80 decreases by 20%.",
    },
    {
        "round_id": 2,
        "question_id": 26,
        "policy_description": "Temple festival crowd improves footfall at Plot 76, so its value increases by 24%, and nearby Plots 75, 78 increase by 14%.",
    },
    {
        "round_id": 2,
        "question_id": 27,
        "policy_description": "Commercial complex opens at Plot 64, so its value increases by 22%, and nearby Plots 63, 66 increase by 13%.",
    },
    {
        "round_id": 2,
        "question_id": 28,
        "policy_description": "Agricultural land flooding affects Plot 90, so its value decreases by 26%, and nearby Plots 86, 89 decrease by 16%.",
    },
    {
        "round_id": 2,
        "question_id": 29,
        "policy_description": "Fire station response time improves at Plot 55, so its value increases by 28%, and nearby Plots 54, 52 increase by 17%.",
    },
    {
        "round_id": 2,
        "question_id": 30,
        "policy_description": "Airport cargo terminal opens at Plot 97, so its value increases by 31%, and nearby Plots 95, 96 increase by 19%.",
    },
    # Round 3
    {
        "round_id": 3,
        "question_id": 1,
        "policy_description": "Metro station crowd spillover increases at Plot 32, so its value increases by 24%, and nearby Plots 31 and 33 increase by 14%.",
    },
    {
        "round_id": 3,
        "question_id": 2,
        "policy_description": "Slum fire incident occurs at Plot 75, so its value decreases by 33%, and nearby Plots 71, 76, 80 decrease by 20%.",
    },
    {
        "round_id": 3,
        "question_id": 3,
        "policy_description": "Hazardous waste transport intensifies at Plot 26 (highway + canal side), so its value decreases by 34%, and nearby Plots 25 and 21 decrease by 22%.",
    },
    {
        "round_id": 3,
        "question_id": 4,
        "policy_description": "Riverfront promenade opens at Plot 30 (river + flyover zone), so its value increases by 29%, and nearby Plots 29, 37, 39 increase by 18%.",
    },
    {
        "round_id": 3,
        "question_id": 5,
        "policy_description": "Ring road entry ramp opens near Plot 61, so its value increases by 23%, and nearby Plots 12 and 62 increase by 14%.",
    },
    {
        "round_id": 3,
        "question_id": 6,
        "policy_description": "Railway vibration issues rise at Plot 15, so its value decreases by 21%, and nearby Plots 13 and 14 decrease by 13%.",
    },
    {
        "round_id": 3,
        "question_id": 7,
        "policy_description": "Canal embankment breach affects Plot 60, so its value decreases by 27%, and nearby Plots 47 and 59 decrease by 17%.",
    },
    {
        "round_id": 3,
        "question_id": 8,
        "policy_description": "Forest buffer fencing improves near Plot 92, so its value increases by 25%, and nearby Plots 91 and 93 increase by 16%.",
    },
    {
        "round_id": 3,
        "question_id": 9,
        "policy_description": "Flyover ramp congestion worsens at Plot 52, so its value decreases by 19%, and nearby Plots 38 and 54 decrease by 12%.",
    },
    {
        "round_id": 3,
        "question_id": 10,
        "policy_description": "National highway noise barriers installed near Plot 39, so its value increases by 22%, and nearby Plot 40 increases by 13%.",
    },
    {
        "round_id": 3,
        "question_id": 11,
        "policy_description": "New bus terminal opens at Plot 60, so its value increases by 26%, and nearby Plots 59 and 47 increase by 16%.",
    },
    {
        "round_id": 3,
        "question_id": 12,
        "policy_description": "Hospital diagnostic wing opens at Plot 33, so its value increases by 28%, and nearby Plots 28 and 34 increase by 17%.",
    },
    {
        "round_id": 3,
        "question_id": 13,
        "policy_description": "Industrial logistics hub expands at Plot 95 (highway zone), so its value increases by 24%, and nearby Plots 96 and 91 increase by 15%.",
    },
    {
        "round_id": 3,
        "question_id": 14,
        "policy_description": "Metro line extension causes construction dust at Plot 89, so its value decreases by 18%, and nearby Plots 87 and 90 decrease by 11%.",
    },
    {
        "round_id": 3,
        "question_id": 15,
        "policy_description": "Central lake boating zone opens at Plot 63 (river zone), so its value increases by 31%, and nearby Plots 62 and 64 increase by 19%.",
    },
    {
        "round_id": 3,
        "question_id": 16,
        "policy_description": "Marketing yard traffic increases at Plot 83 (river + ring road), so its value decreases by 20%, and nearby Plots 66 and 85 decrease by 12%.",
    },
    {
        "round_id": 3,
        "question_id": 17,
        "policy_description": "School campus expansion at Plot 66 increases demand, so its value increases by 27%, and nearby Plots 63 and 65 increase by 16%.",
    },
    {
        "round_id": 3,
        "question_id": 18,
        "policy_description": "Garden walking trail opens at Plot 86, so its value increases by 23%, and nearby Plots 85 and 90 increase by 14%.",
    },
    {
        "round_id": 3,
        "question_id": 19,
        "policy_description": "Industrial wastewater incident at Plot 74, so its value decreases by 29%, and nearby Plots 73 and 71 decrease by 18%.",
    },
    {
        "round_id": 3,
        "question_id": 20,
        "policy_description": "Ring road service market opens near Plot 57, so its value increases by 21%, and nearby Plots 56 and 58 increase by 13%.",
    },
    {
        "round_id": 3,
        "question_id": 21,
        "policy_description": "Railway station plaza opens at Plot 27 (rail + flyover), so its value increases by 26%, and nearby Plots 24 and 35 increase by 16%.",
    },
    {
        "round_id": 3,
        "question_id": 22,
        "policy_description": "Airport fuel depot upgrade at Plot 97 increases activity, so its value increases by 22%, and nearby Plot 98 increases by 13%.",
    },
    {
        "round_id": 3,
        "question_id": 23,
        "policy_description": "Graveyard access road opens near Plot 87, so its value increases by 18%, and nearby Plot 86 increases by 11%.",
    },
    {
        "round_id": 3,
        "question_id": 24,
        "policy_description": "Government e-service centre opens at Plot 73, so its value increases by 24%, and nearby Plots 70 and 71 increase by 14%.",
    },
    {
        "round_id": 3,
        "question_id": 25,
        "policy_description": "Off-street parking pricing hikes at Plot 53, so its value decreases by 17%, and nearby Plot 48 decreases by 10%.",
    },
    {
        "round_id": 3,
        "question_id": 26,
        "policy_description": "Riverbank erosion affects Plot 85, so its value decreases by 28%, and nearby Plots 83 and 66 decrease by 17%.",
    },
    {
        "round_id": 3,
        "question_id": 27,
        "policy_description": "Temple redevelopment improves surroundings at Plot 14, so its value increases by 20%, and nearby Plots 15 and 17 increase by 12%.",
    },
    {
        "round_id": 3,
        "question_id": 28,
        "policy_description": "Commercial street upgrade at Plot 56 increases footfall, so its value increases by 25%, and nearby Plots 50 and 52 increase by 15%.",
    },
    {
        "round_id": 3,
        "question_id": 29,
        "policy_description": "Canal-side green buffer added at Plot 46, so its value increases by 23%, and nearby Plot 47 increases by 14%.",
    },
    {
        "round_id": 3,
        "question_id": 30,
        "policy_description": "Railway track sound barriers installed near Plot 11, so its value increases by 21%, and nearby Plots 10 and 13 increase by 13%.",
    },
    # Round 5
    {
        "round_id": 5,
        "question_id": 1,
        "policy_description": "Agriculture land conversion pressure rises at Plot 1 (highway zone), so its value decreases by 18%, and nearby Plots 2 and 7 decrease by 10%.",
    },
    {
        "round_id": 5,
        "question_id": 2,
        "policy_description": "Residential demand increases near Plot 2 (highway access improves), so its value increases by 22%, and nearby Plots 1 and 4 increase by 13%.",
    },
    {
        "round_id": 5,
        "question_id": 3,
        "policy_description": "River flooding damages crops at Plot 3, so its value decreases by 24%, and nearby Plot 2 decreases by 14%.",
    },
    {
        "round_id": 5,
        "question_id": 4,
        "policy_description": "Garden upgrade improves livability at Plot 16, so its value increases by 26%, and nearby Plots 17 and 18 increase by 15%.",
    },
    {
        "round_id": 5,
        "question_id": 5,
        "policy_description": "Temple crowd management issues arise at Plot 14 (flyover + rail corridor), so its value decreases by 17%, and nearby Plots 13 and 15 decrease by 10%.",
    },
    {
        "round_id": 5,
        "question_id": 6,
        "policy_description": "School ranking improves at Plot 12 (ring road zone), so its value increases by 23%, and nearby Plots 11 and 13 increase by 14%.",
    },
    {
        "round_id": 5,
        "question_id": 7,
        "policy_description": "Hotel over-supply affects Plot 44, so its value decreases by 20%, and nearby Plots 42 and 45 decrease by 12%.",
    },
    {
        "round_id": 5,
        "question_id": 8,
        "policy_description": "Government office crowding reduces appeal at Plot 41, so its value decreases by 16%, and nearby Plots 39 and 42 decrease by 9%.",
    },
    {
        "round_id": 5,
        "question_id": 9,
        "policy_description": "Off-street parking pricing becomes affordable at Plot 53, so its value increases by 21%, and nearby Plots 36 and 54 increase by 13%.",
    },
    {
        "round_id": 5,
        "question_id": 10,
        "policy_description": "Fire station response time upgrade improves safety at Plot 55, so its value increases by 28%, and nearby Plots 54 and 52 increase by 17%.",
    },
    {
        "round_id": 5,
        "question_id": 11,
        "policy_description": "Commercial zoning relaxation boosts Plot 20, so its value increases by 24%, and nearby Plots 21 and 22 increase by 14%.",
    },
    {
        "round_id": 5,
        "question_id": 12,
        "policy_description": "Bus terminal overcrowding reduces appeal at Plot 22, so its value decreases by 19%, and nearby Plots 21 and 23 decrease by 11%.",
    },
    {
        "round_id": 5,
        "question_id": 13,
        "policy_description": "Marketing yard hygiene drive improves Plot 9, so its value increases by 20%, and nearby Plots 8 and 11 increase by 12%.",
    },
    {
        "round_id": 5,
        "question_id": 14,
        "policy_description": "Metro feeder road opens near Plot 28, so its value increases by 27%, and nearby Plots 29 and 33 increase by 16%.",
    },
    {
        "round_id": 5,
        "question_id": 15,
        "policy_description": "Railway siding expansion causes noise at Plot 7, so its value decreases by 18%, and nearby Plots 6 and 8 decrease by 11%.",
    },
    {
        "round_id": 5,
        "question_id": 16,
        "policy_description": "Garden encroachment issue affects Plot 21, so its value decreases by 14%, and nearby Plot 25 decreases by 8%.",
    },
    {
        "round_id": 5,
        "question_id": 17,
        "policy_description": "Industrial safety audit improves Plot 95, so its value increases by 26%, and nearby Plots 91 and 97 increase by 16%.",
    },
    {
        "round_id": 5,
        "question_id": 18,
        "policy_description": "Airport cargo traffic causes congestion at Plot 98, so its value decreases by 22%, and nearby Plot 97 decreases by 13%.",
    },
    {
        "round_id": 5,
        "question_id": 19,
        "policy_description": "Affordable housing maintenance drive improves Plot 59, so its value increases by 19%, and nearby Plots 58 and 60 increase by 11%.",
    },
    {
        "round_id": 5,
        "question_id": 20,
        "policy_description": "Metro line timetable reduction affects Plot 70, so its value decreases by 16%, and nearby Plots 69 and 71 decrease by 9%.",
    },
    {
        "round_id": 5,
        "question_id": 21,
        "policy_description": "Police patrol frequency increases at Plot 68, so its value increases by 24%, and nearby Plots 65 and 67 increase by 14%.",
    },
    {
        "round_id": 5,
        "question_id": 22,
        "policy_description": "Theatre footfall drops at Plot 67, so its value decreases by 15%, and nearby Plots 65 and 72 decrease by 9%.",
    },
    {
        "round_id": 5,
        "question_id": 23,
        "policy_description": "Water treatment odour complaints affect Plot 79, so its value decreases by 31%, and nearby Plots 80 and 78 decrease by 20%.",
    },
    {
        "round_id": 5,
        "question_id": 24,
        "policy_description": "Canal-side walkway opens near Plot 72, so its value increases by 23%, and nearby Plots 71 and 59 increase by 14%.",
    },
    {
        "round_id": 5,
        "question_id": 25,
        "policy_description": "Solid waste segregation plant upgrade improves Plot 78, so its value increases by 21%, and nearby Plots 77 and 80 increase by 13%.",
    },
    {
        "round_id": 5,
        "question_id": 26,
        "policy_description": "Government service centre relocation reduces activity at Plot 91, so its value decreases by 17%, and nearby Plot 92 decreases by 10%.",
    },
    {
        "round_id": 5,
        "question_id": 27,
        "policy_description": "Commercial street lighting upgrade improves Plot 34, so its value increases by 22%, and nearby Plots 29 and 30 increase by 13%.",
    },
    {
        "round_id": 5,
        "question_id": 28,
        "policy_description": "Residential density cap reduces returns at Plot 65, so its value decreases by 14%, and nearby Plots 64 and 66 decrease by 9%.",
    },
    {
        "round_id": 5,
        "question_id": 29,
        "policy_description": "Garden event series boosts footfall at Plot 86, so its value increases by 20%, and nearby Plots 87 and 90 increase by 12%.",
    },
    {
        "round_id": 5,
        "question_id": 30,
        "policy_description": "Railway track maintenance work disrupts access at Plot 9, so its value decreases by 16%, and nearby Plot 10 decreases by 9%.",
    },
    # Round 6
    {
        "round_id": 6,
        "question_id": 1,
        "policy_description": "New agriculture cold-storage opens near Plot 3, so its value increases by 18%, and nearby Plot 5 increases by 10%.",
    },
    {
        "round_id": 6,
        "question_id": 2,
        "policy_description": "Residential noise complaints rise near the railway at Plot 6, so its value decreases by 21%, and nearby Plots 7 and 9 decrease by 13%.",
    },
    {
        "round_id": 6,
        "question_id": 3,
        "policy_description": "Riverbank beautification improves access at Plot 37, so its value increases by 24%, and nearby Plots 30 and 38 increase by 15%.",
    },
    {
        "round_id": 6,
        "question_id": 4,
        "policy_description": "Garden maintenance lapses at Plot 21, so its value decreases by 14%, and nearby Plots 22 and 23 decrease by 8%.",
    },
    {
        "round_id": 6,
        "question_id": 5,
        "policy_description": "Metro feeder shuttle launches at Plot 32, so its value increases by 26%, and nearby Plots 29 and 33 increase by 16%.",
    },
    {
        "round_id": 6,
        "question_id": 6,
        "policy_description": "Commercial street flooding affects Plot 20, so its value decreases by 19%, and nearby Plots 21 and 22 decrease by 11%.",
    },
    {
        "round_id": 6,
        "question_id": 7,
        "policy_description": "Temple access road widening improves Plot 76, so its value increases by 23%, and nearby Plots 75 and 78 increase by 14%.",
    },
    {
        "round_id": 6,
        "question_id": 8,
        "policy_description": "Industrial safety drill disrupts access at Plot 95, so its value decreases by 17%, and nearby Plots 91 and 97 decrease by 10%.",
    },
    {
        "round_id": 6,
        "question_id": 9,
        "policy_description": "Hospital parking shortage affects Plot 84, so its value decreases by 15%, and nearby Plots 83 and 85 decrease by 9%.",
    },
    {
        "round_id": 6,
        "question_id": 10,
        "policy_description": "Marketing yard digital auction hub opens at Plot 83, so its value increases by 22%, and nearby Plots 82 and 66 increase by 13%.",
    },
    {
        "round_id": 6,
        "question_id": 11,
        "policy_description": "Ring road exit signage improves access at Plot 57, so its value increases by 20%, and nearby Plots 56 and 58 increase by 12%.",
    },
    {
        "round_id": 6,
        "question_id": 12,
        "policy_description": "Water treatment maintenance causes odour at Plot 79, so its value decreases by 29%, and nearby Plots 78 and 80 decrease by 18%.",
    },
    {
        "round_id": 6,
        "question_id": 13,
        "policy_description": "Bus terminal route expansion benefits Plot 93, so its value increases by 24%, and nearby Plots 81 and 82 increase by 15%.",
    },
    {
        "round_id": 6,
        "question_id": 14,
        "policy_description": "Airport security restrictions limit access at Plot 96, so its value decreases by 18%, and nearby Plots 95 and 97 decrease by 11%.",
    },
    {
        "round_id": 6,
        "question_id": 15,
        "policy_description": "Government service backlog reduces footfall at Plot 41, so its value decreases by 16%, and nearby Plots 42 and 39 decrease by 10%.",
    },
    {
        "round_id": 6,
        "question_id": 16,
        "policy_description": "Theatre festival season boosts Plot 92, so its value increases by 25%, and nearby Plots 91 and 93 increase by 16%.",
    },
    {
        "round_id": 6,
        "question_id": 17,
        "policy_description": "Affordable housing renovation improves Plot 43, so its value increases by 21%, and nearby Plots 40 and 44 increase by 13%.",
    },
    {
        "round_id": 6,
        "question_id": 18,
        "policy_description": "Graveyard boundary wall construction causes disruption at Plot 87, so its value decreases by 19%, and nearby Plots 86 and 90 decrease by 12%.",
    },
    {
        "round_id": 6,
        "question_id": 19,
        "policy_description": "Garden water feature opens at Plot 50, so its value increases by 23%, and nearby Plots 49 and 51 increase by 14%.",
    },
    {
        "round_id": 6,
        "question_id": 20,
        "policy_description": "Metro maintenance shutdown affects Plot 94, so its value decreases by 17%, and nearby Plots 81 and 93 decrease by 10%.",
    },
    {
        "round_id": 6,
        "question_id": 21,
        "policy_description": "Hotel conference demand drops at Plot 44, so its value decreases by 16%, and nearby Plots 42 and 45 decrease by 10%.",
    },
    {
        "round_id": 6,
        "question_id": 22,
        "policy_description": "School expansion creates traffic near Plot 66, so its value decreases by 14%, and nearby Plots 65 and 63 decrease by 9%.",
    },
    {
        "round_id": 6,
        "question_id": 23,
        "policy_description": "Fire station equipment upgrade improves safety at Plot 55, so its value increases by 27%, and nearby Plots 54 and 52 increase by 17%.",
    },
    {
        "round_id": 6,
        "question_id": 24,
        "policy_description": "Industrial truck curfew improves air quality at Plot 74, so its value increases by 19%, and nearby Plots 73 and 71 increase by 11%.",
    },
    {
        "round_id": 6,
        "question_id": 25,
        "policy_description": "Central lake water sports event boosts Plot 63, so its value increases by 28%, and nearby Plots 62 and 64 increase by 17%.",
    },
    {
        "round_id": 6,
        "question_id": 26,
        "policy_description": "Off-street parking fee hike affects Plot 85, so its value decreases by 18%, and nearby Plots 65 and 66 decrease by 11%.",
    },
    {
        "round_id": 6,
        "question_id": 27,
        "policy_description": "Police surveillance cameras improve safety at Plot 68, so its value increases by 22%, and nearby Plots 67 and 69 increase by 13%.",
    },
    {
        "round_id": 6,
        "question_id": 28,
        "policy_description": "Canal silt removal improves access at Plot 47, so its value increases by 21%, and nearby Plots 46 and 60 increase by 13%.",
    },
    {
        "round_id": 6,
        "question_id": 29,
        "policy_description": "Forest buffer expansion restricts development near Plot 5, so its value decreases by 20%, and nearby Plots 3 and 92 decrease by 12%.",
    },
    {
        "round_id": 6,
        "question_id": 30,
        "policy_description": "Airport runway lighting upgrade improves connectivity at Plot 97, so its value increases by 26%, and nearby Plots 96 and 98 increase by 16%.",
    },
]


async def seed():
    """Drop all tables, recreate schema, and seed all data (teams, plots, policy cards, auction state).

    This is a destructive operation — all existing data will be lost.
    """
    print("Resetting database...")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
        _ensure_enum_values(conn)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # --- Teams ---
        print(f"Seeding {len(TEAMS_DATA)} teams...")
        teams = [
            Team(name=t["name"], passcode=t["passcode"], budget=500000000)
            for t in TEAMS_DATA
        ]
        session.add_all(teams)

        # --- Plots ---
        print(f"Seeding {len(PLOTS_DATA)} plots...")
        plots = [
            Plot(
                number=p["number"],
                plot_type=p["plot_type"],
                total_area=p["total_area"],
                actual_area=p["actual_area"],
                base_price=p["base_price"],
                total_plot_price=p["total_plot_price"],
                current_bid=None,
                purchase_price=None,
                status="pending",
            )
            for p in PLOTS_DATA
        ]
        session.add_all(plots)

        # --- Policy Cards ---
        print(f"Seeding {len(POLICY_CARDS_DATA)} policy cards...")
        cards = [
            PolicyCard(
                round_id=c["round_id"],
                question_id=c["question_id"],
                policy_description=c["policy_description"],
            )
            for c in POLICY_CARDS_DATA
        ]
        session.add_all(cards)

        # --- Auction State ---
        print("Seeding Auction State...")
        state = AuctionState(
            id=1, current_plot_number=1, status=AuctionStatus.NOT_STARTED, admin_forced_theme=False
        )
        session.add(state)

        await session.commit()
        print("Seeding Complete! ✅")
        print(f"  → {len(teams)} teams")
        print(f"  → {len(plots)} plots")
        print(f"  → {len(cards)} policy cards")
        print(f"  → 1 auction state")


if __name__ == "__main__":
    asyncio.run(seed())
