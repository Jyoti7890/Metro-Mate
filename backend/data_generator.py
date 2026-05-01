import random
from datetime import date, timedelta

try:
    from .db import supabase
except ImportError:
    from db import supabase

TOURIST_STATIONS = {
    "Taj Mahal", "Taj East Gate", "Fatehabad Road",
    "Mankameshwar Mandir", "Guru Ka Taal"
}
TRANSPORT_STATIONS = {"Agra Cantt", "ISBT", "Raja Ki Mandi", "Sikandra"}
OFFICE_STATIONS = {"Sanjay Place", "MG Road", "Collectorate"}
MARKET_STATIONS = {"Sadar Bazaar", "Hariparvat Chauraha", "Agra Mandi", "Dr. Ambedkar Chowk"}
STUDENT_STATIONS = {"Agra College", "RBS College", "Medical College"}
INDUSTRIAL_STATIONS = {"Foundary Nagar"}


def get_station_type(name: str) -> str:
    if name in TOURIST_STATIONS:
        return "tourist"
    if name in TRANSPORT_STATIONS:
        return "transport"
    if name in OFFICE_STATIONS:
        return "office"
    if name in MARKET_STATIONS:
        return "market"
    if name in STUDENT_STATIONS:
        return "student"
    if name in INDUSTRIAL_STATIONS:
        return "industrial"
    return "residential"


def get_weather(month: int) -> str:
    if month in [12, 1]:
        return random.choices(["Clear", "Fog", "Rainy"], weights=[50, 35, 15])[0]
    if month in [7, 8]:
        return random.choices(["Clear", "Cloudy", "Rainy"], weights=[30, 20, 50])[0]
    return random.choices(["Clear", "Cloudy", "Rainy"], weights=[65, 20, 15])[0]


def is_holiday(d: date) -> bool:
    fixed_holidays = {(1, 26), (8, 15), (10, 2)}
    return (d.month, d.day) in fixed_holidays


def nearby_event(station_type: str) -> bool:
    if station_type in {"tourist", "market"}:
        return random.random() < 0.10
    return random.random() < 0.03


def base_by_station_type(station_type: str) -> int:
    mapping = {
        "tourist": 150,
        "transport": 170,
        "office": 130,
        "market": 120,
        "student": 110,
        "industrial": 100,
        "residential": 80,
    }
    return mapping.get(station_type, 80)


def hour_effect(hour: int, station_type: str) -> int:
    # Night
    if 0 <= hour <= 5:
        return -80

    # Early morning
    if 6 <= hour <= 7:
        return 20 if station_type in {"transport", "office", "student"} else 5

    # Morning peak
    if 8 <= hour <= 10:
        if station_type in {"transport", "office", "student"}:
            return 90
        if station_type == "tourist":
            return 40
        return 50

    # Midday
    if 11 <= hour <= 16:
        if station_type == "tourist":
            return 110
        if station_type == "market":
            return 50
        if station_type == "office":
            return 20
        return 15

    # Evening peak
    if 17 <= hour <= 20:
        if station_type in {"transport", "office"}:
            return 100
        if station_type == "market":
            return 60
        return 40

    # Late evening
    return -10


def weekend_effect(is_weekend: bool, station_type: str) -> int:
    if not is_weekend:
        return 0

    if station_type in {"office", "student", "industrial"}:
        return -35
    if station_type == "tourist":
        return 50
    if station_type == "market":
        return 20
    return 5


def weather_effect(weather: str, hour: int) -> int:
    if weather == "Rainy":
        return -25
    if weather == "Fog" and 6 <= hour <= 10:
        return -20
    return 0


def holiday_effect(is_holiday_flag: bool, station_type: str) -> int:
    if not is_holiday_flag:
        return 0

    if station_type == "tourist":
        return 45
    if station_type in {"office", "student", "industrial"}:
        return -30
    return 10


def interchange_effect(is_interchange: bool) -> int:
    return 35 if is_interchange else 0


def elevated_effect(is_elevated: bool) -> int:
    return 5 if is_elevated else 0


def event_effect(has_event: bool, station_type: str) -> int:
    if not has_event:
        return 0
    if station_type in {"tourist", "market"}:
        return 60
    return 20


def determine_crowd_level(crowd_count: int) -> str:
    if crowd_count < 100:
        return "Low"
    if crowd_count < 220:
        return "Medium"
    return "High"


def build_crowd_row(station: dict, d: date, hour: int) -> dict:
    name = station["name"]
    line = station.get("line")
    sequence = station.get("sequence")
    is_interchange = station.get("is_interchange", False)
    is_elevated = station.get("is_elevated", False)

    station_type = get_station_type(name)
    weather = get_weather(d.month)
    weekend = d.weekday() >= 5
    holiday_flag = is_holiday(d)
    event_flag = nearby_event(station_type)

    base = base_by_station_type(station_type)
    crowd = (
        base
        + hour_effect(hour, station_type)
        + weekend_effect(weekend, station_type)
        + weather_effect(weather, hour)
        + holiday_effect(holiday_flag, station_type)
        + interchange_effect(is_interchange)
        + elevated_effect(is_elevated)
        + event_effect(event_flag, station_type)
        + random.randint(-12, 12)
    )

    crowd = max(crowd, 10)

    # Split crowd into entries/exits with slight variation
    estimated_entries = int(crowd * random.uniform(0.48, 0.55))
    estimated_exits = max(crowd - estimated_entries, 0)
    crowd_level = determine_crowd_level(crowd)

    return {
        "station_name": name,
        "line": line,
        "sequence": sequence,
        "date": d.isoformat(),
        "hour": hour,
        "day_name": d.strftime("%A"),
        "is_weekend": weekend,
        "is_holiday": holiday_flag,
        "weather": weather,
        "station_type": station_type,
        "is_interchange": is_interchange,
        "is_elevated": is_elevated,
        "nearby_event": event_flag,
        "estimated_entries": estimated_entries,
        "estimated_exits": estimated_exits,
        "crowd_count": crowd,
        "crowd_level": crowd_level,
    }


def fetch_stations():
    response = supabase.table("stations").select("*").execute()
    return response.data


def insert_rows_in_batches(rows, batch_size=500):
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        supabase.table("crowd_history").insert(batch).execute()
        print(f"Inserted rows: {i + len(batch)} / {len(rows)}")


def generate_crowd_history(days_back: int = 60):
    stations = fetch_stations()
    all_rows = []

    start_date = date.today() - timedelta(days=days_back)

    for offset in range(days_back):
        current_date = start_date + timedelta(days=offset)
        for station in stations:
            for hour in range(24):
                row = build_crowd_row(station, current_date, hour)
                all_rows.append(row)

    print(f"Generated rows: {len(all_rows)}")
    insert_rows_in_batches(all_rows)


if __name__ == "__main__":
    generate_crowd_history(days_back=60)
