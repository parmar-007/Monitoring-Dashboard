// ============================================
// Global Variable
// Stores all application data
// ============================================

let applications = [];


// ============================================
// Fetch Applications By Selected Date
// ============================================

async function fetchApplications(selectedDate) {

    try {

        const response = await fetch(
            `http://127.0.0.1:8000/applications/${selectedDate}`
        );

        applications = await response.json();

        loadApplications();

        updateSummaryCards();

        // Auto select first application

        if (applications.length > 0) {

            getApplicationDetails(
                applications[0].application,
                selectedDate
            );

        }

    }
    catch (error) {

        console.error(
            "Error Fetching Applications:",
            error
        );

    }

}


// ============================================
// Populate Summary Cards
// ============================================

function updateSummaryCards() {

    const total = applications.length;

    const success =
        applications.filter(
            app => app.status === "SUCCESS"
        ).length;

    const failed =
        applications.filter(
            app => app.status === "FAILED"
        ).length;

    const running =
        applications.filter(
            app => app.status === "RUNNING"
        ).length;

    document.getElementById(
        "totalApplications"
    ).textContent = total;

    document.getElementById(
        "successCount"
    ).textContent = success;

    document.getElementById(
        "failedCount"
    ).textContent = failed;

    document.getElementById(
        "runningCount"
    ).textContent = running;

}


// ============================================
// Render Table Data
// ============================================

function loadApplications() {

    const tableBody =
        document.getElementById(
            "applicationTableBody"
        );

    tableBody.innerHTML = "";

    applications.forEach((app, index) => {

        let statusClass = "";

        if (app.status === "SUCCESS") {
            statusClass = "success";
        }

        if (app.status === "FAILED") {
            statusClass = "failed";
        }

        if (app.status === "RUNNING") {
            statusClass = "running";
        }

        const row =
            document.createElement("tr");

        row.innerHTML = `
            <td>${index + 1}</td>

            <td>${app.application}</td>

            <td>${app.execution_date}</td>

            <td>
                <span class="status ${statusClass}">
                    ${app.status}
                </span>
            </td>

            <td>${app.total_records}</td>

            <td>${app.end_time}</td>

            <td>
                <button
                    onclick="viewLog(event,'${app.application}')">

                    View Log

                </button>
            </td>
        `;

        row.addEventListener(
            "click",
            () => {

                getApplicationDetails(
                    app.application,
                    app.execution_date
                );

            }
        );

        tableBody.appendChild(row);

    });

}


// ============================================
// Fetch Selected Application Details
// ============================================

async function getApplicationDetails(
    applicationName,
    selectedDate
) {

    try {

        const response = await fetch(
            `http://127.0.0.1:8000/application/${applicationName}/${selectedDate}`
        );

        const data =
            await response.json();

        showApplicationDetails(data);

    }
    catch (error) {

        console.error(
            "Error Fetching Details:",
            error
        );

    }

}


// ============================================
// Update Details Panel
// ============================================

function showApplicationDetails(data) {

    document.getElementById(
        "selectedApplicationTitle"
    ).textContent =
        data.application;

    document.getElementById(
        "statusValue"
    ).textContent =
        data.status;

    document.getElementById(
        "executionId"
    ).textContent =
        data.execution_id;

    document.getElementById(
        "startTime"
    ).textContent =
        data.start_time;

    document.getElementById(
        "endTime"
    ).textContent =
        data.end_time;

    document.getElementById(
        "duration"
    ).textContent =
        data.duration_seconds + " sec";

    document.getElementById(
        "totalRecords"
    ).textContent =
        data.total_records;

    document.getElementById(
        "errorCode"
    ).textContent =
        data.error_code || "-";

    document.getElementById(
        "errorMessage"
    ).textContent =
        data.error_message || "-";

}


// ============================================
// View Log Button
// Current Version Shows Alert
// Later we will open Modal Popup
// ============================================

function viewLog(
    event,
    applicationName
) {

    event.stopPropagation();

    alert(
        "View Log : " +
        applicationName
    );

}


// ============================================
// Calendar Date Change Event
// ============================================

const reportDate =
    document.getElementById(
        "reportDate"
    );

if (reportDate) {

    reportDate.addEventListener(
        "change",
        function () {

            const selectedDate =
                this.value;

            fetchApplications(
                selectedDate
            );

        }
    );

}


// ============================================
// Dashboard Load Event
// ============================================

window.onload = function () {

    console.log(
        "Dashboard Loaded Successfully"
    );

    // Default Date

    const defaultDate =
        "2026-10-05";

    document.getElementById(
        "reportDate"
    ).value =
        defaultDate;

    fetchApplications(
        defaultDate
    );

};