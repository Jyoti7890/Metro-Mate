import os
import time
from pathlib import Path
import joblib
import pandas as pd
from httpx import RemoteProtocolError
from postgrest.types import CountMethod
from supabase import create_client, Client
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

try:
    from backend.settings import get_env_value, load_project_env, missing_supabase_message
except ImportError:
    from settings import get_env_value, load_project_env, missing_supabase_message

# --------------------------------------------------
# Load .env from metro/.env
# --------------------------------------------------
CURRENT_FILE = Path(__file__).resolve()
BACKEND_DIR = CURRENT_FILE.parent
PROJECT_ROOT = BACKEND_DIR.parent
ENV_PATH = PROJECT_ROOT / ".env"

file_values = load_project_env()

SUPABASE_URL = get_env_value("SUPABASE_URL", file_values, allow_placeholder=False)
SUPABASE_KEY = get_env_value(
    "SUPABASE_SERVICE_ROLE_KEY",
    file_values,
    allow_placeholder=False,
) or get_env_value(
    "SUPABASE_KEY",
    file_values,
    allow_placeholder=False,
)

print("\n--- ENV CHECK ---")
print("Looking for .env at:", ENV_PATH)
print(".env exists:", ENV_PATH.exists())
print("SUPABASE_URL loaded:", bool(SUPABASE_URL))
print("SUPABASE_KEY loaded:", bool(SUPABASE_KEY))
print("-----------------\n")

missing_values: list[str] = []
if not SUPABASE_URL:
    missing_values.append("SUPABASE_URL")
if not SUPABASE_KEY:
    missing_values.append("SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY)")
if missing_values:
    raise ValueError(missing_supabase_message(missing_values))

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def fetch_supabase_table_in_batches(
    table_name: str,
    batch_size: int = 1000,
    order_column: str = "id",
    max_retries: int = 3,
) -> pd.DataFrame:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than 0")

    if max_retries <= 0:
        raise ValueError("max_retries must be greater than 0")

    print(f"Fetching '{table_name}' from Supabase in batches of {batch_size} rows...")

    all_records = []
    total_rows = None
    total_fetched = 0
    start = 0
    batch_number = 1

    while True:
        end = start + batch_size - 1
        response = None

        for attempt in range(1, max_retries + 1):
            try:
                count_method = CountMethod.exact if batch_number == 1 else None
                query = (
                    supabase.table(table_name)
                    .select("*", count=count_method)
                    .order(order_column)
                    .range(start, end)
                )
                response = query.execute()
                break
            except RemoteProtocolError as exc:
                print(
                    f"Batch {batch_number} failed with server disconnect "
                    f"(attempt {attempt}/{max_retries})."
                )
                if attempt == max_retries:
                    raise RuntimeError(
                        f"Failed to fetch '{table_name}' batch {batch_number} "
                        f"after {max_retries} attempts."
                    ) from exc
                time.sleep(min(2 ** (attempt - 1), 5))

        records = response.data or []

        if total_rows is None:
            total_rows = response.count
            if total_rows is not None:
                print(f"Supabase reports {total_rows} total rows.")

        if not records:
            print("No rows returned for this batch. Fetch complete.")
            break

        batch_count = len(records)
        all_records.extend(records)
        total_fetched += batch_count

        if total_rows is not None:
            print(
                f"Fetched batch {batch_number}: {batch_count} rows "
                f"({total_fetched}/{total_rows} total)."
            )
        else:
            print(
                f"Fetched batch {batch_number}: {batch_count} rows "
                f"({total_fetched} total so far)."
            )

        if batch_count < batch_size:
            print("Last partial batch received. Fetch complete.")
            break

        if total_rows is not None and total_fetched >= total_rows:
            print("All expected rows fetched. Fetch complete.")
            break

        start += batch_size
        batch_number += 1

    if not all_records:
        return pd.DataFrame()

    df = pd.DataFrame.from_records(all_records)
    print(f"Finished fetching '{table_name}'. Final row count: {len(df)}")
    return df


def fetch_crowd_history(batch_size: int = 1000) -> pd.DataFrame:
    return fetch_supabase_table_in_batches(
        table_name="crowd_history",
        batch_size=batch_size,
        order_column="id",
    )


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    required_cols = [
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
        "crowd_count",
    ]

    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing columns in crowd_history table: {missing_cols}")

    df = df[required_cols].copy()

    # Fill missing values safely
    df["line"] = df["line"].fillna("Unknown")
    df["day_name"] = df["day_name"].fillna("Unknown")
    df["weather"] = df["weather"].fillna("Clear")
    df["station_type"] = df["station_type"].fillna("residential")

    df["sequence"] = df["sequence"].fillna(0).astype(int)
    df["hour"] = df["hour"].fillna(0).astype(int)
    df["is_weekend"] = df["is_weekend"].fillna(False).astype(bool)
    df["is_holiday"] = df["is_holiday"].fillna(False).astype(bool)
    df["is_interchange"] = df["is_interchange"].fillna(False).astype(bool)
    df["is_elevated"] = df["is_elevated"].fillna(False).astype(bool)
    df["nearby_event"] = df["nearby_event"].fillna(False).astype(bool)
    df["crowd_count"] = df["crowd_count"].fillna(0).astype(int)

    # Remove invalid rows
    df = df[df["crowd_count"] >= 0]
    df = df[df["hour"].between(0, 23)]

    print(f"Rows after cleaning: {len(df)}")
    return df


def train_model():
    df = fetch_crowd_history()

    if df.empty:
        raise ValueError("crowd_history table is empty. First run data_generator.py")

    df = clean_data(df)

    feature_cols = [
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
    target_col = "crowd_count"

    X = df[feature_cols]
    y = df[target_col]

    categorical_cols = [
        "station_name",
        "line",
        "day_name",
        "weather",
        "station_type"
    ]

    numeric_cols = [
        "sequence",
        "hour",
        "is_weekend",
        "is_holiday",
        "is_interchange",
        "is_elevated",
        "nearby_event"
    ]

    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), categorical_cols),
            ("num", "passthrough", numeric_cols),
        ]
    )

    # Random Forest works well for structured synthetic data
    model = RandomForestRegressor(
        n_estimators=300,
        random_state=42,
        max_depth=18,
        min_samples_split=3,
        min_samples_leaf=1,
        n_jobs=-1
    )

    pipeline = Pipeline(steps=[
        ("preprocessor", preprocessor),
        ("model", model)
    ])

    print("Splitting data into train and test...")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42
    )

    print(f"Training rows: {len(X_train)}")
    print(f"Testing rows: {len(X_test)}")

    print("\nTraining model...")
    pipeline.fit(X_train, y_train)

    print("Generating predictions...")
    preds = pipeline.predict(X_test)

    mae = mean_absolute_error(y_test, preds)
    r2 = r2_score(y_test, preds)

    print("\n--- MODEL RESULTS ---")
    print(f"Mean Absolute Error (MAE): {mae:.2f}")
    print(f"R2 Score: {r2:.4f}")
    print("---------------------\n")

    model_path = BACKEND_DIR / "crowd_model.pkl"
    joblib.dump(pipeline, model_path)

    print(f"Model saved successfully at: {model_path}")

    # Optional sample predictions in terminal
    sample_output = pd.DataFrame({
        "Actual": y_test.values[:10],
        "Predicted": preds[:10].round(2)
    })
    print("\nSample Predictions:")
    print(sample_output.to_string(index=False))

    if r2 >= 0.90:
        print("\nExcellent model performance.")
    elif r2 >= 0.80:
        print("\nGood model performance.")
    elif r2 >= 0.70:
        print("\nDecent performance, but data generation can be improved.")
    else:
        print("\nLow performance. Improve synthetic data logic for more realistic patterns.")


if __name__ == "__main__":
    train_model()
