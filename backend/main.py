from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Optional
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import base64
import calendar
import hashlib
import hmac
import json
import logging
import os
import re
import bcrypt
import joblib
import pandas as pd
from supabase import Client, create_client

try:
    from backend.settings import get_env_value, load_project_env, missing_supabase_message
except ImportError:
    from settings import get_env_value, load_project_env, missing_supabase_message


CURRENT_FILE = Path(__file__).resolve()
BACKEND_DIR = CURRENT_FILE.parent
PROJECT_ROOT = BACKEND_DIR.parent
ENV_PATH = PROJECT_ROOT / ".env"
STATIC_DIR = PROJECT_ROOT / "frontend" / "static"
TEMPLATES_DIR = PROJECT_ROOT / "frontend" / "templates"
MODEL_PATH = BACKEND_DIR / "crowd_model.pkl"

logging.basicConfig(
    level=logging.INFO,
    format="[metro] %(asctime)s %(levelname)s - %(message)s",
)
logger = logging.getLogger("metro")


def _mask_secret(value: Optional[str]) -> str:
    if not value:
        return "None"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def load_runtime_settings() -> tuple[str, str]:
    """Load Supabase settings from environment variables and the local .env file."""
    logger.info("Loading environment variables from %s", ENV_PATH)
    file_values = load_project_env()

    supabase_url = get_env_value("SUPABASE_URL", file_values, allow_placeholder=False)
    supabase_key = get_env_value(
        "SUPABASE_SERVICE_ROLE_KEY",
        file_values,
        allow_placeholder=False,
    ) or get_env_value(
        "SUPABASE_KEY",
        file_values,
        allow_placeholder=False,
    )

    logger.info(".env file present: %s", ENV_PATH.exists())
    logger.info("SUPABASE_URL loaded: %s", bool(supabase_url))
    logger.info("SUPABASE_KEY preview: %s", _mask_secret(supabase_key))

    missing_values: list[str] = []
    if not supabase_url:
        missing_values.append("SUPABASE_URL")
    if not supabase_key:
        missing_values.append("SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY)")
    if missing_values:
        raise ValueError(missing_supabase_message(missing_values))

    return supabase_url, supabase_key


SUPABASE_URL, SUPABASE_KEY = load_runtime_settings()
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
SESSION_SECRET = get_env_value("APP_SESSION_SECRET", allow_placeholder=False)
if not SESSION_SECRET:
    logger.warning("APP_SESSION_SECRET is not set. Using a derived development fallback secret.")
    SESSION_SECRET = hashlib.sha256(f"{SUPABASE_KEY}:{SUPABASE_URL}".encode("utf-8")).hexdigest()
SESSION_COOKIE_NAME = "metro_session"
logger.info("Supabase client initialized successfully")

crowd_model = None
if _env_flag("DISABLE_CROWD_MODEL"):
    logger.warning("Crowd model loading is disabled via DISABLE_CROWD_MODEL.")
elif MODEL_PATH.exists():
    try:
        crowd_model = joblib.load(MODEL_PATH)
        logger.info("Crowd prediction model loaded from %s", MODEL_PATH)
    except Exception:
        logger.exception("Unable to load crowd model from %s. Falling back to heuristic predictions.", MODEL_PATH)
else:
    logger.warning(
        "Crowd model file was not found at %s. Using the heuristic fallback predictor.",
        MODEL_PATH,
    )

app = FastAPI(title="Metro Mate API", version="1.0.0")

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Configure templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic Models
class StationInfo(BaseModel):
    name: str
    line: str
    sequence: int = 0
    is_interchange: bool = False
    is_elevated: bool = False
    station_type: str = "residential"
    line_color: str = "#0f1a27"

class SmartCard(BaseModel):
    card_number: str
    balance: int
    full_name: str

class RechargeRequest(BaseModel):
    email: str
    amount: int

class RechargeResponse(BaseModel):
    message: str
    new_balance: int

class Transaction(BaseModel):
    id: str
    user_email: str
    from_station: str = ""
    to_station: str = ""
    amount: int
    type: str
    created_at: str

class TransactionResponse(BaseModel):
    transactions: List[Transaction]

class BookingDetails(BaseModel):
    booking_id: str
    user_email: str
    from_station: str
    to_station: str
    total_fare: int
    ticket_count: int
    status: str
    payment_method: str
    booking_date: str

class CancelResponse(BaseModel):
    message: str
    refund_amount: int = 0
    new_balance: int = 0

# Lost & Found System Models
class LostItemRequest(BaseModel):
    email: str
    item_name: str
    station: str
    description: str = ""
    full_name: str = ""
    contact_number: str = ""

class FoundItemRequest(BaseModel):
    item_name: str
    station: str
    description: str = ""
    reported_by: str
    contact_info: str = ""

class LostItemResponse(BaseModel):
    id: str
    user_email: str
    item_name: str
    station: str
    description: str
    status: str
    created_at: str

class FoundItemResponse(BaseModel):
    id: str
    item_name: str
    station: str
    description: str
    reported_by: str
    contact_info: str
    created_at: str

class MatchResponse(BaseModel):
    id: str
    lost_item: LostItemResponse
    found_item: FoundItemResponse
    match_score: float
    status: str
    created_at: str

class ReportResponse(BaseModel):
    success: bool
    message: str
    data: dict = None

class BookingRequest(BaseModel):
    from_station: str
    to_station: str
    ticket_count: int = 1  # Default to 1 ticket
    booking_name: str  # Name for the booking
    payment_method: str  # Payment method
    user_email: str  # To identify the user

class BookingResponse(BaseModel):
    from_station: str
    to_station: str
    stations: int
    fare_per_ticket: float
    ticket_count: int
    baseFare: float
    surcharge: float
    totalFare: float
    payment_method: str
    user_name: str
    booking_name: str
    message: str = ""

# Authentication Models
class SignupRequest(BaseModel):
    full_name: str
    email: str
    password: str
    user_type: str  # "User" or "Admin"

class LoginRequest(BaseModel):
    email: str
    password: str

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    email: str
    new_password: str
    confirm_password: str

class HealthResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    status: str
    timestamp: str
    model_loaded: bool
    supabase_connected: bool


class UserStatusUpdateRequest(BaseModel):
    status: str = Field(..., description="Use 'active' or 'blocked'")


class StationWriteRequest(BaseModel):
    name: str = Field(..., min_length=2)
    line: str = Field(..., min_length=2)
    sequence: int = Field(default=0, ge=0)
    is_interchange: bool = False
    is_elevated: bool = False
    station_type: str = "residential"
    line_color: str = "#0f1a27"


class ComplaintStatusUpdateRequest(BaseModel):
    status: str = Field(..., description="pending, matched, or resolved")


class MatchCreateRequest(BaseModel):
    found_item_id: str
    match_score: float = Field(default=0.85, ge=0, le=1)
    status: str = Field(default="pending")

class CrowdPredictionQuery(BaseModel):
    station_name: str = Field(..., min_length=2, description="Station name to predict crowd for")
    hour: Optional[str] = Field(default=None, description="Selected hour in 24h or 12h format")
    day_type: Optional[str] = Field(default=None, description="weekday or weekend")

class PredictionPoint(BaseModel):
    hour: str
    crowd_level: str

class CrowdPredictionResponse(BaseModel):
    station_name: str
    line: str
    selected_hour: str
    day_type: str
    station_category: str
    is_interchange: bool
    is_elevated: bool
    selected_time_prediction: PredictionPoint
    next_hours: List[PredictionPoint]
    trend: str
    recommendation: str

# Helper Functions
PREDICTION_FEATURE_COLUMNS = [
    "station_name",
    "line",
    "sequence",
    "hour",
    "day_name",
    "is_weekend",
    "is_holiday",
    "weather",
    "station_type",
    "is_interchange",
    "is_elevated",
    "nearby_event",
]

LINE_COLOR_MAP = {
    "yellow": "#eab308",
    "blue": "#2563eb",
    "green": "#16a34a",
    "red": "#dc2626",
    "orange": "#f97316",
    "purple": "#7c3aed",
}

TOURIST_STATIONS = {
    "Taj Mahal",
    "Taj East Gate",
    "Fatehabad Road",
    "Mankameshwar Mandir",
    "Guru Ka Taal",
}
TRANSPORT_STATIONS = {"Agra Cantt", "ISBT", "Raja Ki Mandi", "Sikandra"}
OFFICE_STATIONS = {"Sanjay Place", "MG Road", "Collectorate"}
MARKET_STATIONS = {"Sadar Bazaar", "Hariparvat Chauraha", "Agra Mandi", "Dr. Ambedkar Chowk"}
STUDENT_STATIONS = {"Agra College", "RBS College", "Medical College"}
INDUSTRIAL_STATIONS = {"Foundary Nagar"}

CATEGORY_FORECAST_CONFIG = {
    "transport": {"baseline": 104, "raw_weight": 0.58, "low_threshold": 100, "high_threshold": 214},
    "office": {"baseline": 90, "raw_weight": 0.54, "low_threshold": 90, "high_threshold": 205},
    "student": {"baseline": 84, "raw_weight": 0.50, "low_threshold": 84, "high_threshold": 188},
    "tourist": {"baseline": 94, "raw_weight": 0.50, "low_threshold": 90, "high_threshold": 196},
    "market": {"baseline": 88, "raw_weight": 0.52, "low_threshold": 86, "high_threshold": 190},
    "industrial": {"baseline": 80, "raw_weight": 0.48, "low_threshold": 86, "high_threshold": 190},
    "residential": {"baseline": 72, "raw_weight": 0.44, "low_threshold": 78, "high_threshold": 176},
}

OVERNIGHT_TIME_DELTAS = {
    "transport": -40,
    "office": -52,
    "student": -54,
    "tourist": -42,
    "market": -44,
    "industrial": -48,
    "residential": -32,
}

EARLY_MORNING_TIME_DELTAS = {
    "transport": -8,
    "office": -18,
    "student": -22,
    "tourist": -24,
    "market": -20,
    "industrial": -14,
    "residential": -8,
}

MORNING_RUSH_TIME_DELTAS = {
    "transport": 46,
    "office": 40,
    "student": 34,
    "tourist": 8,
    "market": 12,
    "industrial": 18,
    "residential": 18,
}

LATE_MORNING_TIME_DELTAS = {
    "transport": 18,
    "office": 16,
    "student": 10,
    "tourist": 24,
    "market": 16,
    "industrial": 10,
    "residential": 6,
}

AFTERNOON_TIME_DELTAS = {
    "transport": 14,
    "office": 8,
    "student": 12,
    "tourist": 34,
    "market": 28,
    "industrial": 8,
    "residential": 8,
}

EVENING_RUSH_TIME_DELTAS = {
    "transport": 54,
    "office": 42,
    "student": 18,
    "tourist": 18,
    "market": 36,
    "industrial": 18,
    "residential": 24,
}

POST_RUSH_TIME_DELTAS = {
    "transport": 18,
    "office": 12,
    "student": 6,
    "tourist": 12,
    "market": 18,
    "industrial": 8,
    "residential": 10,
}

LATE_EVENING_TIME_DELTAS = {
    "transport": -10,
    "office": -22,
    "student": -24,
    "tourist": -18,
    "market": -14,
    "industrial": -16,
    "residential": -10,
}

WEEKEND_CATEGORY_DELTAS = {
    "transport": 8,
    "office": -26,
    "student": -34,
    "tourist": 20,
    "market": 14,
    "industrial": -18,
    "residential": 10,
}

WEEKDAY_CATEGORY_DELTAS = {
    "transport": 6,
    "office": 10,
    "student": 12,
    "tourist": -2,
    "market": 2,
    "industrial": 4,
    "residential": -4,
}


def line_to_color(line: str) -> str:
    line_key = (line or "").strip().lower()
    for key, color in LINE_COLOR_MAP.items():
        if key in line_key:
            return color
    return "#0f1a27"


def normalize_station_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def infer_station_type(name: str) -> str:
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


def infer_weather(reference_time: datetime) -> str:
    month = reference_time.month
    hour = reference_time.hour

    if month in {12, 1} and 6 <= hour <= 10:
        return "Fog"
    if month in {7, 8}:
        return "Rainy"
    if month in {6, 9}:
        return "Cloudy"
    return "Clear"


def is_fixed_holiday(current_date: date) -> bool:
    return (current_date.month, current_date.day) in {(1, 26), (8, 15), (10, 2)}


def build_station_info(station: Dict[str, Any]) -> StationInfo:
    station_name = str(station.get("name", "Unknown Station")).strip()
    station_line = str(station.get("line", "Unknown Line")).strip()
    station_type = str(station.get("station_type") or infer_station_type(station_name)).strip().lower()

    return StationInfo(
        name=station_name,
        line=station_line,
        sequence=safe_int(station.get("sequence"), 0),
        is_interchange=normalize_station_bool(station.get("is_interchange")),
        is_elevated=normalize_station_bool(station.get("is_elevated")),
        station_type=station_type,
        line_color=line_to_color(station_line),
    )


def fetch_station_directory_from_supabase() -> List[StationInfo]:
    logger.info("Fetching station directory from Supabase")
    response = supabase.table("stations").select("*").order("line").order("sequence").execute()

    if response.data is None:
        raise HTTPException(status_code=500, detail="Failed to fetch stations from Supabase")

    stations = [build_station_info(station) for station in response.data]
    logger.info("Fetched %s stations", len(stations))
    return stations


def group_stations_by_line(stations: List[StationInfo]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}

    for station in stations:
        if station.line not in grouped:
            grouped[station.line] = {
                "line": station.line,
                "line_color": station.line_color,
                "stations": [],
            }
        grouped[station.line]["stations"].append(station.model_dump())

    return list(grouped.values())


def get_station_query(query: CrowdPredictionQuery = Depends()) -> CrowdPredictionQuery:
    query.station_name = query.station_name.strip()
    if not query.station_name:
        raise HTTPException(status_code=400, detail="station_name is required")
    return query


def fetch_station_by_name(station_name: str) -> StationInfo:
    logger.info("Validating station '%s' before prediction", station_name)
    response = supabase.table("stations").select("*").ilike("name", station_name).execute()

    if not response.data:
        raise HTTPException(status_code=404, detail=f"Station '{station_name}' not found")

    return build_station_info(response.data[0])


def parse_prediction_hour(raw_hour: Optional[str]) -> int:
    """Accept 24h values like 15 or 15:00 and 12h values like 3 PM."""
    if raw_hour is None or str(raw_hour).strip() == "":
        return datetime.now().hour

    hour_value = str(raw_hour).strip().upper()

    if hour_value.isdigit():
        parsed_hour = int(hour_value)
        if 0 <= parsed_hour <= 23:
            return parsed_hour

    hour_match_24 = re.fullmatch(r"(\d{1,2})(?::(\d{1,2}))?", hour_value)
    if hour_match_24:
        parsed_hour = int(hour_match_24.group(1))
        parsed_minute = int(hour_match_24.group(2) or 0)
        if 0 <= parsed_hour <= 23 and 0 <= parsed_minute <= 59:
            return parsed_hour

    hour_match_12 = re.fullmatch(r"(\d{1,2})(?::(\d{1,2}))?\s*([AP]M)", hour_value)
    if hour_match_12:
        parsed_hour = int(hour_match_12.group(1))
        parsed_minute = int(hour_match_12.group(2) or 0)
        meridiem = hour_match_12.group(3)
        if 1 <= parsed_hour <= 12 and 0 <= parsed_minute <= 59:
            parsed_hour %= 12
            if meridiem == "PM":
                parsed_hour += 12
            return parsed_hour

    raise HTTPException(
        status_code=400,
        detail="hour must be between 0 and 23, like 15 or 15:00, or a 12-hour value like 3 PM",
    )


def normalize_day_type(day_type: Optional[str]) -> str:
    if day_type is None or not str(day_type).strip():
        return "weekend" if datetime.now().weekday() >= 5 else "weekday"

    normalized = str(day_type).strip().lower()
    if normalized in {"weekday", "weekdays", "workday", "working-day"}:
        return "weekday"
    if normalized in {"weekend", "weekends"}:
        return "weekend"

    raise HTTPException(status_code=400, detail="day_type must be 'weekday' or 'weekend'")


def resolve_prediction_datetime(selected_hour: int, day_type: str) -> datetime:
    now = datetime.now()

    for offset in range(7):
        candidate_date = now.date() + timedelta(days=offset)
        candidate_is_weekend = candidate_date.weekday() >= 5
        if (day_type == "weekend" and candidate_is_weekend) or (
            day_type == "weekday" and not candidate_is_weekend
        ):
            return datetime.combine(candidate_date, datetime.min.time()).replace(hour=selected_hour)

    return datetime.combine(now.date(), datetime.min.time()).replace(hour=selected_hour)


def get_station_category(station: StationInfo) -> str:
    return station.station_type.strip().lower() or "residential"


def get_category_forecast_config(station_category: str) -> Dict[str, float]:
    return CATEGORY_FORECAST_CONFIG.get(station_category, CATEGORY_FORECAST_CONFIG["residential"])


def station_signature_offset(station_name: str) -> int:
    signature = sum((index + 1) * ord(char) for index, char in enumerate(station_name.lower()))
    return (signature % 15) - 7


def is_expected_busy_window(station_category: str, hour: int, is_weekend: bool) -> bool:
    if station_category in {"transport", "office"} and not is_weekend:
        return 7 <= hour <= 10 or 16 <= hour <= 19
    if station_category == "student":
        return not is_weekend and (7 <= hour <= 10 or 13 <= hour <= 17)
    if station_category == "tourist":
        return 11 <= hour <= 16
    if station_category == "market":
        return 12 <= hour <= 19
    if station_category == "residential":
        return 7 <= hour <= 9 or 17 <= hour <= 21
    if station_category == "industrial":
        return not is_weekend and (7 <= hour <= 9 or 16 <= hour <= 18)
    return False


def infer_series_phase(station_category: str, hour: int, day_type: str) -> str:
    is_weekend = day_type == "weekend"

    if 0 <= hour <= 5 or 22 <= hour <= 23:
        return "wind_down"

    if station_category in {"transport", "office"} and not is_weekend:
        if 6 <= hour <= 8 or 15 <= hour <= 17:
            return "build_up"
        if 9 <= hour <= 10 or 18 <= hour <= 19:
            return "peak"
        if 11 <= hour <= 13 or 20 <= hour <= 21:
            return "wind_down"

    if station_category == "student":
        if not is_weekend and (7 <= hour <= 8 or 13 <= hour <= 15):
            return "build_up"
        if not is_weekend and (9 <= hour <= 10 or 16 <= hour <= 17):
            return "peak"
        if hour >= 18 or (not is_weekend and 11 <= hour <= 12) or (is_weekend and 7 <= hour <= 12):
            return "wind_down"

    if station_category == "tourist":
        if 10 <= hour <= 12:
            return "build_up"
        if 13 <= hour <= 16:
            return "peak"
        if 17 <= hour <= 20:
            return "wind_down"

    if station_category == "market":
        if 11 <= hour <= 13:
            return "build_up"
        if 14 <= hour <= 18:
            return "peak"
        if 19 <= hour <= 21:
            return "wind_down"

    if station_category == "residential":
        if 6 <= hour <= 8 or 17 <= hour <= 18:
            return "build_up"
        if 9 <= hour <= 10 or 19 <= hour <= 20:
            return "peak"
        if 11 <= hour <= 14 or 21 <= hour <= 23:
            return "wind_down"

    if station_category == "industrial":
        if not is_weekend and (7 <= hour <= 8 or 15 <= hour <= 16):
            return "build_up"
        if not is_weekend and (9 <= hour <= 10 or 17 <= hour <= 18):
            return "peak"
        if 19 <= hour <= 21:
            return "wind_down"

    return "steady"


def estimate_station_baseline(station: StationInfo, slot_time: datetime) -> tuple[int, List[str]]:
    station_category = get_station_category(station)
    config = get_category_forecast_config(station_category)
    baseline = int(config["baseline"])
    hour = slot_time.hour
    is_weekend = slot_time.weekday() >= 5
    reasons = [f"category_base={baseline}"]

    if 0 <= hour <= 5:
        time_delta = OVERNIGHT_TIME_DELTAS.get(station_category, -35)
        time_phase = "overnight"
    elif hour == 6:
        time_delta = EARLY_MORNING_TIME_DELTAS.get(station_category, -12)
        time_phase = "early_morning"
    elif 7 <= hour <= 9:
        time_delta = MORNING_RUSH_TIME_DELTAS.get(station_category, 16)
        time_phase = "morning_rush"
    elif 10 <= hour <= 12:
        time_delta = LATE_MORNING_TIME_DELTAS.get(station_category, 10)
        time_phase = "late_morning"
    elif 13 <= hour <= 16:
        time_delta = AFTERNOON_TIME_DELTAS.get(station_category, 12)
        time_phase = "afternoon"
    elif 17 <= hour <= 19:
        time_delta = EVENING_RUSH_TIME_DELTAS.get(station_category, 18)
        time_phase = "evening_rush"
    elif hour == 20:
        time_delta = POST_RUSH_TIME_DELTAS.get(station_category, 8)
        time_phase = "post_rush"
    else:
        time_delta = LATE_EVENING_TIME_DELTAS.get(station_category, -10)
        time_phase = "late_evening"

    baseline += time_delta
    reasons.append(f"{time_phase}{time_delta:+d}")

    day_delta = (
        WEEKEND_CATEGORY_DELTAS.get(station_category, 0)
        if is_weekend
        else WEEKDAY_CATEGORY_DELTAS.get(station_category, 0)
    )
    if day_delta:
        reasons.append(f"{'weekend' if is_weekend else 'weekday'}{day_delta:+d}")
    baseline += day_delta

    if station.is_interchange:
        interchange_delta = 14
        if station_category == "transport":
            interchange_delta += 8
        baseline += interchange_delta
        reasons.append(f"interchange{interchange_delta:+d}")

    if station.is_elevated:
        elevated_delta = 6 if station_category != "market" else 8
        baseline += elevated_delta
        reasons.append(f"elevated{elevated_delta:+d}")

    signature_delta = station_signature_offset(station.name)
    if signature_delta:
        baseline += signature_delta
        reasons.append(f"station_signature{signature_delta:+d}")

    return max(baseline, 18), reasons


def calibrate_crowd_prediction(
    raw_prediction: int,
    station: StationInfo,
    slot_time: datetime,
) -> Dict[str, Any]:
    station_category = get_station_category(station)
    config = get_category_forecast_config(station_category)
    baseline, baseline_reasons = estimate_station_baseline(station, slot_time)
    is_weekend = slot_time.weekday() >= 5
    raw_weight = float(config["raw_weight"])
    hour = slot_time.hour

    if is_expected_busy_window(station_category, hour, is_weekend):
        raw_weight += 0.03
    if 0 <= hour <= 5 or 21 <= hour <= 23:
        raw_weight -= 0.04
    if station.is_interchange:
        raw_weight += 0.01

    raw_weight = min(max(raw_weight, 0.38), 0.64)

    calibrated_count = round((raw_prediction * raw_weight) + (baseline * (1 - raw_weight)))
    adjustments = list(baseline_reasons)
    adjustments.append(f"blend_raw_weight={raw_weight:.2f}")

    gap_from_baseline = raw_prediction - baseline
    if gap_from_baseline > 75:
        damp_ratio = 0.09 if is_expected_busy_window(station_category, hour, is_weekend) else 0.18
        dampening = int(gap_from_baseline * damp_ratio)
        calibrated_count -= dampening
        adjustments.append(f"gap_dampen=-{dampening}")
    elif gap_from_baseline < -70:
        uplift = int(abs(gap_from_baseline) * 0.10)
        calibrated_count += uplift
        adjustments.append(f"gap_uplift=+{uplift}")

    targeted_delta = 0
    if station_category == "transport" and not is_weekend and 17 <= hour <= 19:
        targeted_delta += 10
    if station_category == "tourist" and is_weekend and 12 <= hour <= 15:
        targeted_delta += 8
    if station_category == "market" and 15 <= hour <= 19:
        targeted_delta += 6
    if station_category == "student" and not is_weekend and 13 <= hour <= 16:
        targeted_delta += 6
    if station_category in {"office", "student"} and is_weekend and 7 <= hour <= 16:
        targeted_delta -= 10
    if station_category == "residential" and 11 <= hour <= 16:
        targeted_delta -= 8

    if targeted_delta:
        calibrated_count += targeted_delta
        adjustments.append(f"targeted_shift={targeted_delta:+d}")

    calibrated_count = max(min(int(calibrated_count), 320), 12)

    return {
        "raw_prediction": raw_prediction,
        "baseline": baseline,
        "calibrated_count": calibrated_count,
        "adjustments": adjustments,
    }


def build_prediction_feature_rows(station: StationInfo, reference_time: datetime) -> List[Dict[str, Any]]:
    feature_rows = []
    station_type = get_station_category(station)

    for offset in range(4):
        slot_time = reference_time + timedelta(hours=offset)
        hour = slot_time.hour
        nearby_event = station_type in {"tourist", "market"} and (
            slot_time.weekday() >= 5 or 11 <= hour <= 20
        )

        feature_rows.append(
            {
                "_slot_time": slot_time,
                "station_name": station.name,
                "line": station.line,
                "sequence": station.sequence,
                "hour": hour,
                "day_name": slot_time.strftime("%A"),
                "is_weekend": slot_time.weekday() >= 5,
                "is_holiday": is_fixed_holiday(slot_time.date()),
                "weather": infer_weather(slot_time),
                "station_type": station_type,
                "is_interchange": station.is_interchange,
                "is_elevated": station.is_elevated,
                "nearby_event": nearby_event,
            }
        )

    return feature_rows


def build_fallback_raw_prediction(station: StationInfo, slot_time: datetime, day_type: str) -> int:
    station_category = get_station_category(station)
    baseline, _ = estimate_station_baseline(station, slot_time)
    phase = infer_series_phase(station_category, slot_time.hour, day_type)
    is_weekend = slot_time.weekday() >= 5
    hour = slot_time.hour

    phase_delta = {
        "build_up": 18,
        "peak": 30,
        "steady": 8,
        "wind_down": -12,
    }.get(phase, 4)

    if is_expected_busy_window(station_category, hour, is_weekend):
        phase_delta += 10
    if is_fixed_holiday(slot_time.date()):
        if station_category in {"tourist", "market", "transport"}:
            phase_delta += 10
        elif station_category in {"office", "student", "industrial"}:
            phase_delta -= 8

    if station_category in {"tourist", "market"} and (is_weekend or 11 <= hour <= 20):
        phase_delta += 8

    signature_delta = ((abs(station_signature_offset(station.name)) + hour) % 5 - 2) * 4
    raw_prediction = baseline + phase_delta + signature_delta
    return max(min(raw_prediction, 340), 12)


def get_raw_crowd_predictions(
    feature_rows: List[Dict[str, Any]],
    station: StationInfo,
    day_type: str,
) -> tuple[List[int], str]:
    if crowd_model is not None:
        feature_frame = pd.DataFrame(feature_rows, columns=PREDICTION_FEATURE_COLUMNS)
        raw_predictions = [
            max(int(round(float(predicted_value))), 0)
            for predicted_value in crowd_model.predict(feature_frame)
        ]
        return raw_predictions, "ml"

    fallback_predictions = [
        build_fallback_raw_prediction(station, feature_row["_slot_time"], day_type)
        for feature_row in feature_rows
    ]
    return fallback_predictions, "heuristic"


def apply_series_calibration(
    calibrated_counts: List[int],
    slot_times: List[datetime],
    station: StationInfo,
    day_type: str,
) -> tuple[List[int], List[str]]:
    if not calibrated_counts:
        return [], []

    station_category = get_station_category(station)
    phase = infer_series_phase(station_category, slot_times[0].hour, day_type)
    max_jump = 32 if phase == "steady" else 42
    shaped_counts = [calibrated_counts[0]]
    adjustments = [f"series_phase={phase}"]

    for index in range(1, len(calibrated_counts)):
        candidate = calibrated_counts[index]
        previous = shaped_counts[-1]
        slot_label = format_selected_hour(slot_times[index].hour)

        if candidate > previous + max_jump:
            candidate = previous + max_jump
            adjustments.append(f"{slot_label}_jump_capped")
        elif candidate < previous - max_jump:
            candidate = previous - max_jump
            adjustments.append(f"{slot_label}_drop_capped")

        if phase == "build_up":
            minimum_expected = previous + (10 if index == 1 else 7)
            if candidate < minimum_expected:
                candidate = minimum_expected
                adjustments.append(f"{slot_label}_build_up_floor")
        elif phase == "wind_down":
            maximum_expected = previous - (10 if index == 1 else 7)
            if candidate > maximum_expected:
                candidate = maximum_expected
                adjustments.append(f"{slot_label}_wind_down_cap")
        elif phase == "peak":
            bounded_candidate = min(max(candidate, previous - 14), previous + 14)
            if bounded_candidate != candidate:
                adjustments.append(f"{slot_label}_peak_smoothed")
            candidate = bounded_candidate

        shaped_counts.append(max(candidate, 12))

    return shaped_counts, adjustments


def resolve_dynamic_thresholds(station: StationInfo, slot_time: datetime) -> Dict[str, Any]:
    station_category = get_station_category(station)
    config = get_category_forecast_config(station_category)
    is_weekend = slot_time.weekday() >= 5
    hour = slot_time.hour
    low_threshold = int(config["low_threshold"])
    high_threshold = int(config["high_threshold"])
    reasons = [f"category_thresholds={low_threshold}/{high_threshold}"]

    if is_expected_busy_window(station_category, hour, is_weekend):
        busy_low_shift, busy_high_shift = {
            "transport": (6, 10),
            "office": (8, 14),
            "student": (6, 12),
            "tourist": (8, 12),
            "market": (7, 12),
            "industrial": (8, 14),
            "residential": (8, 14),
        }.get(station_category, (8, 14))
        low_threshold += busy_low_shift
        high_threshold += busy_high_shift
        reasons.append(f"busy_window=+{busy_low_shift}/+{busy_high_shift}")
    elif 0 <= hour <= 5 or 21 <= hour <= 23:
        low_threshold -= 8
        high_threshold -= 14
        reasons.append("quiet_window=-8/-14")

    if station_category == "tourist" and is_weekend and 11 <= hour <= 16:
        low_threshold += 4
        high_threshold += 8
        reasons.append("weekend_tourist=+4/+8")

    if station_category == "market" and 13 <= hour <= 19:
        low_threshold += 4
        high_threshold += 10
        reasons.append("market_afternoon=+4/+10")

    if station_category in {"office", "student"} and is_weekend:
        low_threshold -= 2
        high_threshold -= 6
        reasons.append("weekend_office_student=-2/-6")

    if station.is_interchange:
        low_threshold += 4
        high_threshold += 8
        reasons.append("interchange=+4/+8")

    if station.is_elevated:
        high_threshold += 4
        reasons.append("elevated=+0/+4")

    high_threshold = max(high_threshold, low_threshold + 35)

    return {
        "low_threshold": low_threshold,
        "high_threshold": high_threshold,
        "reasons": reasons,
    }


def crowd_level_from_count(crowd_count: int, station: StationInfo, slot_time: datetime) -> Dict[str, Any]:
    threshold_details = resolve_dynamic_thresholds(station, slot_time)

    if crowd_count < threshold_details["low_threshold"]:
        crowd_level = "Low"
    elif crowd_count < threshold_details["high_threshold"]:
        crowd_level = "Medium"
    else:
        crowd_level = "High"

    return {
        "crowd_level": crowd_level,
        "low_threshold": threshold_details["low_threshold"],
        "high_threshold": threshold_details["high_threshold"],
        "reasons": threshold_details["reasons"],
    }


def format_prediction_hour(hour: int) -> str:
    suffix = "PM" if hour >= 12 else "AM"
    twelve_hour = hour % 12 or 12
    return f"{twelve_hour} {suffix}"


def format_selected_hour(hour: int) -> str:
    return f"{hour:02d}:00"


def crowd_trend_from_values(
    values: List[int],
    slot_times: List[datetime],
    station_category: str,
    day_type: str,
) -> str:
    if not values:
        return "Stable"

    deltas = [values[index + 1] - values[index] for index in range(len(values) - 1)]
    if not deltas:
        return "Stable"

    rising_steps = sum(1 for delta in deltas if delta >= 10)
    falling_steps = sum(1 for delta in deltas if delta <= -10)
    total_delta = values[-1] - values[0]
    average_delta = sum(deltas) / len(deltas)
    series_phase = infer_series_phase(station_category, slot_times[0].hour, day_type)

    if rising_steps >= 2 and total_delta >= 18:
        return "Increasing"
    if falling_steps >= 2 and total_delta <= -18:
        return "Decreasing"

    if series_phase == "build_up" and total_delta >= 10:
        return "Increasing"
    if series_phase == "wind_down" and total_delta <= -10:
        return "Decreasing"

    if max(values) - min(values) <= 18:
        return "Stable"
    if average_delta >= 12:
        return "Increasing"
    if average_delta <= -12:
        return "Decreasing"
    return "Stable"


def build_recommendation(
    predictions: List[PredictionPoint],
    calibrated_counts: List[int],
    trend: str,
) -> str:
    current = predictions[0]
    future_predictions = predictions[1:]
    current_count = calibrated_counts[0]
    peak_index = max(range(len(calibrated_counts)), key=lambda index: calibrated_counts[index])
    peak_prediction = predictions[peak_index]
    next_high_slot = next((point for point in future_predictions if point.crowd_level == "High"), None)
    easier_slot = next(
        (
            predictions[index]
            for index in range(1, len(calibrated_counts))
            if calibrated_counts[index] <= current_count - 18 or predictions[index].crowd_level == "Low"
        ),
        None,
    )

    if current.crowd_level == "High":
        if easier_slot:
            return f"Avoid this station during peak hours. Better to travel after {easier_slot.hour}."
        if trend == "Increasing" and peak_prediction.hour != current.hour:
            return f"Crowd likely to peak around {peak_prediction.hour}. Avoid this station during peak hours."
        return "Avoid this station during peak hours."

    if current.crowd_level == "Medium":
        if future_predictions and future_predictions[0].crowd_level == "High":
            return "Crowd likely to peak in the next hour."
        if next_high_slot and peak_prediction.hour != current.hour:
            return f"Moderate crowd now, but it may get busier around {peak_prediction.hour}."
        if trend == "Decreasing" and easier_slot:
            return f"Moderate crowd expected. Better to travel after {easier_slot.hour}."
        if trend == "Stable":
            return "Moderate crowd expected for the next few hours."
        return "Moderate crowd expected."

    if trend == "Increasing" and peak_prediction.hour != current.hour:
        return f"Good time to travel now. Crowd may rise by {peak_prediction.hour}."
    if future_predictions and future_predictions[0].crowd_level == "Medium":
        return "Light crowd expected now, with a slightly busier hour ahead."
    if all(point.crowd_level == "Low" for point in future_predictions):
        return "Good time to travel."
    return "Light crowd expected."


def is_peak_hour():
    now = datetime.now()
    hour = now.hour
    return (8 <= hour < 11) or (17 <= hour < 20)

def hash_password(password: str) -> str:
    """Hash a password for storing."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    """Verify a stored password against one provided by user"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_user_type(value: Any) -> str:
    return str(value or "").strip().lower()


def user_type_for_storage(value: Any) -> str:
    normalized = normalize_user_type(value)
    if normalized == "admin":
        return "Admin"
    return "User"


def resolve_user_account_status(user: Dict[str, Any]) -> str:
    account_status = str(user.get("account_status") or user.get("status") or "").strip().lower()
    if account_status in {"blocked", "inactive", "disabled", "suspended"}:
        return "blocked"
    if account_status in {"active", "enabled"}:
        return "active"

    if user.get("blocked") is True:
        return "blocked"
    if user.get("is_active") is False:
        return "blocked"

    return "active"


def resolve_user_last_login(user: Dict[str, Any]) -> Optional[str]:
    for key in ("last_login_at", "last_login"):
        value = user.get(key)
        if value:
            return str(value)
    return None


def build_user_status_update_fields(user: Dict[str, Any], requested_status: str) -> Dict[str, Any]:
    normalized_status = requested_status.strip().lower()
    if normalized_status not in {"active", "blocked"}:
        raise HTTPException(status_code=400, detail="Status must be 'active' or 'blocked'")

    if "account_status" in user:
        return {"account_status": normalized_status}
    if "status" in user:
        return {"status": normalized_status}
    if "is_active" in user:
        return {"is_active": normalized_status == "active"}
    if "blocked" in user:
        return {"blocked": normalized_status == "blocked"}

    raise HTTPException(
        status_code=409,
        detail="User status management requires an account_status, status, is_active, or blocked column on users.",
    )


def base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")


def base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def create_session_token(user: Dict[str, Any], expires_in_hours: int = 24) -> str:
    issued_at = int(datetime.utcnow().timestamp())
    expires_at = int((datetime.utcnow() + timedelta(hours=expires_in_hours)).timestamp())
    payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        "user_type": normalize_user_type(user.get("user_type")),
        "iat": issued_at,
        "exp": expires_at,
    }
    payload_segment = base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        SESSION_SECRET.encode("utf-8"),
        payload_segment.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{payload_segment}.{base64url_encode(signature)}"


def decode_session_token(token: str) -> Dict[str, Any]:
    try:
        payload_segment, signature_segment = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid session token") from exc

    expected_signature = base64url_encode(
        hmac.new(
            SESSION_SECRET.encode("utf-8"),
            payload_segment.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    )
    if not hmac.compare_digest(signature_segment, expected_signature):
        raise HTTPException(status_code=401, detail="Invalid session token")

    try:
        payload = json.loads(base64url_decode(payload_segment).decode("utf-8"))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid session token payload") from exc

    if int(payload.get("exp", 0)) < int(datetime.utcnow().timestamp()):
        raise HTTPException(status_code=401, detail="Session token expired")

    return payload


def set_session_cookie(response: JSONResponse, session_token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 24,
        path="/",
    )


def clear_session_cookie(response: JSONResponse) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


def extract_session_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "").strip()
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token

    cookie_token = request.cookies.get(SESSION_COOKIE_NAME, "").strip()
    if cookie_token:
        return cookie_token

    session_token = request.headers.get("x-session-token", "").strip()
    if session_token:
        return session_token

    raise HTTPException(status_code=401, detail="Authentication required")


def get_authenticated_user(request: Request, required_user_type: Optional[str] = None) -> Dict[str, Any]:
    token_payload = decode_session_token(extract_session_token(request))
    user_response = (
        supabase.table("users")
        .select("*")
        .eq("email", token_payload["email"])
        .limit(1)
        .execute()
    )

    if not user_response.data:
        raise HTTPException(status_code=401, detail="Authenticated user not found")

    user = dict(user_response.data[0])
    if str(user.get("id")) != str(token_payload.get("sub")):
        raise HTTPException(status_code=401, detail="Invalid session user")

    if resolve_user_account_status(user) != "active":
        raise HTTPException(status_code=403, detail="Account is blocked. Please contact admin support.")

    user.pop("password", None)
    user["user_type"] = normalize_user_type(user.get("user_type"))
    user["account_status"] = resolve_user_account_status(user)
    user["last_login_at"] = resolve_user_last_login(user)
    user["session_issued_at"] = datetime.fromtimestamp(
        int(token_payload.get("iat", 0)),
        tz=timezone.utc,
    ).isoformat() if token_payload.get("iat") else None

    if required_user_type and user["user_type"] != required_user_type.lower():
        raise HTTPException(status_code=403, detail="Access denied for this dashboard")

    return user


def authorize_template_route(request: Request, required_user_type: str) -> tuple[Optional[Dict[str, Any]], Optional[RedirectResponse]]:
    try:
        current_user = get_authenticated_user(request)
    except HTTPException:
        return None, RedirectResponse(url="/", status_code=303)

    if current_user["user_type"] != required_user_type.lower():
        redirect_target = "/admin" if current_user["user_type"] == "admin" else "/home"
        return None, RedirectResponse(url=redirect_target, status_code=303)

    return current_user, None


def authorize_email_access(request: Request, email: str) -> Dict[str, Any]:
    current_user = get_authenticated_user(request)
    if current_user["user_type"] == "admin" or str(current_user.get("email", "")).strip().lower() == email.strip().lower():
        return current_user
    raise HTTPException(status_code=403, detail="Access denied for this account data")


def parse_datetime_value(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed_value = value
        if parsed_value.tzinfo is None:
            return parsed_value.replace(tzinfo=timezone.utc)
        return parsed_value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)

    raw_value = str(value).strip()
    if not raw_value or raw_value.upper() == "NOW()":
        return None

    normalized_value = raw_value.replace("Z", "+00:00")
    try:
        parsed_value = datetime.fromisoformat(normalized_value)
        if parsed_value.tzinfo is None:
            return parsed_value.replace(tzinfo=timezone.utc)
        return parsed_value.astimezone(timezone.utc)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S"):
        try:
            return datetime.strptime(raw_value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


def resolve_record_datetime(record: Dict[str, Any], *keys: str) -> Optional[datetime]:
    for key in keys:
        if key in record:
            parsed_value = parse_datetime_value(record.get(key))
            if parsed_value is not None:
                return parsed_value
    return None


def serialize_datetime(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def mask_card_number(card_number: Optional[str]) -> str:
    digits = "".join(char for char in str(card_number or "") if char.isdigit())
    if not digits:
        return "Not available"
    if len(digits) <= 4:
        return digits
    masked_prefix = " ".join(["****"] * max((len(digits) - 4) // 4, 2))
    return f"{masked_prefix} {digits[-4:]}"


def classify_time_of_day(value: Optional[datetime]) -> str:
    hour = value.hour if value else 0
    if 5 <= hour < 12:
        return "Morning"
    if 12 <= hour < 17:
        return "Afternoon"
    if 17 <= hour < 22:
        return "Evening"
    return "Night"


def classify_fare_range(amount: float) -> str:
    if amount <= 30:
        return "Low"
    if amount <= 80:
        return "Medium"
    return "High"


def build_daily_series(
    records: List[Dict[str, Any]],
    days: int,
    datetime_getter,
    value_getter=None,
) -> List[Dict[str, Any]]:
    today = datetime.now(timezone.utc).date()
    date_window = [today - timedelta(days=offset) for offset in reversed(range(days))]
    buckets = {series_date: 0.0 for series_date in date_window}

    for record in records:
        record_datetime = datetime_getter(record)
        if not record_datetime:
            continue
        record_date = record_datetime.date()
        if record_date in buckets:
            increment = value_getter(record) if value_getter else 1
            buckets[record_date] += safe_float(increment, 0.0)

    return [
        {
            "date": series_date.isoformat(),
            "label": series_date.strftime("%d %b"),
            "value": round(buckets[series_date], 2),
        }
        for series_date in date_window
    ]


def build_monthly_series(
    records: List[Dict[str, Any]],
    months: int,
    datetime_getter,
    value_getter=None,
) -> List[Dict[str, Any]]:
    cursor = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_window: List[datetime] = []
    for _ in range(months):
        month_window.append(cursor)
        if cursor.month == 1:
            cursor = cursor.replace(year=cursor.year - 1, month=12)
        else:
            cursor = cursor.replace(month=cursor.month - 1)
    month_window.reverse()
    buckets = {(month.year, month.month): 0.0 for month in month_window}

    for record in records:
        record_datetime = datetime_getter(record)
        if not record_datetime:
            continue
        month_key = (record_datetime.year, record_datetime.month)
        if month_key in buckets:
            increment = value_getter(record) if value_getter else 1
            buckets[month_key] += safe_float(increment, 0.0)

    return [
        {
            "label": month.strftime("%b %Y"),
            "value": round(buckets[(month.year, month.month)], 2),
            "month": month.strftime("%Y-%m"),
        }
        for month in month_window
    ]


def build_hourly_distribution(records: List[Dict[str, Any]], datetime_getter) -> List[Dict[str, Any]]:
    buckets = {hour: 0 for hour in range(24)}
    for record in records:
        record_datetime = datetime_getter(record)
        if not record_datetime:
            continue
        buckets[record_datetime.hour] += 1

    return [
        {"label": format_prediction_hour(hour), "value": buckets[hour], "hour": hour}
        for hour in range(24)
    ]


def top_counter_items(counter: Counter, limit: int = 6) -> List[Dict[str, Any]]:
    return [{"label": label, "value": count} for label, count in counter.most_common(limit)]


def nearest_recharge_amount(amount: float) -> int:
    recharge_options = [100, 200, 500, 1000, 2000]
    safe_amount = max(int(round(amount or 0)), recharge_options[0])
    return min(recharge_options, key=lambda option: abs(option - safe_amount))


def map_ticket_timeline_status(raw_status: str, booking_datetime: Optional[datetime], now: Optional[datetime] = None) -> str:
    reference_time = now or datetime.now(timezone.utc)
    normalized_status = str(raw_status or "").strip().lower()
    if normalized_status in {"cancelled", "refunded"}:
        return "Cancelled"
    if normalized_status in {"upcoming", "active"}:
        if booking_datetime and booking_datetime >= reference_time - timedelta(hours=2):
            return "Upcoming"
    if booking_datetime and booking_datetime >= reference_time and normalized_status not in {"completed"}:
        return "Upcoming"
    return "Completed"


def map_complaint_status(raw_status: str) -> str:
    normalized_status = str(raw_status or "").strip().lower()
    if normalized_status in {"resolved", "accepted"}:
        return "Resolved"
    if normalized_status in {"matched"}:
        return "Matched"
    return "Pending"


def format_hour_window(hour_value: Optional[int]) -> str:
    if hour_value is None:
        return "Insufficient history"
    start_label = format_prediction_hour(hour_value)
    end_label = format_prediction_hour((hour_value + 1) % 24)
    return f"{start_label} - {end_label}"


def build_dashboard_payload(
    current_user: Dict[str, Any],
    bookings: List[Dict[str, Any]],
    card: Optional[Dict[str, Any]],
    transactions: List[Dict[str, Any]],
    complaints: List[Dict[str, Any]],
    matches: List[Dict[str, Any]],
    found_items_by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    today = now.date()
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    days_in_month = calendar.monthrange(now.year, now.month)[1]

    normalized_bookings: List[Dict[str, Any]] = []
    for booking in bookings:
        booking_datetime = resolve_record_datetime(booking, "booking_date", "created_at")
        normalized_bookings.append(
            {
                **booking,
                "_datetime": booking_datetime,
                "_status": str(booking.get("status") or "active").strip().lower(),
                "_fare": safe_float(booking.get("total_fare"), 0.0),
                "_ticket_count": safe_int(booking.get("ticket_count"), 0),
                "_payment_method": str(booking.get("payment_method") or "Unknown").strip(),
                "_route": f"{booking.get('from_station', 'Unknown')} -> {booking.get('to_station', 'Unknown')}",
            }
        )

    normalized_transactions: List[Dict[str, Any]] = []
    for transaction in transactions:
        transaction_datetime = resolve_record_datetime(transaction, "created_at")
        normalized_transactions.append(
            {
                **transaction,
                "_datetime": transaction_datetime,
                "_amount": safe_float(transaction.get("amount"), 0.0),
                "_type": str(transaction.get("type") or "").strip().lower(),
            }
        )

    normalized_complaints: List[Dict[str, Any]] = []
    for complaint in complaints:
        complaint_datetime = resolve_record_datetime(complaint, "created_at")
        normalized_complaints.append(
            {
                **complaint,
                "_datetime": complaint_datetime,
                "_status": str(complaint.get("status") or "searching").strip().lower(),
            }
        )

    normalized_matches: List[Dict[str, Any]] = []
    for match in matches:
        match_datetime = resolve_record_datetime(match, "created_at")
        normalized_matches.append(
            {
                **match,
                "_datetime": match_datetime,
                "_match_score": safe_float(match.get("match_score"), 0.0),
                "_status": str(match.get("status") or "pending").strip().lower(),
                "_found_item": found_items_by_id.get(str(match.get("found_item_id"))),
            }
        )

    min_dashboard_datetime = datetime.min.replace(tzinfo=timezone.utc)
    normalized_bookings.sort(key=lambda item: item["_datetime"] or min_dashboard_datetime, reverse=True)
    normalized_transactions.sort(key=lambda item: item["_datetime"] or min_dashboard_datetime, reverse=True)
    normalized_complaints.sort(key=lambda item: item["_datetime"] or min_dashboard_datetime, reverse=True)
    normalized_matches.sort(key=lambda item: item["_datetime"] or min_dashboard_datetime, reverse=True)

    active_bookings = [booking for booking in normalized_bookings if booking["_status"] == "active"]
    cancelled_bookings = [booking for booking in normalized_bookings if booking["_status"] == "cancelled"]
    completed_bookings = [booking for booking in normalized_bookings if booking["_status"] == "completed"]
    credit_transactions = [transaction for transaction in normalized_transactions if transaction["_type"] == "credit"]
    debit_transactions = [transaction for transaction in normalized_transactions if transaction["_type"] == "debit"]
    active_complaints = [complaint for complaint in normalized_complaints if complaint["_status"] != "resolved"]
    resolved_complaints = [complaint for complaint in normalized_complaints if complaint["_status"] == "resolved"]

    favorite_source_counter = Counter(
        str(booking.get("from_station") or "Unknown") for booking in normalized_bookings if booking.get("from_station")
    )
    favorite_destination_counter = Counter(
        str(booking.get("to_station") or "Unknown") for booking in normalized_bookings if booking.get("to_station")
    )
    payment_method_counter = Counter(booking["_payment_method"] for booking in normalized_bookings if booking["_payment_method"])
    route_counter = Counter(booking["_route"] for booking in normalized_bookings)
    peak_hour_counter = Counter(
        booking["_datetime"].hour for booking in normalized_bookings if booking["_datetime"] is not None
    )
    time_of_day_counter = Counter(
        classify_time_of_day(booking["_datetime"]) for booking in normalized_bookings if booking["_datetime"] is not None
    )

    total_amount_spent = sum(booking["_fare"] for booking in normalized_bookings)
    monthly_spend = sum(
        booking["_fare"]
        for booking in normalized_bookings
        if booking["_datetime"] and booking["_datetime"] >= start_of_month
    )
    total_recharge_amount = sum(transaction["_amount"] for transaction in credit_transactions)
    total_debit_amount = sum(transaction["_amount"] for transaction in debit_transactions)
    average_spend_per_trip = round(total_amount_spent / max(len(normalized_bookings), 1), 2) if normalized_bookings else 0.0

    favorite_source_station = favorite_source_counter.most_common(1)[0][0] if favorite_source_counter else "No source data yet"
    favorite_destination_station = (
        favorite_destination_counter.most_common(1)[0][0] if favorite_destination_counter else "No destination data yet"
    )
    favorite_route = route_counter.most_common(1)[0][0] if route_counter else "No route data yet"
    most_used_payment_method = payment_method_counter.most_common(1)[0][0] if payment_method_counter else "No payment data yet"
    peak_hour = peak_hour_counter.most_common(1)[0][0] if peak_hour_counter else None
    peak_hour_label = format_prediction_hour(peak_hour) if peak_hour is not None else "Not enough history"

    weekday_travel = sum(
        1
        for booking in normalized_bookings
        if booking["_datetime"] and booking["_datetime"].weekday() < 5
    )
    weekend_travel = sum(
        1
        for booking in normalized_bookings
        if booking["_datetime"] and booking["_datetime"].weekday() >= 5
    )
    weekday_spend = sum(
        booking["_fare"]
        for booking in normalized_bookings
        if booking["_datetime"] and booking["_datetime"].weekday() < 5
    )
    weekend_spend = sum(
        booking["_fare"]
        for booking in normalized_bookings
        if booking["_datetime"] and booking["_datetime"].weekday() >= 5
    )

    top_active_booking = active_bookings[0] if active_bookings else None
    last_booking = normalized_bookings[0] if normalized_bookings else None
    last_recharge = credit_transactions[0] if credit_transactions else None
    last_debit = debit_transactions[0] if debit_transactions else None
    latest_complaint = normalized_complaints[0] if normalized_complaints else None

    card_balance = safe_float(card.get("balance"), 0.0) if card else 0.0
    low_balance_threshold = max(average_spend_per_trip * 2, 100)
    days_elapsed = max(today.day, 1)
    monthly_spend_prediction = round((monthly_spend / days_elapsed) * days_in_month, 2) if monthly_spend else 0.0
    favorite_station_category = infer_station_type(favorite_source_station) if favorite_source_counter else "residential"

    kpis = {
        "card_balance": round(card_balance, 2),
        "active_tickets": len(active_bookings),
        "total_trips": len(normalized_bookings),
        "total_amount_spent": round(total_amount_spent, 2),
        "monthly_spend": round(monthly_spend, 2),
        "active_complaints": len(active_complaints),
        "resolved_complaints": len(resolved_complaints),
        "last_booking_fare": round(last_booking["_fare"], 2) if last_booking else 0.0,
        "favorite_source_station": favorite_source_station,
        "favorite_destination_station": favorite_destination_station,
        "most_used_payment_method": most_used_payment_method,
        "recharge_count": len(credit_transactions),
        "total_recharge_amount": round(total_recharge_amount, 2),
        "last_recharge_amount": round(last_recharge["_amount"], 2) if last_recharge else 0.0,
        "last_travel_date": serialize_datetime(last_booking["_datetime"]) if last_booking else None,
        "latest_active_booking": {
            "route": top_active_booking["_route"],
            "booking_date": serialize_datetime(top_active_booking["_datetime"]),
        } if top_active_booking else None,
    }

    graphs = {
        "travel_history": build_daily_series(
            normalized_bookings,
            7,
            lambda booking: booking["_datetime"],
        ),
        "spending_trend": build_daily_series(
            normalized_bookings,
            30,
            lambda booking: booking["_datetime"],
            lambda booking: booking["_fare"],
        ),
        "most_used_stations": top_counter_items(favorite_source_counter),
        "routes": top_counter_items(route_counter),
        "payment_methods": top_counter_items(payment_method_counter),
        "time_of_day": top_counter_items(time_of_day_counter, limit=4),
        "weekday_vs_weekend": [
            {"label": "Weekday", "value": weekday_travel},
            {"label": "Weekend", "value": weekend_travel},
        ],
        "fare_ranges": top_counter_items(
            Counter(classify_fare_range(booking["_fare"]) for booking in normalized_bookings),
            limit=3,
        ),
    }

    all_activity_trend = build_daily_series(
        debit_transactions + credit_transactions,
        30,
        lambda item: item["_datetime"],
    )
    graphs["smart_card_trend"] = {
        "labels": [point["label"] for point in all_activity_trend],
        "credit": [
            point["value"]
            for point in build_daily_series(
                credit_transactions,
                30,
                lambda transaction: transaction["_datetime"],
                lambda transaction: transaction["_amount"],
            )
        ],
        "debit": [
            point["value"]
            for point in build_daily_series(
                debit_transactions,
                30,
                lambda transaction: transaction["_datetime"],
                lambda transaction: transaction["_amount"],
            )
        ],
    }


def build_user_dashboard_contract(
    current_user: Dict[str, Any],
    bookings: List[Dict[str, Any]],
    card: Optional[Dict[str, Any]],
    transactions: List[Dict[str, Any]],
    complaints: List[Dict[str, Any]],
    matches: List[Dict[str, Any]],
    found_items_by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    normalized_bookings: List[Dict[str, Any]] = []
    normalized_transactions: List[Dict[str, Any]] = []
    normalized_complaints: List[Dict[str, Any]] = []
    normalized_matches: List[Dict[str, Any]] = []

    for booking in bookings:
        booking_datetime = resolve_record_datetime(booking, "booking_date", "created_at")
        total_fare = safe_float(booking.get("total_fare"), 0.0)
        ticket_count = safe_int(booking.get("ticket_count"), 1) or 1
        raw_status = str(booking.get("status") or "active").strip().lower()
        normalized_bookings.append(
            {
                **booking,
                "_datetime": booking_datetime,
                "_fare": total_fare,
                "_ticket_count": ticket_count,
                "_status": raw_status,
                "_timeline_status": map_ticket_timeline_status(raw_status, booking_datetime, now),
                "_route": f"{booking.get('from_station', 'Unknown')} -> {booking.get('to_station', 'Unknown')}",
            }
        )

    for transaction in transactions:
        transaction_datetime = resolve_record_datetime(transaction, "created_at")
        normalized_transactions.append(
            {
                **transaction,
                "_datetime": transaction_datetime,
                "_amount": safe_float(transaction.get("amount"), 0.0),
                "_type": str(transaction.get("type") or "").strip().lower(),
            }
        )

    for complaint in complaints:
        complaint_datetime = resolve_record_datetime(complaint, "created_at")
        normalized_complaints.append(
            {
                **complaint,
                "_datetime": complaint_datetime,
                "_status": str(complaint.get("status") or "searching").strip().lower(),
                "_dashboard_status": map_complaint_status(complaint.get("status") or "searching"),
            }
        )

    for match in matches:
        match_datetime = resolve_record_datetime(match, "created_at")
        normalized_matches.append(
            {
                **match,
                "_datetime": match_datetime,
                "_status": str(match.get("status") or "pending").strip().lower(),
                "_match_score": safe_float(match.get("match_score"), 0.0),
                "_found_item": found_items_by_id.get(str(match.get("found_item_id"))),
            }
        )

    min_datetime = datetime.min.replace(tzinfo=timezone.utc)
    normalized_bookings.sort(key=lambda item: item["_datetime"] or min_datetime, reverse=True)
    normalized_transactions.sort(key=lambda item: item["_datetime"] or min_datetime, reverse=True)
    normalized_complaints.sort(key=lambda item: item["_datetime"] or min_datetime, reverse=True)
    normalized_matches.sort(key=lambda item: item["_datetime"] or min_datetime, reverse=True)

    total_tickets_booked = sum(item["_ticket_count"] for item in normalized_bookings)
    total_amount_spent = round(sum(item["_fare"] for item in normalized_bookings), 2)
    upcoming_ticket_count = sum(1 for item in normalized_bookings if item["_timeline_status"] == "Upcoming")
    monthly_booking_trend = build_monthly_series(normalized_bookings, 6, lambda item: item["_datetime"])
    monthly_spend_trend = build_monthly_series(
        normalized_bookings,
        6,
        lambda item: item["_datetime"],
        lambda item: item["_fare"],
    )
    station_counter = Counter()
    for booking in normalized_bookings:
        if booking.get("from_station"):
            station_counter[str(booking["from_station"])] += 1
        if booking.get("to_station"):
            station_counter[str(booking["to_station"])] += 1
    route_counter = Counter(booking["_route"] for booking in normalized_bookings)
    peak_hour_series = build_hourly_distribution(normalized_bookings, lambda item: item["_datetime"])
    peak_hour_entry = max(peak_hour_series, key=lambda row: row["value"], default=None)
    peak_hour_value = peak_hour_entry["hour"] if peak_hour_entry and peak_hour_entry["value"] > 0 else None
    complaint_status_counter = Counter(item["_dashboard_status"] for item in normalized_complaints)
    active_complaints = sum(
        1 for item in normalized_complaints if item["_dashboard_status"] in {"Pending", "Matched"}
    )
    most_frequent_stations = top_counter_items(station_counter, limit=6)
    suggested_routes = [
        {
            "route": route,
            "bookings": count,
            "message": f"Used {count} time(s); good candidate for one-tap quick booking.",
        }
        for route, count in route_counter.most_common(3)
    ]
    travel_pattern_note = "Travel history will unlock smarter route suggestions."
    if suggested_routes:
        travel_pattern_note = (
            f"Your strongest repeat pattern is {suggested_routes[0]['route']}. "
            f"Peak usage clusters around {format_hour_window(peak_hour_value)}."
            if peak_hour_value is not None
            else f"Your strongest repeat pattern is {suggested_routes[0]['route']}."
        )

    complaint_match_counts = Counter(str(match.get("lost_item_id")) for match in normalized_matches if match.get("lost_item_id"))
    ticket_history = [
        {
            "booking_id": str(booking.get("id")),
            "from_station": booking.get("from_station"),
            "to_station": booking.get("to_station"),
            "travel_date": serialize_datetime(booking["_datetime"]),
            "fare": round(booking["_fare"], 2),
            "ticket_count": booking["_ticket_count"],
            "status": booking["_timeline_status"],
            "raw_status": booking["_status"],
        }
        for booking in normalized_bookings[:20]
    ]
    complaint_items = [
        {
            "complaint_id": str(complaint.get("id")),
            "item_name": complaint.get("item_name"),
            "station": complaint.get("station"),
            "description": complaint.get("description"),
            "status": complaint["_dashboard_status"],
            "submitted_at": serialize_datetime(complaint["_datetime"]),
            "image_url": complaint.get("image_url"),
            "match_count": complaint_match_counts.get(str(complaint.get("id")), 0),
        }
        for complaint in normalized_complaints[:20]
    ]
    complaint_matches = [
        {
            "match_id": str(match.get("id")),
            "complaint_id": str(match.get("lost_item_id")),
            "status": map_complaint_status(match.get("status") or "pending"),
            "match_score": round(match["_match_score"] * 100, 2) if match["_match_score"] <= 1 else round(match["_match_score"], 2),
            "found_item": {
                "id": str((match["_found_item"] or {}).get("id")) if (match["_found_item"] or {}).get("id") is not None else None,
                "item_name": (match["_found_item"] or {}).get("item_name"),
                "station": (match["_found_item"] or {}).get("station"),
                "reported_by": (match["_found_item"] or {}).get("reported_by"),
            },
            "created_at": serialize_datetime(match["_datetime"]),
        }
        for match in normalized_matches[:10]
    ]
    recent_transactions = [
        {
            "transaction_id": str(transaction.get("id")),
            "type": transaction["_type"],
            "amount": round(transaction["_amount"], 2),
            "from_station": transaction.get("from_station"),
            "to_station": transaction.get("to_station"),
            "created_at": serialize_datetime(transaction["_datetime"]),
        }
        for transaction in normalized_transactions[:10]
    ]

    return {
        "generated_at": now.isoformat(),
        "profile": {
            "user_id": str(current_user.get("id")),
            "name": current_user.get("full_name"),
            "email": current_user.get("email"),
            "role": current_user.get("user_type"),
            "last_login_time": current_user.get("last_login_at") or current_user.get("session_issued_at"),
            "account_status": current_user.get("account_status", "active"),
        },
        "overview": {
            "total_tickets_booked": total_tickets_booked,
            "total_amount_spent": total_amount_spent,
            "upcoming_tickets": upcoming_ticket_count,
            "active_complaints": active_complaints,
            "smart_card_balance": round(safe_float((card or {}).get("balance"), 0.0), 2),
        },
        "ticket_history": ticket_history,
        "personal_analytics": {
            "total_tickets_booked": total_tickets_booked,
            "total_amount_spent": total_amount_spent,
            "monthly_booking_trend": monthly_booking_trend,
            "monthly_spend_trend": monthly_spend_trend,
            "most_frequently_used_stations": most_frequent_stations,
            "peak_travel_times": peak_hour_series,
            "favorite_routes": [
                {"label": route, "value": count}
                for route, count in route_counter.most_common(5)
            ],
        },
        "lost_and_found": {
            "summary": {
                "total_complaints": len(normalized_complaints),
                "active_complaints": active_complaints,
                "resolved_complaints": complaint_status_counter.get("Resolved", 0),
                "matched_complaints": complaint_status_counter.get("Matched", 0),
            },
            "complaints": complaint_items,
            "matches": complaint_matches,
        },
        "smart_insights": {
            "suggested_frequent_routes": suggested_routes,
            "peak_travel_window": format_hour_window(peak_hour_value),
            "travel_pattern_note": travel_pattern_note,
        },
        "smart_card": {
            "card_number_masked": mask_card_number((card or {}).get("card_number")),
            "balance": round(safe_float((card or {}).get("balance"), 0.0), 2),
            "recent_transactions": recent_transactions,
        },
        "charts": {
            "monthly_booking_trend": monthly_booking_trend,
            "monthly_spend_trend": monthly_spend_trend,
            "station_frequency": most_frequent_stations,
            "peak_travel_times": peak_hour_series,
            "complaint_status": [
                {"label": label, "value": count}
                for label, count in complaint_status_counter.items()
            ],
        },
    }


def build_admin_dashboard_contract(
    current_user: Dict[str, Any],
    users: List[Dict[str, Any]],
    bookings: List[Dict[str, Any]],
    complaints: List[Dict[str, Any]],
    matches: List[Dict[str, Any]],
    found_items: List[Dict[str, Any]],
    stations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    normalized_users: List[Dict[str, Any]] = []
    normalized_bookings: List[Dict[str, Any]] = []
    normalized_complaints: List[Dict[str, Any]] = []
    normalized_matches: List[Dict[str, Any]] = []
    normalized_found_items: List[Dict[str, Any]] = []
    station_id_to_name = {
        str(station.get("id")): station.get("name")
        for station in stations
        if station.get("id") is not None
    }

    for user in users:
        normalized_users.append(
            {
                **user,
                "user_type": normalize_user_type(user.get("user_type")),
                "account_status": resolve_user_account_status(user),
                "last_login_at": resolve_user_last_login(user),
            }
        )

    for booking in bookings:
        booking_datetime = resolve_record_datetime(booking, "booking_date", "created_at")
        normalized_bookings.append(
            {
                **booking,
                "_datetime": booking_datetime,
                "_fare": safe_float(booking.get("total_fare"), 0.0),
                "_ticket_count": safe_int(booking.get("ticket_count"), 1) or 1,
            }
        )

    for complaint in complaints:
        complaint_datetime = resolve_record_datetime(complaint, "created_at")
        normalized_complaints.append(
            {
                **complaint,
                "_datetime": complaint_datetime,
                "_dashboard_status": map_complaint_status(complaint.get("status") or "searching"),
            }
        )

    for match in matches:
        match_datetime = resolve_record_datetime(match, "created_at")
        normalized_matches.append(
            {
                **match,
                "_datetime": match_datetime,
                "_match_score": safe_float(match.get("match_score"), 0.0),
            }
        )

    for item in found_items:
        found_datetime = resolve_record_datetime(item, "created_at")
        normalized_found_items.append({**item, "_datetime": found_datetime})

    min_datetime = datetime.min.replace(tzinfo=timezone.utc)
    normalized_bookings.sort(key=lambda item: item["_datetime"] or min_datetime, reverse=True)
    normalized_complaints.sort(key=lambda item: item["_datetime"] or min_datetime, reverse=True)
    normalized_matches.sort(key=lambda item: item["_datetime"] or min_datetime, reverse=True)
    normalized_found_items.sort(key=lambda item: item["_datetime"] or min_datetime, reverse=True)

    total_revenue = round(sum(item["_fare"] for item in normalized_bookings), 2)
    daily_bookings = build_daily_series(normalized_bookings, 14, lambda item: item["_datetime"])
    monthly_bookings = build_monthly_series(normalized_bookings, 6, lambda item: item["_datetime"])
    revenue_analysis = build_monthly_series(
        normalized_bookings,
        6,
        lambda item: item["_datetime"],
        lambda item: item["_fare"],
    )

    station_counter = Counter()
    station_hour_counter = Counter()
    for booking in normalized_bookings:
        station_name = str(booking.get("from_station") or booking.get("to_station") or "Unknown")
        if booking.get("from_station"):
            station_counter[str(booking.get("from_station"))] += booking["_ticket_count"]
        if booking.get("to_station"):
            station_counter[str(booking.get("to_station"))] += booking["_ticket_count"]
        if booking["_datetime"] is not None:
            station_hour_counter[(station_name, booking["_datetime"].hour)] += booking["_ticket_count"]

    peak_hours = build_hourly_distribution(normalized_bookings, lambda item: item["_datetime"])
    high_risk_stations_counter = Counter(
        str(complaint.get("station") or "Unknown")
        for complaint in normalized_complaints
        if complaint.get("station")
    )
    complaint_status_counter = Counter(
        complaint["_dashboard_status"] for complaint in normalized_complaints
    )
    match_count_by_complaint = Counter(
        str(match.get("lost_item_id")) for match in normalized_matches if match.get("lost_item_id")
    )
    booking_count_by_email = Counter(
        str(booking.get("user_email") or "").strip().lower()
        for booking in normalized_bookings
        if booking.get("user_email")
    )
    user_name_by_email = {
        str(user.get("email") or "").strip().lower(): (user.get("full_name") or "Unknown User")
        for user in normalized_users
        if user.get("email")
    }
    spend_by_email = Counter()
    for booking in normalized_bookings:
        email = str(booking.get("user_email") or "").strip().lower()
        if email:
            spend_by_email[email] += booking["_fare"]

    user_management = []
    for user in normalized_users:
        email = str(user.get("email") or "").strip().lower()
        last_booking = next(
            (booking for booking in normalized_bookings if str(booking.get("user_email") or "").strip().lower() == email),
            None,
        )
        user_management.append(
            {
                "user_id": str(user.get("id")),
                "name": user.get("full_name"),
                "email": user.get("email"),
                "role": user.get("user_type"),
                "status": user.get("account_status"),
                "last_login_time": user.get("last_login_at"),
                "total_bookings": booking_count_by_email.get(email, 0),
                "total_spend": round(spend_by_email.get(email, 0.0), 2),
                "last_booking_at": serialize_datetime(resolve_record_datetime(last_booking or {}, "booking_date", "created_at")),
            }
        )
    user_management.sort(
        key=lambda item: (item["status"] != "active", -item["total_spend"]),
    )

    complaint_list = []
    for complaint in normalized_complaints[:50]:
        complaint_list.append(
            {
                "complaint_id": str(complaint.get("id")),
                "user_email": complaint.get("user_email"),
                "user_name": user_name_by_email.get(str(complaint.get("user_email") or "").strip().lower(), "Unknown User"),
                "item_name": complaint.get("item_name"),
                "station": complaint.get("station"),
                "status": complaint["_dashboard_status"],
                "submitted_at": serialize_datetime(complaint["_datetime"]),
                "description": complaint.get("description"),
                "image_url": complaint.get("image_url"),
                "match_count": match_count_by_complaint.get(str(complaint.get("id")), 0),
            }
        )

    available_found_items = [
        {
            "found_item_id": str(item.get("id")),
            "item_name": item.get("item_name"),
            "station": item.get("station"),
            "reported_by": item.get("reported_by"),
            "reported_at": serialize_datetime(item["_datetime"]),
        }
        for item in normalized_found_items[:50]
    ]

    crowd_prediction_summary = [
        {
            "station": station,
            "peak_window": format_hour_window(hour_value),
            "estimated_load": count,
            "note": f"{station} is seeing concentrated booking activity in this hour block.",
        }
        for (station, hour_value), count in station_hour_counter.most_common(5)
    ]

    return {
        "generated_at": now.isoformat(),
        "admin": {
            "user_id": str(current_user.get("id")),
            "name": current_user.get("full_name"),
            "email": current_user.get("email"),
            "role": current_user.get("user_type"),
        },
        "system_overview": {
            "total_users": len(normalized_users),
            "total_bookings": len(normalized_bookings),
            "total_revenue": total_revenue,
            "total_complaints": len(normalized_complaints),
            "total_matches": len(normalized_matches),
            "total_stations": len(stations),
        },
        "global_analytics": {
            "daily_bookings_trend": daily_bookings,
            "monthly_bookings_trend": monthly_bookings,
            "revenue_analysis": revenue_analysis,
            "most_crowded_stations": top_counter_items(station_counter, limit=8),
            "peak_hours_analysis": peak_hours,
            "complaint_status_breakdown": [
                {"label": label, "value": value}
                for label, value in complaint_status_counter.items()
            ],
        },
        "user_management": user_management[:100],
        "station_management": {
            "stations": [
                {
                    "station_id": str(station.get("id")),
                    "name": station.get("name"),
                    "line": station.get("line"),
                    "sequence": safe_int(station.get("sequence"), 0),
                    "is_interchange": bool(station.get("is_interchange")),
                    "is_elevated": bool(station.get("is_elevated")),
                    "station_type": station.get("station_type") or "residential",
                    "line_color": station.get("line_color") or line_to_color(str(station.get("line") or "")),
                }
                for station in sorted(stations, key=lambda item: (str(item.get("line") or ""), safe_int(item.get("sequence"), 0)))
            ]
        },
        "lost_found_management": {
            "summary": {
                "pending": complaint_status_counter.get("Pending", 0),
                "matched": complaint_status_counter.get("Matched", 0),
                "resolved": complaint_status_counter.get("Resolved", 0),
            },
            "complaints": complaint_list,
            "available_found_items": available_found_items,
        },
        "advanced_insights": {
            "high_risk_stations": [
                {"label": label, "value": value}
                for label, value in high_risk_stations_counter.most_common(6)
            ],
            "crowd_prediction_summary": crowd_prediction_summary,
        },
        "reference_data": {
            "station_lookup": station_id_to_name,
        },
    }
    graphs["complaint_status"] = top_counter_items(
        Counter(complaint["_status"].replace("_", " ").title() for complaint in normalized_complaints),
        limit=6,
    )

    ticket_usage_category = "Low traveler"
    if len(normalized_bookings) >= 20:
        ticket_usage_category = "Frequent traveler"
    elif len(normalized_bookings) >= 8:
        ticket_usage_category = "Moderate traveler"

    personalized_travel_category = "Occasional traveler"
    if favorite_station_category == "office" and peak_hour is not None and (7 <= peak_hour <= 10 or 17 <= peak_hour <= 20):
        personalized_travel_category = "Office commuter"
    elif favorite_station_category == "tourist":
        personalized_travel_category = "Tourist"
    elif len(normalized_bookings) >= 18:
        personalized_travel_category = "Regular traveler"

    if peak_hour is not None and 7 <= peak_hour <= 9:
        best_time_suggestion = "Try after 10 AM for a calmer ride on your common route."
    elif peak_hour is not None and 17 <= peak_hour <= 20:
        best_time_suggestion = "If possible, travel before 4 PM to avoid the evening rush."
    elif peak_hour is not None:
        best_time_suggestion = f"Your usual {peak_hour_label} slot already looks balanced for regular travel."
    else:
        best_time_suggestion = "Book a few trips to unlock personalized timing suggestions."

    avg_daily_debit_series = build_daily_series(
        debit_transactions,
        30,
        lambda transaction: transaction["_datetime"],
        lambda transaction: transaction["_amount"],
    )
    active_debit_days = [point["value"] for point in avg_daily_debit_series if point["value"] > 0]
    avg_daily_debit_spend = round(sum(active_debit_days) / max(len(active_debit_days), 1), 2) if active_debit_days else 0.0
    if card_balance <= low_balance_threshold:
        low_balance_prediction_value = "Balance is already near the low threshold"
    elif avg_daily_debit_spend > 0:
        days_to_low_balance = max(int((card_balance - low_balance_threshold) / avg_daily_debit_spend), 0)
        low_balance_prediction_value = f"Balance may feel low in about {days_to_low_balance} day(s)"
    else:
        low_balance_prediction_value = "Not enough debit history to estimate low-balance timing"

    active_match = next((match for match in normalized_matches if match["_status"] not in {"rejected", "accepted"}), None)
    oldest_active_complaint = active_complaints[-1] if active_complaints else None
    active_complaint_probability = "No active complaint"
    if active_complaints:
        if active_match:
            active_complaint_probability = "High (active match found)"
        elif oldest_active_complaint and oldest_active_complaint["_datetime"] and (now - oldest_active_complaint["_datetime"]).days <= 3:
            active_complaint_probability = "Medium (recent complaint still being processed)"
        else:
            active_complaint_probability = "Low to medium (no current match yet)"

    suggested_recharge_amount = nearest_recharge_amount(
        max(average_spend_per_trip * 8, monthly_spend / max(days_elapsed, 1) * 7, 100)
    )

    active_tickets = [
        {
            "booking_id": str(booking.get("id")),
            "from_station": booking.get("from_station"),
            "to_station": booking.get("to_station"),
            "booking_date": serialize_datetime(booking["_datetime"]),
            "ticket_count": booking["_ticket_count"],
            "total_fare": round(booking["_fare"], 2),
            "payment_method": booking["_payment_method"],
            "status": booking["_status"],
        }
        for booking in active_bookings[:6]
    ]

    recent_bookings = [
        {
            "booking_id": str(booking.get("id")),
            "from_station": booking.get("from_station"),
            "to_station": booking.get("to_station"),
            "booking_date": serialize_datetime(booking["_datetime"]),
            "ticket_count": booking["_ticket_count"],
            "total_fare": round(booking["_fare"], 2),
            "payment_method": booking["_payment_method"],
            "status": booking["_status"],
        }
        for booking in normalized_bookings[:10]
    ]

    booking_summary = {
        "total_bookings": len(normalized_bookings),
        "cancelled_bookings": len(cancelled_bookings),
        "completed_bookings": len(completed_bookings),
        "active_bookings": len(active_bookings),
        "next_active_ticket": {
            "route": top_active_booking["_route"],
            "booking_date": serialize_datetime(top_active_booking["_datetime"]),
            "fare": round(top_active_booking["_fare"], 2),
        } if top_active_booking else None,
        "latest_active_route": top_active_booking["_route"] if top_active_booking else "No active route",
    }

    smart_card_summary = {
        "card_number_masked": mask_card_number(card.get("card_number") if card else None),
        "current_balance": round(card_balance, 2),
        "total_recharge_count": len(credit_transactions),
        "total_recharge_amount": round(total_recharge_amount, 2),
        "total_debit_amount": round(total_debit_amount, 2),
        "last_recharge_date": serialize_datetime(last_recharge["_datetime"]) if last_recharge else None,
        "last_debit_date": serialize_datetime(last_debit["_datetime"]) if last_debit else None,
        "average_spend_per_trip": average_spend_per_trip,
        "low_balance_warning": card_balance < low_balance_threshold,
        "low_balance_threshold": round(low_balance_threshold, 2),
        "recharge_suggestion": suggested_recharge_amount,
    }

    recent_transactions = [
        {
            "id": str(transaction.get("id")),
            "type": transaction["_type"],
            "amount": round(transaction["_amount"], 2),
            "from_station": transaction.get("from_station"),
            "to_station": transaction.get("to_station"),
            "created_at": serialize_datetime(transaction["_datetime"]),
        }
        for transaction in normalized_transactions[:10]
    ]

    complaint_matches = []
    for match in normalized_matches[:5]:
        found_item = match["_found_item"] or {}
        complaint_matches.append(
            {
                "match_id": str(match.get("id")),
                "status": match["_status"],
                "match_confidence": round(match["_match_score"] * 100, 2) if match["_match_score"] <= 1 else round(match["_match_score"], 2),
                "found_item": {
                    "item_name": found_item.get("item_name"),
                    "station": found_item.get("station"),
                    "reported_by": found_item.get("reported_by"),
                    "created_at": serialize_datetime(resolve_record_datetime(found_item, "created_at")),
                },
                "created_at": serialize_datetime(match["_datetime"]),
            }
        )

    complaints_payload = {
        "summary": {
            "total_complaints": len(normalized_complaints),
            "active_complaints": len(active_complaints),
            "resolved_complaints": len(resolved_complaints),
            "latest_complaint": {
                "item_name": latest_complaint.get("item_name"),
                "station": latest_complaint.get("station"),
                "status": latest_complaint["_status"],
                "created_at": serialize_datetime(latest_complaint["_datetime"]),
            } if latest_complaint else None,
        },
        "recent": [
            {
                "id": str(complaint.get("id")),
                "item_name": complaint.get("item_name"),
                "station": complaint.get("station"),
                "status": complaint["_status"],
                "created_at": serialize_datetime(complaint["_datetime"]),
            }
            for complaint in normalized_complaints[:6]
        ],
        "potential_matches": complaint_matches,
    }

    predictions = [
        {
            "title": "Peak Travel Time Prediction",
            "value": peak_hour_label,
            "description": "Based on your booking history, this is the hour you use the metro most often.",
            "confidence": 88 if peak_hour is not None else 40,
        },
        {
            "title": "Next Likely Travel Time",
            "value": peak_hour_label,
            "description": "Estimated from your most repeated travel hour and recent booking behavior.",
            "confidence": 82 if peak_hour is not None else 35,
        },
        {
            "title": "Next Likely Route",
            "value": favorite_route,
            "description": "Your most frequent route is used as the next-likely trip prediction.",
            "confidence": 80 if route_counter else 35,
        },
        {
            "title": "Monthly Spend Prediction",
            "value": f"Rs.{round(monthly_spend_prediction, 2)}",
            "description": "Projected from your current-month spending pace.",
            "confidence": 76 if monthly_spend else 30,
        },
        {
            "title": "Low Balance Prediction",
            "value": low_balance_prediction_value,
            "description": "Estimated using recent debit activity and your current smart card balance.",
            "confidence": 72 if debit_transactions else 30,
        },
        {
            "title": "Complaint Resolution Probability",
            "value": active_complaint_probability,
            "description": "Derived from complaint age and whether a potential match already exists.",
            "confidence": 68 if active_complaints else 20,
        },
        {
            "title": "Best Time to Travel Suggestion",
            "value": best_time_suggestion,
            "description": "A simple recommendation built from your usual travel window and route pattern.",
            "confidence": 70 if peak_hour is not None else 25,
        },
        {
            "title": "Recharge Recommendation",
            "value": f"Rs.{suggested_recharge_amount}",
            "description": "Suggested recharge amount based on your recent spend and trip pattern.",
            "confidence": 84 if normalized_bookings else 40,
        },
        {
            "title": "Ticket Usage Trend Prediction",
            "value": ticket_usage_category,
            "description": "This classifies your ticket activity as frequent, moderate, or low usage.",
            "confidence": 78 if normalized_bookings else 20,
        },
        {
            "title": "Personalized Travel Category",
            "value": personalized_travel_category,
            "description": "A practical label inferred from your favorite route, travel hour, and station profile.",
            "confidence": 74 if normalized_bookings else 25,
        },
    ]

    recommendations: List[Dict[str, Any]] = []
    if peak_hour is not None and (7 <= peak_hour <= 9 or 17 <= peak_hour <= 20):
        recommendations.append(
            {
                "title": "Avoid your usual rush slot",
                "description": f"You often travel around {peak_hour_label}. Shifting a little later could mean a smoother trip.",
                "action_label": "Book smarter",
                "action_href": "/book-ticket",
            }
        )
    if card_balance < low_balance_threshold:
        recommendations.append(
            {
                "title": "Recharge before your next trip",
                "description": f"Your balance is getting close to your usual usage. A recharge of Rs.{suggested_recharge_amount} should keep you covered.",
                "action_label": "Recharge card",
                "action_href": "/smart-card",
            }
        )
    if favorite_route != "No route data yet":
        recommendations.append(
            {
                "title": "Your most used route is ready",
                "description": f"{favorite_route} is your top route. Keep it in mind for faster repeat bookings.",
                "action_label": "View bookings",
                "action_href": "/my-bookings",
            }
        )
    if weekend_spend > weekday_spend and len(normalized_bookings) > 3:
        recommendations.append(
            {
                "title": "Weekend spending is higher for you",
                "description": "You spend more on weekends than weekdays. Planning ahead could help reduce last-minute ticket costs.",
                "action_label": "See travel stats",
                "action_href": "/dashboard",
            }
        )
    if most_used_payment_method != "Smart Card" and len(normalized_bookings) >= 3:
        recommendations.append(
            {
                "title": "Use smart card more often",
                "description": "Most of your payments are not through Smart Card yet. Using it more can make repeat travel faster.",
                "action_label": "Open smart card",
                "action_href": "/smart-card",
            }
        )
    if active_complaints:
        recommendations.append(
            {
                "title": "Track your unresolved complaint",
                "description": "You still have an open complaint. Checking for updates regularly can help you respond quickly to matches.",
                "action_label": "Track complaint",
                "action_href": "/lost-found",
            }
        )

    alerts: List[Dict[str, Any]] = []
    if card_balance < low_balance_threshold:
        alerts.append(
            {
                "severity": "warning",
                "title": "Low smart card balance",
                "message": f"Your current balance is Rs.{round(card_balance, 2)}. Consider recharging before your next ride.",
                "action_href": "/smart-card",
            }
        )
    if top_active_booking:
        alerts.append(
            {
                "severity": "info",
                "title": "You have an active ticket",
                "message": f"Your latest active route is {top_active_booking['_route']}. Keep it handy if you need to view it again.",
                "action_href": "/my-bookings",
            }
        )
    if active_complaints:
        alerts.append(
            {
                "severity": "warning",
                "title": "Complaint still open",
                "message": f"You currently have {len(active_complaints)} unresolved complaint(s).",
                "action_href": "/lost-found",
            }
        )
    if cancelled_bookings:
        alerts.append(
            {
                "severity": "neutral",
                "title": "Recent cancelled booking found",
                "message": "One of your recent bookings was cancelled. You can review the details in My Bookings.",
                "action_href": "/my-bookings",
            }
        )
    if favorite_source_counter and peak_hour is not None and favorite_station_category in {"office", "transport", "market"} and (
        7 <= peak_hour <= 10 or 17 <= peak_hour <= 20
    ):
        alerts.append(
            {
                "severity": "danger",
                "title": "Crowd warning on your common station",
                "message": f"{favorite_source_station} is likely to feel busy around your usual {peak_hour_label} travel window.",
                "action_href": "/stations",
            }
        )
    if favorite_route != "No route data yet":
        alerts.append(
            {
                "severity": "info",
                "title": "Route advisory",
                "message": f"Your common route is {favorite_route}. Checking station crowd before departure can help you time it better.",
                "action_href": "/stations",
            }
        )

    recent_activity = []
    for booking in normalized_bookings[:5]:
        recent_activity.append(
            {
                "type": "booking",
                "title": f"Booked {booking['_route']}",
                "description": f"{booking['_ticket_count']} ticket(s) via {booking['_payment_method']} for Rs.{round(booking['_fare'], 2)}.",
                "created_at": serialize_datetime(booking["_datetime"]),
                "status": booking["_status"],
            }
        )
    for transaction in normalized_transactions[:5]:
        direction = "Recharge" if transaction["_type"] == "credit" else "Travel debit"
        route_fragment = ""
        if transaction.get("from_station") and transaction.get("to_station"):
            route_fragment = f" on {transaction.get('from_station')} -> {transaction.get('to_station')}"
        recent_activity.append(
            {
                "type": "transaction",
                "title": f"{direction}{route_fragment}",
                "description": f"Amount: Rs.{round(transaction['_amount'], 2)}",
                "created_at": serialize_datetime(transaction["_datetime"]),
                "status": transaction["_type"],
            }
        )
    for complaint in normalized_complaints[:4]:
        recent_activity.append(
            {
                "type": "complaint",
                "title": f"Complaint logged for {complaint.get('item_name')}",
                "description": f"Status: {complaint['_status'].replace('_', ' ').title()} at {complaint.get('station', 'Unknown station')}.",
                "created_at": serialize_datetime(complaint["_datetime"]),
                "status": complaint["_status"],
            }
        )

    recent_activity.sort(
        key=lambda item: parse_datetime_value(item.get("created_at")) or min_dashboard_datetime,
        reverse=True,
    )

    return {
        "user": {
            "id": str(current_user.get("id")),
            "full_name": current_user.get("full_name"),
            "email": current_user.get("email"),
            "user_type": current_user.get("user_type"),
        },
        "generated_at": now.isoformat(),
        "kpis": kpis,
        "graphs": graphs,
        "active_tickets": active_tickets,
        "booking_summary": booking_summary,
        "recent_bookings": recent_bookings,
        "smart_card": smart_card_summary,
        "recent_transactions": recent_transactions,
        "complaints": complaints_payload,
        "predictions": predictions,
        "recommendations": recommendations[:8],
        "recent_activity": recent_activity[:10],
        "alerts": alerts[:6],
        "quick_actions": [
            {"label": "Book Ticket", "href": "/book-ticket"},
            {"label": "Recharge Smart Card", "href": "/smart-card"},
            {"label": "View All Bookings", "href": "/my-bookings"},
            {"label": "Track Complaint", "href": "/lost-found"},
            {"label": "Search Station", "href": "/stations"},
            {"label": "View Nearby Places", "href": "/nearby-places"},
        ],
    }

# API Endpoints

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Serve the auth page as the landing page"""
    return templates.TemplateResponse(request=request, name="auth.html")

@app.get("/api")
async def api_info():
    return {"message": "Metro Mate API"}

# Frontend Page Routes
@app.get("/home", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    _, redirect_response = authorize_template_route(request, "user")
    if redirect_response is not None:
        return redirect_response
    return templates.TemplateResponse(request=request, name="user_dashboard_role_based.html")

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    _, redirect_response = authorize_template_route(request, "admin")
    if redirect_response is not None:
        return redirect_response
    return templates.TemplateResponse(request=request, name="admin_dashboard_live.html")

@app.get("/stations", response_class=HTMLResponse)
async def stations_page(request: Request, format: Optional[str] = None):
    accept_header = request.headers.get("accept", "")
    wants_json = format == "json" or "application/json" in accept_header.lower()

    try:
        stations = fetch_station_directory_from_supabase()
        station_payload = [station.model_dump() for station in stations]

        if wants_json:
            logger.info("Serving /stations as JSON directory data")
            return JSONResponse(content=station_payload)

        return templates.TemplateResponse(
            request=request,
            name="stations.html",
            context={
                "stations": station_payload,
                "stations_by_line": group_stations_by_line(stations),
                "station_count": len(stations),
                "page_error": None,
            },
        )
    except HTTPException:
        if wants_json:
            raise
        logger.exception("Could not load station directory for stations page")
    except Exception:
        if wants_json:
            logger.exception("Could not load station directory as JSON")
            raise HTTPException(status_code=500, detail="Unable to load station directory")
        logger.exception("Unexpected error while loading stations page")

    return templates.TemplateResponse(
        request=request,
        name="stations.html",
        context={
            "stations": [],
            "stations_by_line": [],
            "station_count": 0,
            "page_error": "Stations could not be loaded right now. Please try again in a moment.",
        },
    )

@app.get("/book-ticket", response_class=HTMLResponse)
async def book_ticket_page(request: Request):
    _, redirect_response = authorize_template_route(request, "user")
    if redirect_response is not None:
        return redirect_response
    return templates.TemplateResponse(request=request, name="book_ticket.html")

@app.get("/nearby-places", response_class=HTMLResponse)
async def nearby_places_page(request: Request):
    _, redirect_response = authorize_template_route(request, "user")
    if redirect_response is not None:
        return redirect_response
    return templates.TemplateResponse(request=request, name="nearby_places.html")

@app.get("/test-view-details", response_class=HTMLResponse, include_in_schema=False)
async def test_view_details_page(request: Request):
    return RedirectResponse(url="/nearby-places", status_code=307)

@app.get("/animated-train", response_class=HTMLResponse, include_in_schema=False)
async def animated_train_page(request: Request):
    return RedirectResponse(url="/home", status_code=307)

@app.get("/lost-found", response_class=HTMLResponse)
async def lost_found_page(request: Request):
    _, redirect_response = authorize_template_route(request, "user")
    if redirect_response is not None:
        return redirect_response
    return templates.TemplateResponse(request=request, name="lost_found_fixed.html")

@app.get("/station-test", response_class=HTMLResponse, include_in_schema=False)
async def station_test_page(request: Request):
    return RedirectResponse(url="/stations", status_code=307)

@app.get("/smart-card", response_class=HTMLResponse)
async def smart_card_page(request: Request):
    _, redirect_response = authorize_template_route(request, "user")
    if redirect_response is not None:
        return redirect_response
    return templates.TemplateResponse(request=request, name="smart_card.html")

@app.get("/my-bookings", response_class=HTMLResponse)
async def my_bookings_page(request: Request):
    _, redirect_response = authorize_template_route(request, "user")
    if redirect_response is not None:
        return redirect_response
    return templates.TemplateResponse(request=request, name="my_bookings.html")

@app.get("/debug-stations", response_class=HTMLResponse, include_in_schema=False)
async def debug_stations_page(request: Request):
    return RedirectResponse(url="/stations", status_code=307)

@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    _, redirect_response = authorize_template_route(request, "admin")
    if redirect_response is not None:
        return redirect_response
    return templates.TemplateResponse(request=request, name="analytics.html")

@app.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse(request=request, name="forgot-password.html")

# Personalized user dashboard API
@app.get("/user-dashboard")
@app.get("/api/dashboard/user")
async def get_user_dashboard(request: Request):
    try:
        current_user = get_authenticated_user(request, required_user_type="user")
        user_email = current_user["email"]

        bookings_response = (
            supabase.table("bookings")
            .select("*")
            .eq("user_email", user_email)
            .order("booking_date", desc=True)
            .execute()
        )
        if bookings_response.data is None:
            raise HTTPException(status_code=500, detail="Failed to load bookings for dashboard")

        card_response = (
            supabase.table("smart_cards")
            .select("*")
            .eq("user_email", user_email)
            .limit(1)
            .execute()
        )
        if card_response.data is None:
            raise HTTPException(status_code=500, detail="Failed to load smart card for dashboard")

        transactions_response = (
            supabase.table("card_transactions")
            .select("*")
            .eq("user_email", user_email)
            .order("created_at", desc=True)
            .execute()
        )
        if transactions_response.data is None:
            raise HTTPException(status_code=500, detail="Failed to load card transactions for dashboard")

        complaints_response = (
            supabase.table("lost_items")
            .select("*")
            .eq("user_email", user_email)
            .order("created_at", desc=True)
            .execute()
        )
        if complaints_response.data is None:
            raise HTTPException(status_code=500, detail="Failed to load complaints for dashboard")

        complaint_ids = [complaint["id"] for complaint in complaints_response.data if complaint.get("id") is not None]
        matches_data: List[Dict[str, Any]] = []
        found_items_by_id: Dict[str, Dict[str, Any]] = {}

        if complaint_ids:
            matches_response = (
                supabase.table("matches")
                .select("*")
                .in_("lost_item_id", complaint_ids)
                .order("created_at", desc=True)
                .execute()
            )
            if matches_response.data is None:
                raise HTTPException(status_code=500, detail="Failed to load complaint matches for dashboard")

            matches_data = matches_response.data
            found_item_ids = [match["found_item_id"] for match in matches_data if match.get("found_item_id") is not None]
            if found_item_ids:
                found_items_response = (
                    supabase.table("found_items")
                    .select("*")
                    .in_("id", found_item_ids)
                    .execute()
                )
                if found_items_response.data is None:
                    raise HTTPException(status_code=500, detail="Failed to load matched found items for dashboard")

                found_items_by_id = {
                    str(found_item["id"]): found_item
                    for found_item in found_items_response.data
                    if found_item.get("id") is not None
                }

        return build_user_dashboard_contract(
            current_user=current_user,
            bookings=bookings_response.data,
            card=card_response.data[0] if card_response.data else None,
            transactions=transactions_response.data,
            complaints=complaints_response.data,
            matches=matches_data,
            found_items_by_id=found_items_by_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unable to build personalized dashboard")
        raise HTTPException(status_code=500, detail=f"Unable to load dashboard right now: {str(exc)}")


@app.get("/api/dashboard/admin")
async def get_admin_dashboard(request: Request):
    try:
        current_user = get_authenticated_user(request, required_user_type="admin")

        users_response = supabase.table("users").select("*").execute()
        bookings_response = supabase.table("bookings").select("*").execute()
        complaints_response = supabase.table("lost_items").select("*").execute()
        matches_response = supabase.table("matches").select("*").execute()
        found_items_response = supabase.table("found_items").select("*").execute()
        stations_response = supabase.table("stations").select("*").order("line").order("sequence").execute()

        response_map = {
            "users": users_response,
            "bookings": bookings_response,
            "complaints": complaints_response,
            "matches": matches_response,
            "found_items": found_items_response,
            "stations": stations_response,
        }
        for resource_name, response in response_map.items():
            if response.data is None:
                raise HTTPException(status_code=500, detail=f"Failed to load {resource_name} for admin dashboard")

        return build_admin_dashboard_contract(
            current_user=current_user,
            users=users_response.data,
            bookings=bookings_response.data,
            complaints=complaints_response.data,
            matches=matches_response.data,
            found_items=found_items_response.data,
            stations=stations_response.data,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unable to build admin dashboard")
        raise HTTPException(status_code=500, detail=f"Unable to load admin dashboard right now: {str(exc)}")


@app.patch("/api/admin/users/{user_id}/status")
async def update_user_account_status(user_id: str, payload: UserStatusUpdateRequest, request: Request):
    current_user = get_authenticated_user(request, required_user_type="admin")
    user_response = supabase.table("users").select("*").eq("id", user_id).limit(1).execute()
    if not user_response.data:
        raise HTTPException(status_code=404, detail="User not found")

    target_user = dict(user_response.data[0])
    if str(target_user.get("id")) == str(current_user.get("id")) and payload.status.strip().lower() == "blocked":
        raise HTTPException(status_code=400, detail="Admins cannot block their own account")

    update_fields = build_user_status_update_fields(target_user, payload.status)
    update_response = supabase.table("users").update(update_fields).eq("id", user_id).execute()
    if update_response.data is None:
        raise HTTPException(status_code=500, detail="Failed to update user status")

    return {
        "message": f"User status updated to {payload.status.strip().lower()}",
        "user_id": user_id,
        "status": payload.status.strip().lower(),
    }


@app.get("/api/admin/users/{user_id}")
async def get_admin_user_details(user_id: str, request: Request):
    get_authenticated_user(request, required_user_type="admin")

    user_response = supabase.table("users").select("*").eq("id", user_id).limit(1).execute()
    if not user_response.data:
        raise HTTPException(status_code=404, detail="User not found")

    user = dict(user_response.data[0])
    user.pop("password", None)
    email = str(user.get("email") or "").strip().lower()

    bookings_response = (
        supabase.table("bookings")
        .select("*")
        .eq("user_email", email)
        .order("booking_date", desc=True)
        .limit(5)
        .execute()
    )
    complaints_response = (
        supabase.table("lost_items")
        .select("*")
        .eq("user_email", email)
        .order("created_at", desc=True)
        .limit(5)
        .execute()
    )

    recent_bookings = bookings_response.data or []
    recent_complaints = complaints_response.data or []
    total_spend = round(sum(safe_float(item.get("total_fare"), 0.0) for item in recent_bookings), 2)

    return {
        "user": {
            "id": str(user.get("id")),
            "name": user.get("full_name"),
            "email": user.get("email"),
            "role": normalize_user_type(user.get("user_type")),
            "status": resolve_user_account_status(user),
            "last_login_time": resolve_user_last_login(user),
        },
        "summary": {
            "recent_booking_count": len(recent_bookings),
            "recent_complaint_count": len(recent_complaints),
            "recent_spend": total_spend,
        },
        "recent_bookings": [
            {
                "booking_id": str(item.get("id")),
                "from_station": item.get("from_station"),
                "to_station": item.get("to_station"),
                "total_fare": round(safe_float(item.get("total_fare"), 0.0), 2),
                "status": item.get("status", "active"),
                "booking_date": serialize_datetime(resolve_record_datetime(item, "booking_date", "created_at")),
            }
            for item in recent_bookings
        ],
        "recent_complaints": [
            {
                "complaint_id": str(item.get("id")),
                "item_name": item.get("item_name"),
                "station": item.get("station"),
                "status": map_complaint_status(item.get("status") or "searching"),
                "submitted_at": serialize_datetime(resolve_record_datetime(item, "created_at")),
            }
            for item in recent_complaints
        ],
    }


@app.post("/api/admin/stations")
async def create_station(payload: StationWriteRequest, request: Request):
    get_authenticated_user(request, required_user_type="admin")
    station_data = {
        "name": payload.name.strip(),
        "line": payload.line.strip(),
        "sequence": payload.sequence,
        "is_interchange": payload.is_interchange,
        "is_elevated": payload.is_elevated,
        "station_type": payload.station_type.strip().lower(),
        "line_color": payload.line_color.strip() or line_to_color(payload.line),
    }
    create_response = supabase.table("stations").insert(station_data).execute()
    if create_response.data is None:
        raise HTTPException(status_code=500, detail="Failed to create station")
    return {"message": "Station created successfully", "station": create_response.data[0]}


@app.patch("/api/admin/stations/{station_id}")
async def update_station(station_id: str, payload: StationWriteRequest, request: Request):
    get_authenticated_user(request, required_user_type="admin")
    update_payload = {
        "name": payload.name.strip(),
        "line": payload.line.strip(),
        "sequence": payload.sequence,
        "is_interchange": payload.is_interchange,
        "is_elevated": payload.is_elevated,
        "station_type": payload.station_type.strip().lower(),
        "line_color": payload.line_color.strip() or line_to_color(payload.line),
    }
    update_response = supabase.table("stations").update(update_payload).eq("id", station_id).execute()
    if update_response.data is None:
        raise HTTPException(status_code=500, detail="Failed to update station")
    return {"message": "Station updated successfully", "station": update_response.data[0] if update_response.data else None}


@app.delete("/api/admin/stations/{station_id}")
async def delete_station(station_id: str, request: Request):
    get_authenticated_user(request, required_user_type="admin")
    station_response = supabase.table("stations").select("*").eq("id", station_id).limit(1).execute()
    if not station_response.data:
        raise HTTPException(status_code=404, detail="Station not found")

    delete_response = supabase.table("stations").delete().eq("id", station_id).execute()
    if delete_response.data is None:
        raise HTTPException(status_code=500, detail="Failed to delete station")
    return {"message": "Station deleted successfully", "station_id": station_id}


@app.patch("/api/admin/complaints/{complaint_id}/status")
async def update_complaint_status(complaint_id: str, payload: ComplaintStatusUpdateRequest, request: Request):
    get_authenticated_user(request, required_user_type="admin")
    normalized_status = map_complaint_status(payload.status)
    storage_status = {
        "Pending": "searching",
        "Matched": "matched",
        "Resolved": "resolved",
    }[normalized_status]
    update_response = supabase.table("lost_items").update({"status": storage_status}).eq("id", complaint_id).execute()
    if update_response.data is None:
        raise HTTPException(status_code=500, detail="Failed to update complaint status")
    return {"message": f"Complaint status updated to {normalized_status}", "complaint_id": complaint_id, "status": normalized_status}


@app.post("/api/admin/complaints/{complaint_id}/match")
async def create_complaint_match(complaint_id: str, payload: MatchCreateRequest, request: Request):
    get_authenticated_user(request, required_user_type="admin")

    complaint_response = supabase.table("lost_items").select("*").eq("id", complaint_id).limit(1).execute()
    if not complaint_response.data:
        raise HTTPException(status_code=404, detail="Complaint not found")

    found_item_response = supabase.table("found_items").select("*").eq("id", payload.found_item_id).limit(1).execute()
    if not found_item_response.data:
        raise HTTPException(status_code=404, detail="Found item not found")

    match_data = {
        "lost_item_id": complaint_id,
        "found_item_id": payload.found_item_id,
        "match_score": payload.match_score,
        "status": payload.status.strip().lower(),
    }
    create_response = supabase.table("matches").insert(match_data).execute()
    if create_response.data is None:
        raise HTTPException(status_code=500, detail="Failed to create match")

    supabase.table("lost_items").update({"status": "matched"}).eq("id", complaint_id).execute()
    return {"message": "Complaint matched successfully", "match": create_response.data[0] if create_response.data else None}

# API Endpoints
@app.get("/api/stations", response_model=List[StationInfo])
async def get_stations():
    """Return all stations for dropdowns and frontend station lists."""
    try:
        return fetch_station_directory_from_supabase()
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to fetch /api/stations")
        raise HTTPException(status_code=500, detail="Unable to load stations right now")


@app.get("/predict-crowd", response_model=CrowdPredictionResponse)
async def predict_crowd(query: CrowdPredictionQuery = Depends(get_station_query)):
    """
    Predict crowd for a user-selected hour and the next three hours for one station.
    """
    try:
        station = fetch_station_by_name(query.station_name)
        selected_hour = parse_prediction_hour(query.hour)
        day_type = normalize_day_type(query.day_type)
        station_category = get_station_category(station)
        prediction_time = resolve_prediction_datetime(selected_hour, day_type)
        feature_rows = build_prediction_feature_rows(station, prediction_time)
        raw_predictions, prediction_engine = get_raw_crowd_predictions(feature_rows, station, day_type)

        logger.info(
            "Generating crowd prediction for station=%s, station_category=%s, selected_hour=%s, day_type=%s, engine=%s, reference=%s",
            station.name,
            station_category,
            format_selected_hour(selected_hour),
            day_type,
            prediction_engine,
            prediction_time.isoformat(),
        )
        slot_times = [feature_row["_slot_time"] for feature_row in feature_rows]
        slot_calibrations: List[Dict[str, Any]] = []
        pre_series_counts: List[int] = []

        for feature_row, predicted_value in zip(feature_rows, raw_predictions):
            slot_time = feature_row["_slot_time"]
            raw_prediction = max(int(round(float(predicted_value))), 0)
            calibration = calibrate_crowd_prediction(raw_prediction, station, slot_time)
            slot_calibrations.append(calibration)
            pre_series_counts.append(calibration["calibrated_count"])

        final_counts, series_adjustments = apply_series_calibration(
            pre_series_counts,
            slot_times,
            station,
            day_type,
        )
        if series_adjustments:
            logger.info(
                "Series calibration for %s at %s: %s",
                station.name,
                format_selected_hour(selected_hour),
                ", ".join(series_adjustments),
            )

        timeline: List[PredictionPoint] = []

        for feature_row, slot_time, calibration, final_count in zip(
            feature_rows,
            slot_times,
            slot_calibrations,
            final_counts,
        ):
            level_details = crowd_level_from_count(final_count, station, slot_time)
            crowd_level = level_details["crowd_level"]
            timeline.append(
                PredictionPoint(
                    hour=format_prediction_hour(feature_row["hour"]),
                    crowd_level=crowd_level,
                )
            )
            logger.info(
                "Forecast slot station=%s category=%s slot=%s day_type=%s raw=%s baseline=%s calibrated=%s final=%s level=%s thresholds=%s/%s calibration=%s threshold_notes=%s",
                station.name,
                station_category,
                format_selected_hour(slot_time.hour),
                day_type,
                calibration["raw_prediction"],
                calibration["baseline"],
                calibration["calibrated_count"],
                final_count,
                crowd_level,
                level_details["low_threshold"],
                level_details["high_threshold"],
                ", ".join(calibration["adjustments"]),
                ", ".join(level_details["reasons"]),
            )

        trend = crowd_trend_from_values(final_counts, slot_times, station_category, day_type)
        recommendation = build_recommendation(timeline, final_counts, trend)

        response = CrowdPredictionResponse(
            station_name=station.name,
            line=station.line,
            selected_hour=format_selected_hour(selected_hour),
            day_type=day_type.title(),
            station_category=station_category,
            is_interchange=station.is_interchange,
            is_elevated=station.is_elevated,
            selected_time_prediction=timeline[0],
            next_hours=timeline[1:],
            trend=trend,
            recommendation=recommendation,
        )

        logger.info(
            "Prediction ready for %s: selected_hour=%s, day_type=%s, station_category=%s, engine=%s, current_level=%s, hidden_count=%s, trend=%s",
            station.name,
            response.selected_hour,
            response.day_type,
            response.station_category,
            prediction_engine,
            response.selected_time_prediction.crowd_level,
            final_counts[0],
            response.trend,
        )
        return response
    except HTTPException:
        raise
    except Exception:
        logger.exception("Prediction failed for station '%s'", query.station_name)
        raise HTTPException(status_code=500, detail="Unable to generate crowd prediction right now")

@app.get("/api/nearby-places")
async def get_nearby_places(station: str = None):
    """
    Get nearby places from Supabase database.
    If station is provided, filter by station_name.
    Otherwise, return all places.
    Returns image_url exactly as stored (complete Supabase URLs).
    """
    try:
        # Use the imported supabase client from db.py
        if not supabase:
            raise HTTPException(status_code=500, detail="Database connection failed")
        
        # Query the nearby_places table
        query = supabase.table("nearby_places").select("*")
        
        if station:
            query = query.eq("station_name", station)
        
        response = query.order("rating", desc=True).execute()
        
        if response.data is None:
            return []
        
        # Return data exactly as stored - image_url is complete Supabase URL
        return response.data
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching nearby places: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching nearby places: {str(e)}")

@app.get("/api/nearby-places/{place_id}")
async def get_nearby_place_details(place_id: str):
    """
    Get detailed information about a specific nearby place from Supabase database.
    Returns image_url exactly as stored (complete Supabase URLs).
    """
    try:
        # Use the imported supabase client from db.py
        if not supabase:
            raise HTTPException(status_code=500, detail="Database connection failed")
        
        # Query the nearby_places table for specific place
        response = supabase.table("nearby_places")\
            .select("*")\
            .eq("id", place_id)\
            .execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="Place not found")
        
        # Return data exactly as stored - image_url is complete Supabase URL
        return response.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching place details: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching place details: {str(e)}")

# Health check endpoint
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    logger.info("Health check requested")
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now().isoformat(),
        model_loaded=crowd_model is not None,
        supabase_connected=supabase is not None,
    )

@app.post("/api/book-ticket", response_model=BookingResponse)
async def book_ticket(booking: BookingRequest, request: Request):
    """
    Book a ticket between two stations with fare calculation and user details
    """
    try:
        current_user = get_authenticated_user(request, required_user_type="user")
        booking_email = str(current_user.get("email") or "").strip().lower()
        if booking.user_email.strip().lower() != booking_email:
            raise HTTPException(status_code=403, detail="Bookings can only be created for the authenticated user")
        # Validation: If same station → return error
        if booking.from_station == booking.to_station:
            raise HTTPException(status_code=400, detail="From and to stations cannot be the same")
        
        # Validation: Ticket count must be greater than 0
        if booking.ticket_count <= 0:
            raise HTTPException(status_code=400, detail="Ticket count must be greater than 0")
        
        # Validation: Payment method must be valid
        valid_payment_methods = ["Debit Card", "Credit Card", "UPI", "Smart Card"]
        if booking.payment_method not in valid_payment_methods:
            raise HTTPException(status_code=400, detail="Invalid payment method")
        
        user_name = current_user.get("full_name") or booking.booking_name or "Passenger"
        
        # Fetch both stations from Supabase
        from_response = supabase.table("stations").select("*").eq("name", booking.from_station).execute()
        to_response = supabase.table("stations").select("*").eq("name", booking.to_station).execute()
        
        # Validation: If station not found → return 404
        if not from_response.data:
            raise HTTPException(status_code=404, detail=f"Station '{booking.from_station}' not found")
        if not to_response.data:
            raise HTTPException(status_code=404, detail=f"Station '{booking.to_station}' not found")
        
        from_station = from_response.data[0]
        to_station = to_response.data[0]
        
        # Calculate stations count
        if from_station["line"] == to_station["line"]:
            # Same line: stations = absolute difference of sequence
            stations = abs(from_station["sequence"] - to_station["sequence"])
        else:
            # Different line: interchange station = "Agra College"
            interchange_response = supabase.table("stations").select("*").eq("name", "Agra College").execute()
            if not interchange_response.data:
                raise HTTPException(status_code=404, detail="Interchange station 'Agra College' not found")
            
            interchange = interchange_response.data[0]
            
            # stations1 = from → interchange, stations2 = interchange → to
            stations1 = abs(from_station["sequence"] - interchange["sequence"]) if from_station["line"] == interchange["line"] else 0
            stations2 = abs(to_station["sequence"] - interchange["sequence"]) if to_station["line"] == interchange["line"] else 0
            stations = stations1 + stations2
        
        # Fare calculation per ticket
        fare_per_ticket = 10 + (stations * 5)
        
        # Peak hour logic: 8–11 AM or 5–8 PM, surcharge = 20% of baseFare
        surcharge_per_ticket = fare_per_ticket * 0.2 if is_peak_hour() else 0
        
        # Total fare calculation
        baseFare = fare_per_ticket * booking.ticket_count
        surcharge = surcharge_per_ticket * booking.ticket_count
        totalFare = int(baseFare + surcharge)  # Convert to integer for smart card
        
        # TASK 7: CONNECT SMART CARD WITH BOOKING
        if booking.payment_method == "Smart Card":
            # Fetch smart card using user_email
            card_response = supabase.table("smart_cards").select("*").eq("user_email", booking_email).execute()
            
            # IF card not found → create card automatically
            if not card_response.data:
                try:
                    # Generate 12-digit card number
                    import random
                    card_number = f"{random.randint(100000000000, 999999999999)}"
                    
                    # Create new card with 0 balance
                    card_data = {
                        "user_email": booking_email,
                        "card_number": card_number,
                        "balance": 0
                    }
                    
                    create_response = supabase.table("smart_cards").insert(card_data).execute()
                    
                    if not create_response.data:
                        raise HTTPException(status_code=500, detail="Failed to create smart card")
                    
                    current_balance = 0
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Failed to create smart card: {str(e)}")
            else:
                card = card_response.data[0]
                current_balance = card["balance"]
            
            # Check balance
            if current_balance < totalFare:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Insufficient balance. Please recharge your card. Current balance: Rs.{current_balance}, Required: Rs.{totalFare}"
                )
            
            # IF sufficient balance → deduct fare
            new_balance = current_balance - totalFare
            update_response = supabase.table("smart_cards").update({"balance": new_balance}).eq("user_email", booking_email).execute()
            
            if not update_response.data:
                raise HTTPException(status_code=500, detail="Failed to update smart card balance")
        
        # Insert booking into bookings table with updated fields
        booking_data = {
            "from_station": booking.from_station,
            "to_station": booking.to_station,
            "stations": stations,
            "fare_per_ticket": int(fare_per_ticket),
            "ticket_count": booking.ticket_count,
            "base_fare": int(baseFare),
            "surcharge": int(surcharge),
            "total_fare": totalFare,
            "payment_method": booking.payment_method,
            "user_email": booking_email,
            "user_name": booking.booking_name or user_name,  # Use booking name or fallback to user name
            "status": "active",  # Default status for new bookings
            "booking_date": "NOW()"  # Set current timestamp
        }
        
        insert_response = supabase.table("bookings").insert(booking_data).execute()
        
        if insert_response.data is None:
            raise HTTPException(status_code=500, detail="Failed to save booking")
        
        booking_id = insert_response.data[0]["id"]
        
        # Create transaction record for smart card payment
        if booking.payment_method == "Smart Card":
            # Insert into card_transactions with exact fields
            transaction_data = {
                "user_email": booking_email,
                "from_station": booking.from_station,
                "to_station": booking.to_station,
                "amount": totalFare,
                "type": "debit"
            }
            
            transaction_response = supabase.table("card_transactions").insert(transaction_data).execute()
            
            if not transaction_response.data:
                # Log error but don't fail the booking
                print(f"Warning: Failed to create transaction record for booking {booking_id}")
        
        # Return response
        message = ""
        if booking.payment_method == "Smart Card":
            message = f"Rs.{totalFare} deducted from your smart card. New balance: Rs.{new_balance}"
        
        return BookingResponse(
            from_station=booking.from_station,
            to_station=booking.to_station,
            stations=stations,
            fare_per_ticket=int(fare_per_ticket),
            ticket_count=booking.ticket_count,
            baseFare=int(baseFare),
            surcharge=int(surcharge),
            totalFare=totalFare,
            payment_method=booking.payment_method,
            user_name=user_name,
            booking_name=booking.booking_name or user_name,
            message=message
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing booking: {str(e)}")

@app.get("/api/user-bookings/{user_email}")
async def get_user_bookings(user_email: str, request: Request):
    """
    Get all bookings for a specific user and count total tickets
    """
    try:
        authorize_email_access(request, user_email)
        # Fetch all bookings for the user
        bookings_response = supabase.table("bookings").select("*").eq("user_email", user_email).execute()
        
        if bookings_response.data is None:
            raise HTTPException(status_code=500, detail="Failed to fetch bookings")
        
        bookings = bookings_response.data
        
        # Calculate total tickets booked
        total_tickets = sum(booking["ticket_count"] for booking in bookings)
        
        return {
            "bookings": bookings,
            "total_bookings": len(bookings),
            "total_tickets": total_tickets
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching user bookings: {str(e)}")

# Smart Card APIs

@app.get("/smart-card/{email}", response_model=SmartCard)
async def get_smart_card(email: str, request: Request):
    """Get smart card by user_email with auto-creation and user full name"""
    try:
        authorize_email_access(request, email)
        # Fetch smart card
        card_response = supabase.table("smart_cards").select("*").eq("user_email", email).execute()
        
        # Fetch user full name
        user_response = supabase.table("users").select("full_name").eq("email", email).execute()
        
        if not card_response.data:
            # Auto-create smart card if not found
            import random
            card_number = f"{random.randint(100000000000, 999999999999)}"
            
            card_data = {
                "user_email": email,
                "card_number": card_number,
                "balance": 0
            }
            
            create_response = supabase.table("smart_cards").insert(card_data).execute()
            
            if not create_response.data:
                raise HTTPException(status_code=500, detail="Failed to create smart card")
            
            card = create_response.data[0]
            
            # Get user name for new card
            user_full_name = "User"
            if user_response.data:
                user_full_name = user_response.data[0]["full_name"]
            
            return SmartCard(
                card_number=card["card_number"],
                balance=card["balance"],
                full_name=user_full_name
            )
        
        # Card exists, get user name
        card = card_response.data[0]
        user_full_name = "User"
        
        if user_response.data:
            user_full_name = user_response.data[0]["full_name"]
        
        return SmartCard(
            card_number=card["card_number"],
            balance=card["balance"],
            full_name=user_full_name
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching smart card: {str(e)}")

@app.post("/create-smart-card", response_model=SmartCard)
async def create_smart_card(request: Request):
    """Create smart card (auto-create if not exists) with user full name"""
    try:
        # Get email from request body
        body = await request.json()
        email = body.get("email")
        
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")

        authorize_email_access(request, email)
        
        # Check if card already exists
        existing_card = supabase.table("smart_cards").select("*").eq("user_email", email).execute()
        
        # Fetch user full name
        user_response = supabase.table("users").select("full_name").eq("email", email).execute()
        user_full_name = "User"
        if user_response.data:
            user_full_name = user_response.data[0]["full_name"]
        
        if existing_card.data:
            # Return existing card with user name
            card = existing_card.data[0]
            return SmartCard(
                card_number=card["card_number"],
                balance=card["balance"],
                full_name=user_full_name
            )
        
        # Generate 12-digit card number
        import random
        card_number = f"{random.randint(100000000000, 999999999999)}"
        
        # Create new card with 0 balance
        card_data = {
            "user_email": email,
            "card_number": card_number,
            "balance": 0
        }
        
        create_response = supabase.table("smart_cards").insert(card_data).execute()
        
        if not create_response.data:
            raise HTTPException(status_code=500, detail="Failed to create smart card")
        
        card = create_response.data[0]
        return SmartCard(
            card_number=card["card_number"],
            balance=card["balance"],
            full_name=user_full_name
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating smart card: {str(e)}")

@app.post("/recharge-card", response_model=RechargeResponse)
async def recharge_card(recharge: RechargeRequest, request: Request):
    """TASK 2: Recharge smart card with auto-creation"""
    try:
        authorize_email_access(request, recharge.email)
        # Get current card
        card_response = supabase.table("smart_cards").select("*").eq("user_email", recharge.email).execute()
        
        if not card_response.data:
            # Auto-create smart card if not found
            import random
            card_number = f"{random.randint(100000000000, 999999999999)}"
            
            card_data = {
                "user_email": recharge.email,
                "card_number": card_number,
                "balance": 0
            }
            
            create_response = supabase.table("smart_cards").insert(card_data).execute()
            
            if not create_response.data:
                raise HTTPException(status_code=500, detail="Failed to create smart card")
            
            card = create_response.data[0]
            old_balance = 0
        else:
            card = card_response.data[0]
            old_balance = card["balance"]
        
        new_balance = old_balance + recharge.amount
        
        # Update balance
        update_response = supabase.table("smart_cards").update({"balance": new_balance}).eq("user_email", recharge.email).execute()
        
        if not update_response.data:
            raise HTTPException(status_code=500, detail="Failed to update card balance")
        
        # Insert transaction record (credit)
        transaction_data = {
            "user_email": recharge.email,
            "amount": recharge.amount,
            "type": "credit",
            "from_station": None,
            "to_station": None
        }
        
        transaction_response = supabase.table("card_transactions").insert(transaction_data).execute()
        
        if not transaction_response.data:
            raise HTTPException(status_code=500, detail="Failed to create transaction record")
        
        return RechargeResponse(
            message="Recharge successful",
            new_balance=new_balance
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error recharging card: {str(e)}")

@app.get("/transactions/{email}", response_model=TransactionResponse)
async def get_transactions(email: str, request: Request, limit: int = 10):
    """TASK 8: Get last 10 transactions"""
    try:
        authorize_email_access(request, email)
        response = supabase.table("card_transactions")\
            .select("*")\
            .eq("user_email", email)\
            .order("created_at", desc=True)\
            .limit(limit)\
            .execute()
        
        if response.data is None:
            raise HTTPException(status_code=500, detail="Failed to fetch transactions")
        
        transactions = []
        for transaction in response.data:
            transactions.append(Transaction(
                id=str(transaction["id"]),
                user_email=transaction["user_email"],
                from_station=transaction.get("from_station") or "",
                to_station=transaction.get("to_station") or "",
                amount=transaction["amount"],
                type=transaction["type"],
                created_at=str(transaction["created_at"])
            ))
        
        return TransactionResponse(transactions=transactions)
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching transactions: {str(e)}")

# Ticket Cancellation APIs

@app.post("/cancel-booking/{booking_id}", response_model=CancelResponse)
async def cancel_booking(booking_id: str, request: Request):
    """Cancel a booking and process refund if payment was via Smart Card"""
    try:
        current_user = get_authenticated_user(request)
        # Get booking by ID
        booking_response = supabase.table("bookings").select("*").eq("id", booking_id).execute()
        
        if not booking_response.data:
            raise HTTPException(status_code=404, detail="Booking not found")
        
        booking = booking_response.data[0]
        if current_user["user_type"] != "admin" and str(booking.get("user_email") or "").strip().lower() != str(current_user.get("email") or "").strip().lower():
            raise HTTPException(status_code=403, detail="Access denied for this booking")
        
        # Check if already cancelled
        if booking.get("status") == "cancelled":
            return CancelResponse(message="Booking already cancelled")
        
        # Update booking status to cancelled
        update_response = supabase.table("bookings").update({"status": "cancelled"}).eq("id", booking_id).execute()
        
        if not update_response.data:
            raise HTTPException(status_code=500, detail="Failed to cancel booking")
        
        # Process refund if payment was via Smart Card
        refund_amount = 0
        new_balance = 0
        
        if booking.get("payment_method") == "Smart Card":
            # Fetch user's smart card
            card_response = supabase.table("smart_cards").select("*").eq("user_email", booking["user_email"]).execute()
            
            if not card_response.data:
                raise HTTPException(status_code=404, detail="Smart card not found for refund")
            
            card = card_response.data[0]
            current_balance = card["balance"]
            refund_amount = booking["total_fare"]
            new_balance = current_balance + refund_amount
            
            # Update smart card balance
            balance_update = supabase.table("smart_cards").update({"balance": new_balance}).eq("user_email", booking["user_email"]).execute()
            
            if not balance_update.data:
                raise HTTPException(status_code=500, detail="Failed to process refund")
            
            # Insert refund transaction
            transaction_data = {
                "user_email": booking["user_email"],
                "from_station": booking["from_station"],
                "to_station": booking["to_station"],
                "amount": refund_amount,
                "type": "credit"
            }
            
            transaction_response = supabase.table("card_transactions").insert(transaction_data).execute()
            
            if not transaction_response.data:
                raise HTTPException(status_code=500, detail="Failed to record refund transaction")
        
        return CancelResponse(
            message="Booking cancelled successfully" + (f". Refund of Rs.{refund_amount} processed to your Smart Card." if refund_amount > 0 else ""),
            refund_amount=refund_amount,
            new_balance=new_balance
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cancelling booking: {str(e)}")

@app.get("/user-bookings/{email}", response_model=List[BookingDetails])
async def get_user_bookings(email: str, request: Request):
    """Get all bookings for a user with details"""
    try:
        authorize_email_access(request, email)
        response = supabase.table("bookings")\
            .select("*")\
            .eq("user_email", email)\
            .order("booking_date", desc=True)\
            .execute()
        
        if response.data is None:
            raise HTTPException(status_code=500, detail="Failed to fetch bookings")
        
        bookings = []
        for booking in response.data:
            bookings.append(BookingDetails(
                booking_id=str(booking["id"]),
                user_email=booking["user_email"],
                from_station=booking["from_station"],
                to_station=booking["to_station"],
                total_fare=booking["total_fare"],
                ticket_count=booking["ticket_count"],
                status=booking.get("status", "active"),
                payment_method=booking["payment_method"],
                booking_date=str(booking.get("booking_date", booking.get("created_at")))
            ))
        
        return bookings
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching user bookings: {str(e)}")

# Authentication APIs

@app.post("/signup")
async def signup(user: SignupRequest):
    """User signup API with auto smart card creation"""
    try:
        normalized_user_type = normalize_user_type(user.user_type)
        if normalized_user_type not in {"user", "admin"}:
            raise HTTPException(status_code=400, detail="user_type must be either 'user' or 'admin'")

        # Check if email already exists
        existing_user = supabase.table("users").select("*").eq("email", user.email).execute()
        
        if existing_user.data:
            raise HTTPException(status_code=400, detail="User already exists")
        
        # Hash the password
        hashed_password = hash_password(user.password)
        
        # Insert user into Supabase
        user_data = {
            "full_name": user.full_name,
            "email": user.email,
            "password": hashed_password,
            "user_type": user_type_for_storage(normalized_user_type)
        }
        
        try:
            response = supabase.table("users").insert(user_data).execute()
        except Exception as exc:
            logger.exception("Supabase user insert failed for %s", user.email)
            raise HTTPException(status_code=400, detail=f"Unable to create user record: {str(exc)}") from exc
        
        if response.data is None:
            raise HTTPException(status_code=500, detail="Failed to create user")
        
        # TASK 3: AUTO CREATE SMART CARD
        try:
            # Generate 12-digit card number
            import random
            card_number = f"{random.randint(100000000000, 999999999999)}"
            
            # Create smart card with 0 balance
            card_data = {
                "user_email": user.email,
                "card_number": card_number,
                "balance": 0
            }
            
            card_response = supabase.table("smart_cards").insert(card_data).execute()
            
            if card_response.data is None:
                print(f"Warning: Failed to create smart card for user {user.email}")
            else:
                print(f"Smart card created for user {user.email}: {card_number}")
        except Exception as e:
            print(f"Warning: Smart card creation failed for user {user.email}: {str(e)}")
        
        return {"message": "Signup successful"}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during signup: {str(e)}")

@app.post("/login")
async def login(credentials: LoginRequest):
    """User login API"""
    try:
        # Check if email exists
        existing_user = supabase.table("users").select("*").eq("email", credentials.email).execute()
        
        if not existing_user.data:
            raise HTTPException(status_code=404, detail="Please signup first")
        
        user = existing_user.data[0]

        if resolve_user_account_status(user) != "active":
            raise HTTPException(status_code=403, detail="Account is blocked. Please contact admin support.")
        
        # Check password
        if not verify_password(credentials.password, user["password"]):
            raise HTTPException(status_code=401, detail="Wrong password")

        login_timestamp = datetime.now(timezone.utc).isoformat()
        try:
            supabase.table("users").update({"last_login_at": login_timestamp}).eq("id", user["id"]).execute()
            user["last_login_at"] = login_timestamp
        except Exception:
            logger.warning("Could not persist last_login_at for user %s", user.get("email"))
        
        session_token = create_session_token(user)

        response = JSONResponse(
            content={
            "message": "Login successful",
            "session_token": session_token,
            "user": {
                "id": user["id"],
                "full_name": user["full_name"],
                "email": user["email"],
                "user_type": normalize_user_type(user["user_type"]),
                "last_login_at": user.get("last_login_at"),
                "account_status": resolve_user_account_status(user),
            }
        })
        set_session_cookie(response, session_token)
        return response
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during login: {str(e)}")


@app.post("/logout")
async def logout():
    response = JSONResponse(content={"message": "Logout successful"})
    clear_session_cookie(response)
    return response


@app.get("/api/session")
async def get_session(request: Request):
    current_user = get_authenticated_user(request)
    return {
        "user": {
            "id": current_user["id"],
            "full_name": current_user["full_name"],
            "email": current_user["email"],
            "user_type": current_user["user_type"],
            "last_login_at": current_user.get("last_login_at"),
            "account_status": current_user.get("account_status", "active"),
        }
    }


@app.post("/api/session/restore")
async def restore_session(request: Request):
    current_user = get_authenticated_user(request)
    session_token = extract_session_token(request)
    response = JSONResponse(
        content={
            "message": "Session restored",
            "user": {
                "id": current_user["id"],
                "full_name": current_user["full_name"],
                "email": current_user["email"],
                "user_type": current_user["user_type"],
                "last_login_at": current_user.get("last_login_at"),
                "account_status": current_user.get("account_status", "active"),
            },
        }
    )
    set_session_cookie(response, session_token)
    return response

@app.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    """Forgot password API"""
    try:
        # Check if email exists
        existing_user = supabase.table("users").select("*").eq("email", request.email).execute()
        
        if not existing_user.data:
            raise HTTPException(status_code=404, detail="Signup first")
        
        return {"message": "Email exists. You can reset your password."}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error in forgot password: {str(e)}")

@app.post("/reset-password")
async def reset_password(request: ResetPasswordRequest):
    """Reset password API"""
    try:
        # Check if email exists
        existing_user = supabase.table("users").select("*").eq("email", request.email).execute()
        
        if not existing_user.data:
            raise HTTPException(status_code=404, detail="Signup first")
        
        # Check if passwords match
        if request.new_password != request.confirm_password:
            raise HTTPException(status_code=400, detail="Passwords do not match")
        
        # Hash the new password
        hashed_password = hash_password(request.new_password)
        
        # Update password in users table
        response = supabase.table("users").update({"password": hashed_password}).eq("email", request.email).execute()
        
        if response.data is None:
            raise HTTPException(status_code=500, detail="Failed to update password")
        
        return {"message": "Password updated successfully"}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error in reset password: {str(e)}")

# Lost & Found System APIs

def calculate_match_score(lost_item, found_item):
    """Calculate match score between lost and found items"""
    score = 0
    
    # Item name similarity (50 points)
    if lost_item['item_name'].lower() == found_item['item_name'].lower():
        score += 50
    elif lost_item['item_name'].lower() in found_item['item_name'].lower() or found_item['item_name'].lower() in lost_item['item_name'].lower():
        score += 30
    
    # Station similarity (30 points)
    if lost_item['station'].lower() == found_item['station'].lower():
        score += 30
    
    # Description similarity (20 points)
    if lost_item['description'] and found_item['description']:
        lost_desc_words = set(lost_item['description'].lower().split())
        found_desc_words = set(found_item['description'].lower().split())
        common_words = lost_desc_words.intersection(found_desc_words)
        if common_words:
            score += min(20, len(common_words) * 5)
    
    return score

async def run_matching_for_lost_item(lost_item_id):
    """Run matching algorithm for a lost item"""
    try:
        # Get the lost item
        lost_response = supabase.table("lost_items").select("*").eq("id", lost_item_id).execute()
        if not lost_response.data:
            return
        
        lost_item = lost_response.data[0]
        
        # Get all found items
        found_response = supabase.table("found_items").select("*").execute()
        if not found_response.data:
            return
        
        found_items = found_response.data
        
        # Calculate match scores
        matches = []
        for found_item in found_items:
            score = calculate_match_score(lost_item, found_item)
            
            # Create match if score >= 60
            if score >= 60:
                match_data = {
                    "lost_item_id": lost_item_id,
                    "found_item_id": found_item["id"],
                    "match_score": score,
                    "status": "pending"
                }
                
                # Insert match
                match_response = supabase.table("matches").insert(match_data).execute()
                if match_response.data:
                    match_id = match_response.data[0]["id"]
                    
                    # Get full match data
                    match_response_full = supabase.table("matches").select("*").eq("id", match_id).execute()
                    if match_response_full.data:
                        match = match_response_full.data[0]
                        matches.append(MatchResponse(
                            id=str(match["id"]),
                            lost_item=LostItemResponse(
                                id=str(lost_item["id"]),
                                user_email=lost_item["user_email"],
                                item_name=lost_item["item_name"],
                                station=lost_item["station"],
                                description=lost_item["description"],
                                status=lost_item["status"],
                                created_at=str(lost_item["created_at"])
                            ),
                            found_item=FoundItemResponse(
                                id=str(found_item["id"]),
                                item_name=found_item["item_name"],
                                station=found_item["station"],
                                description=found_item["description"],
                                reported_by=found_item["reported_by"],
                                contact_info=found_item.get("contact_info", ""),
                                created_at=str(found_item["created_at"])
                            ),
                            match_score=score,
                            status=match["status"],
                            created_at=str(match["created_at"])
                        ))
        
        # Update lost item status if matches found
        if matches:
            supabase.table("lost_items").update({"status": "matched"}).eq("id", lost_item_id).execute()
        
        return matches
        
    except Exception as e:
        print(f"Error in matching: {str(e)}")
        return []

async def run_matching_for_found_item(found_item_id):
    """Run matching algorithm for a found item"""
    try:
        # Get the found item
        found_response = supabase.table("found_items").select("*").eq("id", found_item_id).execute()
        if not found_response.data:
            return
        
        found_item = found_response.data[0]
        
        # Get all lost items
        lost_response = supabase.table("lost_items").select("*").execute()
        if not lost_response.data:
            return
        
        lost_items = lost_response.data
        
        # Calculate match scores
        matches = []
        for lost_item in lost_items:
            score = calculate_match_score(lost_item, found_item)
            
            # Create match if score >= 60
            if score >= 60:
                match_data = {
                    "lost_item_id": lost_item["id"],
                    "found_item_id": found_item_id,
                    "match_score": score,
                    "status": "pending"
                }
                
                # Insert match
                match_response = supabase.table("matches").insert(match_data).execute()
                if match_response.data:
                    match_id = match_response.data[0]["id"]
                    
                    # Get full match data
                    match_response_full = supabase.table("matches").select("*").eq("id", match_id).execute()
                    if match_response_full.data:
                        match = match_response_full.data[0]
                        matches.append(MatchResponse(
                            id=str(match["id"]),
                            lost_item=LostItemResponse(
                                id=str(lost_item["id"]),
                                user_email=lost_item["user_email"],
                                item_name=lost_item["item_name"],
                                station=lost_item["station"],
                                description=lost_item["description"],
                                status=lost_item["status"],
                                created_at=str(lost_item["created_at"])
                            ),
                            found_item=FoundItemResponse(
                                id=str(found_item["id"]),
                                item_name=found_item["item_name"],
                                station=found_item["station"],
                                description=found_item["description"],
                                reported_by=found_item["reported_by"],
                                contact_info=found_item.get("contact_info", ""),
                                created_at=str(found_item["created_at"])
                            ),
                            match_score=score,
                            status=match["status"],
                            created_at=str(match["created_at"])
                        ))
        
        # Update all matched lost items status
        for match in matches:
            supabase.table("lost_items").update({"status": "matched"}).eq("id", match.lost_item.id).execute()
        
        return matches
        
    except Exception as e:
        print(f"Error in matching: {str(e)}")
        return []

@app.post("/report-lost", response_model=ReportResponse)
async def report_lost_item(payload: LostItemRequest, request: Request):
    """Report a lost item"""
    try:
        current_user = get_authenticated_user(request, required_user_type="user")
        # Validation
        if not payload.email or not payload.item_name or not payload.station:
            raise HTTPException(status_code=400, detail="Email, item name, and station are required")
        if payload.email.strip().lower() != str(current_user.get("email") or "").strip().lower():
            raise HTTPException(status_code=403, detail="Lost item reports can only be created for the authenticated user")
        
        # Insert lost item
        lost_item_data = {
            "user_email": payload.email.strip().lower(),
            "item_name": payload.item_name,
            "station": payload.station,
            "description": payload.description,
            "full_name": payload.full_name,
            "contact_number": payload.contact_number,
            "status": "searching"
        }
        
        response = supabase.table("lost_items").insert(lost_item_data).execute()
        
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to report lost item")
        
        lost_item = response.data[0]
        
        # Run matching automatically
        await run_matching_for_lost_item(lost_item["id"])
        
        return ReportResponse(
            success=True,
            message="Lost item reported successfully. We'll notify you if we find a match.",
            data={
                "item_id": str(lost_item["id"]),
                "status": "searching"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reporting lost item: {str(e)}")

@app.post("/report-found", response_model=ReportResponse)
async def report_found_item(payload: FoundItemRequest, request: Request):
    """Report a found item"""
    try:
        get_authenticated_user(request, required_user_type="user")
        # Validation
        if not payload.item_name or not payload.station or not payload.reported_by:
            raise HTTPException(status_code=400, detail="Item name, station, and reporter name are required")
        
        # Insert found item
        found_item_data = {
            "item_name": payload.item_name,
            "station": payload.station,
            "description": payload.description,
            "reported_by": payload.reported_by,
            "contact_info": payload.contact_info
        }
        
        response = supabase.table("found_items").insert(found_item_data).execute()
        
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to report found item")
        
        found_item = response.data[0]
        
        # Run matching automatically
        await run_matching_for_found_item(found_item["id"])
        
        return ReportResponse(
            success=True,
            message="Found item reported successfully. We'll try to match it with lost items.",
            data={
                "item_id": str(found_item["id"]),
                "status": "searching_for_matches"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reporting found item: {str(e)}")

@app.get("/my-reports/{email}", response_model=List[LostItemResponse])
async def get_user_reports(email: str, request: Request):
    """Get all lost items reported by a user"""
    try:
        authorize_email_access(request, email)
        response = supabase.table("lost_items")\
            .select("*")\
            .eq("user_email", email)\
            .order("created_at", desc=True)\
            .execute()
        
        if response.data is None:
            raise HTTPException(status_code=500, detail="Failed to fetch user reports")
        
        reports = []
        for item in response.data:
            reports.append(LostItemResponse(
                id=str(item["id"]),
                user_email=item["user_email"],
                item_name=item["item_name"],
                station=item["station"],
                description=item["description"],
                status=item["status"],
                created_at=str(item["created_at"])
            ))
        
        return reports
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching user reports: {str(e)}")

@app.get("/matches/{email}", response_model=List[MatchResponse])
async def get_user_matches(email: str, request: Request):
    """Get all matches for a user's lost items"""
    try:
        authorize_email_access(request, email)
        # Get user's lost items
        lost_response = supabase.table("lost_items")\
            .select("*")\
            .eq("user_email", email)\
            .execute()
        
        if not lost_response.data:
            return []
        
        lost_items = lost_response.data
        lost_item_ids = [item["id"] for item in lost_items]
        
        # Get matches for user's lost items
        matches_response = supabase.table("matches")\
            .select("*")\
            .in_("lost_item_id", lost_item_ids)\
            .order("created_at", desc=True)\
            .execute()
        
        if matches_response.data is None:
            return []
        
        matches = []
        for match in matches_response.data:
            # Get lost item details
            lost_item = next((item for item in lost_items if item["id"] == match["lost_item_id"]), None)
            # Get found item details
            found_response = supabase.table("found_items").select("*").eq("id", match["found_item_id"]).execute()
            found_item = found_response.data[0] if found_response.data else None
            
            if lost_item and found_item:
                matches.append(MatchResponse(
                    id=str(match["id"]),
                    lost_item=LostItemResponse(
                        id=str(lost_item["id"]),
                        user_email=lost_item["user_email"],
                        item_name=lost_item["item_name"],
                        station=lost_item["station"],
                        description=lost_item["description"],
                        status=lost_item["status"],
                        created_at=str(lost_item["created_at"])
                    ),
                    found_item=FoundItemResponse(
                        id=str(found_item["id"]),
                        item_name=found_item["item_name"],
                        station=found_item["station"],
                        description=found_item["description"],
                        reported_by=found_item["reported_by"],
                        contact_info=found_item.get("contact_info", ""),
                        created_at=str(found_item["created_at"])
                    ),
                    match_score=match["match_score"],
                    status=match["status"],
                    created_at=str(match["created_at"])
                ))
        
        return matches
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching matches: {str(e)}")

@app.post("/accept-match/{match_id}", response_model=ReportResponse)
async def accept_match(match_id: str, request: Request):
    """Accept a match between lost and found item"""
    try:
        current_user = get_authenticated_user(request)
        # Get match details
        match_response = supabase.table("matches").select("*").eq("id", match_id).execute()
        
        if not match_response.data:
            raise HTTPException(status_code=404, detail="Match not found")
        
        match = match_response.data[0]
        lost_item_response = supabase.table("lost_items").select("*").eq("id", match["lost_item_id"]).limit(1).execute()
        if not lost_item_response.data:
            raise HTTPException(status_code=404, detail="Related complaint not found")
        lost_item = lost_item_response.data[0]
        if current_user["user_type"] != "admin" and str(lost_item.get("user_email") or "").strip().lower() != str(current_user.get("email") or "").strip().lower():
            raise HTTPException(status_code=403, detail="Access denied for this match")
        
        # Update match status
        update_response = supabase.table("matches").update({"status": "accepted"}).eq("id", match_id).execute()
        
        if not update_response.data:
            raise HTTPException(status_code=500, detail="Failed to accept match")

        supabase.table("lost_items").update({"status": "resolved"}).eq("id", match["lost_item_id"]).execute()
        
        return ReportResponse(
            success=True,
            message="Match accepted successfully. Contact information has been shared.",
            data={
                "match_id": match_id,
                "status": "accepted"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error accepting match: {str(e)}")

@app.post("/reject-match/{match_id}", response_model=ReportResponse)
async def reject_match(match_id: str, request: Request):
    """Reject a match between lost and found item"""
    try:
        current_user = get_authenticated_user(request)
        # Get match details
        match_response = supabase.table("matches").select("*").eq("id", match_id).execute()
        
        if not match_response.data:
            raise HTTPException(status_code=404, detail="Match not found")
        
        match = match_response.data[0]
        lost_item_response = supabase.table("lost_items").select("*").eq("id", match["lost_item_id"]).limit(1).execute()
        if not lost_item_response.data:
            raise HTTPException(status_code=404, detail="Related complaint not found")
        lost_item = lost_item_response.data[0]
        if current_user["user_type"] != "admin" and str(lost_item.get("user_email") or "").strip().lower() != str(current_user.get("email") or "").strip().lower():
            raise HTTPException(status_code=403, detail="Access denied for this match")
        
        # Update match status
        update_response = supabase.table("matches").update({"status": "rejected"}).eq("id", match_id).execute()
        
        if not update_response.data:
            raise HTTPException(status_code=500, detail="Failed to reject match")
        
        return ReportResponse(
            success=True,
            message="Match rejected successfully.",
            data={
                "match_id": match_id,
                "status": "rejected"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error rejecting match: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
