import os
import sys
import json
import zipfile
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime, date, timezone
from pathlib import Path

# Add project root to sys.path
project_root = "/Users/amitgrupper/Desktop/Klaus"
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(project_root, ".env"), override=True)

# Set logging
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("garmin_ingester")

# DDL Schema Definitions
SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS daily_biometrics (
    date DATE PRIMARY KEY,
    resting_hr INTEGER,
    hrv_baseline INTEGER,
    hrv_overnight INTEGER,
    sleep_score INTEGER CHECK (sleep_score BETWEEN 0 AND 100),
    sleep_duration NUMERIC(4,2),
    body_battery_max INTEGER CHECK (body_battery_max BETWEEN 0 AND 100),
    training_readiness INTEGER CHECK (training_readiness BETWEEN 0 AND 100)
);

CREATE TABLE IF NOT EXISTS activities (
    activity_id BIGINT PRIMARY KEY,
    date TIMESTAMP WITH TIME ZONE NOT NULL,
    type VARCHAR(50) NOT NULL,
    duration_sec INTEGER NOT NULL,
    distance_m NUMERIC(8,2),
    avg_hr INTEGER,
    max_hr INTEGER,
    avg_pace NUMERIC(5,2),
    training_effect NUMERIC(3,1) CHECK (training_effect BETWEEN 0.0 AND 5.0)
);

CREATE TABLE IF NOT EXISTS laps_telemetry (
    lap_id BIGINT PRIMARY KEY,
    activity_id BIGINT REFERENCES activities(activity_id) ON DELETE CASCADE,
    lap_index INTEGER NOT NULL,
    duration_sec INTEGER NOT NULL,
    avg_hr INTEGER NOT NULL,
    speed_mps NUMERIC(5,2) NOT NULL
);

-- PHASE 19 — additive, idempotent (SCHEMA-01, SCHEMA-02, SCHEMA-03)
ALTER TABLE activities ADD COLUMN IF NOT EXISTS training_load REAL;
ALTER TABLE activities ADD COLUMN IF NOT EXISTS perceived_exertion SMALLINT;
ALTER TABLE activities ADD COLUMN IF NOT EXISTS feel SMALLINT;
ALTER TABLE daily_biometrics ADD COLUMN IF NOT EXISTS vo2_max REAL;
ALTER TABLE daily_biometrics ADD COLUMN IF NOT EXISTS training_load_acute REAL;
ALTER TABLE daily_biometrics ADD COLUMN IF NOT EXISTS training_load_chronic REAL;
ALTER TABLE daily_biometrics ADD COLUMN IF NOT EXISTS acwr REAL;
"""

def get_db_connection():
    conn_str = os.environ.get("PG_CONNECTION_STRING") or os.environ.get("DATABASE_URL")
    if conn_str:
        logger.info("Connecting to Postgres database using PG_CONNECTION_STRING...")
        return psycopg2.connect(conn_str)
        
    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    user = os.environ.get("PGUSER", "postgres")
    password = os.environ.get("PGPASSWORD", "")
    database = os.environ.get("PGDATABASE", "klaus-postgres")
    
    logger.info(f"Connecting to Postgres database '{database}' on {host}:{port}...")
    return psycopg2.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database
    )

def setup_schema(conn):
    with conn.cursor() as cur:
        logger.info("Initializing relational database schema if not present...")
        cur.execute(SCHEMA_DDL)
    conn.commit()
    logger.info("Schema setup successfully complete.")

def parse_and_ingest_wellness(conn, extract_dir):
    wellness_dir = Path(extract_dir) / "DI_CONNECT" / "DI-Connect-Wellness"
    if not wellness_dir.exists():
        logger.warning(f"Wellness directory not found at: {wellness_dir}. Skipping wellness ingestion.")
        return

    # Track parsed biometrics: date_str -> biometric dict
    biometrics = {}

    # 1. Parse Sleep Data files
    sleep_files = list(wellness_dir.glob("*sleepData.json"))
    logger.info(f"Found {len(sleep_files)} sleep data files.")
    for file_path in sleep_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # sleepData is usually a list of daily sleep summaries
                for entry in data:
                    # Garmin sleep dates are usually anchored to calendar date of waking up
                    sleep_time = entry.get("sleepStartTimestampGMT")
                    if not sleep_time:
                        continue
                    # Convert to YYYY-MM-DD waking date
                    # Usually sleepEndTimestampGMT is better for waking date
                    end_time = entry.get("sleepEndTimestampGMT") or sleep_time
                    wake_dt = datetime.fromtimestamp(end_time / 1000)
                    date_str = wake_dt.date().isoformat()
                    
                    if date_str not in biometrics:
                        biometrics[date_str] = {}
                        
                    # Extract Sleep Duration
                    sleep_secs = entry.get("sleepTimeSeconds") or 0
                    if sleep_secs:
                        biometrics[date_str]["sleep_duration"] = round(sleep_secs / 3600, 2)
                        
                    # Extract Sleep Score
                    score_obj = entry.get("sleepScores") or {}
                    overall = score_obj.get("overall") or {}
                    sleep_score = overall.get("value")
                    if sleep_score is not None:
                        biometrics[date_str]["sleep_score"] = sleep_score
                        
                    # Extract Overnight HRV
                    hrv_val = entry.get("overnightHrv") or entry.get("avgOvernightHrv")
                    if hrv_val is not None:
                        biometrics[date_str]["hrv_overnight"] = hrv_val
        except Exception as e:
            logger.error(f"Error parsing sleep file {file_path.name}: {e}")

    # 2. Parse UDS / User daily summary files for resting heart rate & body battery
    uds_dir = Path(extract_dir) / "DI_CONNECT" / "DI-Connect-User"
    uds_files = list(uds_dir.glob("*UDSFile.json")) if uds_dir.exists() else []
    logger.info(f"Found {len(uds_files)} UDS files.")
    for file_path in uds_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for entry in data:
                    date_str = entry.get("calendarDate")
                    if not date_str:
                        continue
                    if date_str not in biometrics:
                        biometrics[date_str] = {}
                        
                    # Extract Resting Heart Rate
                    rhr = entry.get("restingHeartRate")
                    if rhr:
                        biometrics[date_str]["resting_hr"] = rhr
                        
                    # Extract Body Battery Max
                    bb_max = entry.get("bodyBatteryMax")
                    if bb_max:
                        biometrics[date_str]["body_battery_max"] = bb_max
                        
                    # Extract Training Readiness
                    readiness = entry.get("trainingReadiness")
                    if readiness:
                        biometrics[date_str]["training_readiness"] = readiness

                    # PHASE 19: Extract VO2 Max (key verified by Wave-0 probe
                    # + RESEARCH §Deep Research §1)
                    vo2 = entry.get("vO2MaxValue")
                    if vo2 is not None:
                        biometrics[date_str]["vo2_max"] = vo2
        except Exception as e:
            logger.error(f"Error parsing UDS file {file_path.name}: {e}")

    # Bulk insert daily biometrics
    if biometrics:
        logger.info(f"Ingesting {len(biometrics)} daily biometric records...")
        with conn.cursor() as cur:
            insert_query = """
            INSERT INTO daily_biometrics (
                date, resting_hr, hrv_baseline, hrv_overnight,
                sleep_score, sleep_duration, body_battery_max, training_readiness,
                vo2_max
            ) VALUES %s
            ON CONFLICT (date) DO UPDATE SET
                resting_hr = EXCLUDED.resting_hr,
                hrv_overnight = EXCLUDED.hrv_overnight,
                sleep_score = EXCLUDED.sleep_score,
                sleep_duration = EXCLUDED.sleep_duration,
                body_battery_max = EXCLUDED.body_battery_max,
                training_readiness = EXCLUDED.training_readiness,
                vo2_max = EXCLUDED.vo2_max;
            """
            values = [
                (
                    d,
                    b.get("resting_hr"),
                    b.get("hrv_baseline"),
                    b.get("hrv_overnight"),
                    b.get("sleep_score"),
                    b.get("sleep_duration"),
                    b.get("body_battery_max"),
                    b.get("training_readiness"),
                    b.get("vo2_max"),
                )
                for d, b in biometrics.items()
            ]
            execute_values(cur, insert_query, values)
        conn.commit()
        logger.info("Daily biometrics successfully ingested.")

def parse_and_ingest_activities(conn, extract_dir):
    fitness_dir = Path(extract_dir) / "DI_CONNECT" / "DI-Connect-Fitness"
    if not fitness_dir.exists():
        logger.warning(f"Fitness directory not found at: {fitness_dir}. Skipping activities ingestion.")
        return

    # Activity summaries are usually saved as JSON files in fitness_dir
    activity_files = list(fitness_dir.glob("*summaries.json"))
    logger.info(f"Found {len(activity_files)} activity summaries files.")
    
    activities = []
    for file_path in activity_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for entry in data:
                    activity_id = entry.get("activityId")
                    if not activity_id:
                        continue
                        
                    # Extract timestamp
                    start_time = entry.get("startTimeGMT")
                    if not start_time:
                        continue
                    dt = datetime.fromtimestamp(start_time / 1000, tz=timezone.utc)

                    # Convert Pace and Speed
                    duration = entry.get("duration") or entry.get("activeDuration") or 0
                    distance = entry.get("distance") or 0

                    # activityType may be a dict {"typeKey": "running"} OR a bare string
                    activity_type_raw = entry.get("activityType", "unknown")
                    if isinstance(activity_type_raw, dict):
                        activity_type = activity_type_raw.get("typeKey", "unknown")
                    else:
                        activity_type = activity_type_raw

                    activities.append((
                        activity_id,
                        dt,
                        activity_type,
                        int(duration),
                        round(float(distance), 2) if distance else None,
                        entry.get("averageHeartRate"),
                        entry.get("maxHeartRate"),
                        entry.get("averagePace"),
                        entry.get("trainingEffect"),
                        # PHASE 19 ADDITIONS (NULL-safe — keys verified by Wave-0 probe
                        # + RESEARCH §Deep Research §1)
                        entry.get("activityTrainingLoad"),
                        entry.get("directWorkoutRpe"),
                        entry.get("directWorkoutFeel"),
                    ))
        except Exception as e:
            logger.error(f"Error parsing activity file {file_path.name}: {e}")

    # Bulk insert activities
    if activities:
        logger.info(f"Ingesting {len(activities)} activity summaries...")
        with conn.cursor() as cur:
            insert_query = """
            INSERT INTO activities (
                activity_id, date, type, duration_sec, distance_m,
                avg_hr, max_hr, avg_pace, training_effect,
                training_load, perceived_exertion, feel
            ) VALUES %s
            ON CONFLICT (activity_id) DO UPDATE SET
                date = EXCLUDED.date,
                type = EXCLUDED.type,
                duration_sec = EXCLUDED.duration_sec,
                distance_m = EXCLUDED.distance_m,
                avg_hr = EXCLUDED.avg_hr,
                max_hr = EXCLUDED.max_hr,
                avg_pace = EXCLUDED.avg_pace,
                training_effect = EXCLUDED.training_effect,
                training_load = EXCLUDED.training_load,
                perceived_exertion = EXCLUDED.perceived_exertion,
                feel = EXCLUDED.feel;
            """
            execute_values(cur, insert_query, activities)
        conn.commit()
        logger.info("Activities successfully ingested.")

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/ingest_garmin_zip.py <path_to_unzipped_garmin_folder_or_zip>")
        sys.exit(1)
        
    path = sys.argv[1]
    
    # Check if we need to unzip first
    extract_dir = path
    if path.endswith(".zip"):
        extract_dir = "/tmp/garmin_export_extract"
        logger.info(f"Extracting {path} to temporary directory {extract_dir}...")
        with zipfile.ZipFile(path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        logger.info("Extraction complete.")
        
    try:
        conn = get_db_connection()
        setup_schema(conn)
        
        parse_and_ingest_wellness(conn, extract_dir)
        parse_and_ingest_activities(conn, extract_dir)
        
        conn.close()
        logger.info("Ingestion completed successfully!")
    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
