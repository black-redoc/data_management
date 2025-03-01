from fastapi import File, UploadFile, FastAPI
from typing import Tuple
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
import pandas as pd
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from contextlib import asynccontextmanager
import os
import traceback as tb
from mangum import Mangum
from fastapi.staticfiles import StaticFiles

# Load environment variables
DB_URL = os.environ.get("DB_URL", "sqlite:///data.db")
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "1000"))

# Create DB engine and session
engine = create_engine(DB_URL, echo=True)
SessionLocal = None
if "postgres" in DB_URL:
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
else:
    SessionLocal = sessionmaker(bind=engine)


Base = declarative_base()


def create_database():
    Base.metadata.create_all(bind=engine)


# Dependency to get the DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_database()
    yield


def check_job_columns(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    valid_df = df.copy()
    invalid_df = df.copy()
    valid_df = valid_df[(valid_df["id"].notnull()) & (valid_df["job"].notnull())]
    valid_df = valid_df.astype(
        {
            "id": "int16",
            "job": "string",
        },
    )
    null_rows = valid_df[(valid_df["id"].isnull()) & (valid_df["job"].isnull())]
    if len(null_rows) > 0:
        invalid_df = pd.concat(
            [invalid_df, null_rows],
        )
    return valid_df, invalid_df


def check_hired_employees_columns(
    df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    valid_df = df.copy()
    invalid_df = df.copy()
    valid_df = valid_df[
        (valid_df["id"].notnull())
        & (valid_df["name"].notnull())
        & (valid_df["datetime"].notnull())
        & (valid_df["department_id"].notnull())
        & (valid_df["job_id"].notnull())
    ]
    valid_df = valid_df.astype(
        {
            "id": "int16",
            "name": "string",
            "datetime": "string",
            "department_id": "int16",
            "job_id": "int16",
        },
        errors="ignore",
        copy=True,
    )
    null_rows = valid_df = valid_df[
        (valid_df["id"].isnull())
        & (valid_df["name"].isnull())
        & (valid_df["datetime"].isnull())
        & (valid_df["department_id"].isnull())
        & (valid_df["job_id"].isnull())
    ]
    if len(null_rows) > 0:
        invalid_df = pd.concat(
            [invalid_df, null_rows],
        )
    return valid_df, invalid_df


def check_departments_columns(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    valid_df = df.copy()
    invalid_df = df.copy()
    valid_df = valid_df[(valid_df["id"].notnull()) & (valid_df["department"].notnull())]
    valid_df = valid_df.astype(
        {
            "id": "int16",
            "department": "string",
        },
    )
    null_rows = valid_df[(valid_df["id"].isnull()) & (valid_df["department"].isnull())]
    if len(null_rows) > 0:
        invalid_df = pd.concat(
            [invalid_df, null_rows],
        )
    return valid_df, invalid_df


# Load schemas
jobs_schema = [
    "id",
    "job",
]
deparments_schema = [
    "id",
    "department",
]
hired_employees_schema = [
    "id",
    "name",
    "datetime",
    "department_id",
    "job_id",
]
schemas = {
    "jobs": (jobs_schema, check_job_columns),
    "departments": (deparments_schema, check_departments_columns),
    "hired_employees": (hired_employees_schema, check_hired_employees_columns),
}

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
handler = Mangum(app)


# ui routes
@app.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/fileupload")
def fileupload(request: Request):
    return templates.TemplateResponse(
        "fileupload.html",
        {
            "request": request,
        },
    )


# api routes
@app.get("/healthcheck")
def health():
    return "OK"


@app.post("/api/v1/uploadfile/{file_type}", name="upload_file")
def upload_file(file_type: str, file: UploadFile = File(...)):
    schema, check_columns = schemas.get(file_type, (None, None))
    if not schema:
        return JSONResponse(
            {
                "file_type": file_type,
                "status": "error",
                "message": "file_type not found",
            },
            400,
        )
    file_bytes = file.file
    df = pd.read_csv(file_bytes, names=schema)
    df, invalid_df = check_columns(df)
    try:
        df.to_sql(
            file_type, engine, if_exists="append", index=False, chunksize=CHUNK_SIZE
        )
        print({"invalid_rows": invalid_df})
        return JSONResponse(
            {
                "file_type": file_type,
                "status": "success",
            },
            201,
        )
    except Exception as e:
        tb.print_stack()
        print(e)
        return JSONResponse(
            {
                "file_type": file_type,
                "status": "error",
                "message": "error while uploading file",
            },
            400,
        )


@app.get("/api/v1/getquarteremployees/{year}")
def get_quarter_employees(year: int):
    query = f"""
    SELECT
        d.department,
        j.job,
        EXTRACT(QUARTER FROM CAST(he.datetime AS TIMESTAMP)) AS quarter,
        COUNT(*) AS num_employees
    FROM
        hired_employees he
    JOIN
        departments d ON he.department_id = d.id
    JOIN
        jobs j ON he.job_id = j.id
    WHERE
        EXTRACT(YEAR FROM CAST(he.datetime AS TIMESTAMP)) = {year}
    GROUP BY
        d.department, j.job, EXTRACT(QUARTER FROM CAST(he.datetime AS TIMESTAMP))
    ORDER BY
        d.department, j.job;
    """
    try:
        df_generator = pd.read_sql(
            query,
            engine,
            chunksize=CHUNK_SIZE,
        )
        df = pd.concat([df for df in df_generator])
        df_q1 = df[df["quarter"] == 1]
        df_q2 = df[df["quarter"] == 2]
        df_q3 = df[df["quarter"] == 3]
        df_q4 = df[df["quarter"] == 4]

        df_q1 = df_q1.rename(columns={"num_employees": "Q1"}).drop(columns=["quarter"])
        df_q2 = df_q2.rename(columns={"num_employees": "Q2"}).drop(columns=["quarter"])
        df_q3 = df_q3.rename(columns={"num_employees": "Q3"}).drop(columns=["quarter"])
        df_q4 = df_q4.rename(columns={"num_employees": "Q4"}).drop(columns=["quarter"])

        df_final = (
            df_q1.merge(df_q2, on=["department", "job"])
            .merge(df_q3, on=["department", "job"])
            .merge(df_q4, on=["department", "job"])
        )

        content = json.loads(df_final.to_json(orient="records"))
        return JSONResponse(
            {
                "data": content,
            }
        )
    except Exception as e:
        tb.print_stack()
        print(e)
        return JSONResponse(
            {
                "status": "error",
                "message": "error while getting quarter employees",
            },
            400,
        )


@app.get("/api/v1/listofids")
def list_of_ids():
    try:
        df_generator = pd.read_sql(
            """
            SELECT
            departments.id AS id,
            departments.department AS department,
            SUM(hired_employees.id) AS hired
            FROM hired_employees
            JOIN jobs ON hired_employees.job_id = jobs.id
            JOIN departments ON hired_employees.department_id = departments.id
            GROUP BY departments.department, departments.id
            """,
            engine,
            chunksize=CHUNK_SIZE,
        )
        df = pd.concat([df for df in df_generator])
        content = json.loads(df.to_json(orient="records"))
        return JSONResponse(
            {
                "data": content,
            }
        )
    except Exception as e:
        tb.print_stack()
        print(e)
        return JSONResponse(
            {
                "status": "error",
                "message": "error while getting list of ids",
            },
            400,
        )


@app.get("/api/v1/getfile/{file_type}", name="get_file")
def get_file(file_type: str):
    if file_type not in schemas:
        return JSONResponse(
            {
                "file_type": file_type,
                "status": "error",
                "message": "file_type not found",
            },
            400,
        )
    try:
        df_generator = pd.read_sql(
            f"SELECT * FROM {file_type} ORDER BY id", engine, chunksize=CHUNK_SIZE
        )
        df = pd.concat([df for df in df_generator])
        content = json.loads(df.to_json(orient="records"))
        return JSONResponse(
            {
                "file_type": file_type,
                "data": content,
            },
        )
    except Exception as e:
        tb.print_stack()
        print(e)
        return JSONResponse(
            {
                "file_type": file_type,
                "status": "error",
                "message": "error while getting file",
            },
            400,
        )
