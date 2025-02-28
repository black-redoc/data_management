import io
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, Mock
from src.api import app, Base, get_db, create_database
import os
import pandas as pd

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
# Create a new engine and session for testing
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables
Base.metadata.create_all(bind=engine)


# Dependency override function
def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Override the app's database dependency
app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def mock_db_session():
    return Mock(spec=Session)


@pytest.fixture(autouse=True)
def run_around_tests():
    # Setup: can be used to initialize the database
    create_database()

    yield  # this is where the testing happens

    # Teardown
    try:
        os.remove("test.db")
    except:
        """
        Do nothing
        """


# UI Route Tests
def test_index_route(client, mock_db_session):
    """Test the index route returns 200 status code and correct template"""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_fileupload_route(client, mock_db_session):
    """Test the fileupload route returns 200 status code and correct template"""
    response = client.get("/fileupload")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


# API Route Tests - File Upload Tests
@pytest.mark.parametrize("file_type", ["departments", "jobs", "hired_employees"])
def test_upload_file_success(file_type, client, mock_db_session):
    """Test successful file upload for different file types"""
    test_file_content = b"id,column1,column2\n1,value1,value2\n2,value3,value4"
    test_file = io.BytesIO(test_file_content)

    with patch("src.api.upload_file"):

        response = client.post(
            f"/api/v1/uploadfile/{file_type}",
            files={"file": (f"{file_type}.csv", test_file, "text/csv")},
        )

        assert response.status_code == 201
        assert "success" in response.json()["status"]


def test_upload_file_invalid_type(client, mock_db_session):
    """Test file upload with invalid file type"""
    test_file = io.BytesIO(b"test content")

    response = client.post(
        "/api/v1/uploadfile/invalid_type",
        files={"file": ("test.csv", test_file, "text/csv")},
    )

    assert response.status_code == 400
    assert "not found" in response.json()["message"]


def test_upload_file_no_file(client, mock_db_session):
    """Test file upload with no file provided"""
    response = client.post("/api/v1/uploadfile/departments")
    assert response.status_code == 422  # Unprocessable Entity


# Quarter Employees Tests
def test_get_quarter_employees_success(client, mock_db_session):
    """Test getting employees by quarter with valid year"""
    with patch("src.api.get_quarter_employees"), patch(
        "pandas.read_sql"
    ) as mock_read_sql:
        mock_read_sql.return_value = (
            pd.DataFrame(
                [
                    {
                        "department": "Engineering",
                        "job": "Engineer",
                        "quarter": 1,
                        "num_employees": 10,
                    },
                    {
                        "department": "Engineering",
                        "job": "Engineer",
                        "quarter": 2,
                        "num_employees": 20,
                    },
                ]
            )
            for _ in range(2)
        )

        response = client.get("/api/v1/getquarteremployees/2021")

        assert response.status_code == 200
        assert response.json() is not None


def test_get_quarter_employees_invalid_year(client, mock_db_session):
    """Test getting employees by quarter with invalid year format"""
    response = client.get("/api/v1/getquarteremployees/invalid")
    assert response.status_code == 422  # Validation error


def test_get_quarter_employees_no_data(client, mock_db_session):
    """Test getting employees by quarter with year that has no data"""
    with patch("src.api.get_quarter_employees"), patch(
        "pandas.read_sql"
    ) as mock_read_sql:
        mock_read_sql.return_value = None

        response = client.get("/api/v1/getquarteremployees/2021")

        assert response.status_code == 400
        assert response.json() is not None


# List of IDs Tests
def test_list_of_ids_success(client, mock_db_session):
    """Test getting list of departments with hire counts"""
    mock_data = [
        {"department": "Engineering", "hired": 10},
        {"department": "Marketing", "hired": 5},
        {"department": "Sales", "hired": 8},
    ]

    with patch("src.api.list_of_ids") as mock_get, patch.dict(
        {"os.environ": {"DB_URL": "sqlite:///test.db"}}
    ):
        mock_get.return_value = mock_data

        response = client.get("/api/v1/listofids")

        assert response.status_code == 200
        assert response.json() is not None


def test_list_of_ids_empty(client, mock_db_session):
    """Test getting list of departments when no data is available"""
    with patch("src.api.list_of_ids") as mock_get, patch.dict(
        {"os.environ": {"DB_URL": "sqlite:///test.db"}}
    ):
        mock_get.return_value = []

        response = client.get("/api/v1/listofids")

        assert response.status_code == 200
        assert response.json() is not None


# Get File Tests
@pytest.mark.parametrize("file_type", ["departments", "jobs", "hired_employees"])
def test_get_file_success(file_type, client, mock_db_session):
    """Test getting data for specific file types"""

    with patch("src.api.get_file"), patch.dict(
        {"os.environ": {"DB_URL": "sqlite:///test.db"}}
    ):

        response = client.get(f"/api/v1/getfile/{file_type}")

        assert response.status_code == 200
        assert response.json() is not None


def test_get_file_invalid_type(client, mock_db_session):
    """Test getting data with invalid file type"""
    response = client.get("/api/v1/getfile/invalid_type")
    assert response.status_code == 400
    assert "not found" in response.json()["message"]


def test_get_file_error_handling(client, mock_db_session):
    """Test error handling when database operation fails"""
    with patch("src.api.get_file") as mock_get:
        mock_get.side_effect = Exception("Database error")

        response = client.get("/api/v1/getfile/department")

        assert response.status_code == 400
        assert "message" in response.json()
