from fastapi import FastAPI

from fastapi.middleware.cors import CORSMiddleware

from services.file_reader import get_applications_by_date


app = FastAPI()


# Allow Frontend Access

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.get("/")
def health_check():

    return {
        "status": "UP"
    }


@app.get("/applications/{selected_date}")
def get_dashboard_data(selected_date):

    return get_applications_by_date(selected_date)

@app.get("/summary/{selected_date}")
def get_summary(selected_date):

    applications = get_applications_by_date(
        selected_date
    )

    summary = {
        "total": len(applications),

        "success": len(
            [
                a
                for a in applications
                if a["status"] == "SUCCESS"
            ]
        ),

        "failed": len(
            [
                a
                for a in applications
                if a["status"] == "FAILED"
            ]
        ),

        "running": len(
            [
                a
                for a in applications
                if a["status"] == "RUNNING"
            ]
        )
    }

    return summary

@app.get(
    "/application/{app_name}/{selected_date}"
)
def get_application_details(
    app_name,
    selected_date
):

    from pathlib import Path
    import json

    file_path = (
        Path("../logs")
        / app_name
        / f"{selected_date}.json"
    )

    if not file_path.exists():

        return {
            "message": "File not found"
        }

    with open(file_path, "r") as file:

        return json.load(file)