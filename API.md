# Chicken counter REST API

Base URL: http://ZIMA_IP:8080

GET /api/status returns the schedule, configured coops (no connection credentials),
active job, and a token for action requests.
Send that token in X-Check-Token for POST requests. This is cross-site request
protection for the local dashboard, not an account login.

POST /api/checks accepts:
    {"coop_ids": [1, 2]}
Omit coop_ids or supply null to check all configured coops.
Returns HTTP 202 with job_id, status, progress and source.
There is one active job at a time. Overlapping submissions return HTTP 409,
invalid configured coop selections return 400 (typed/body validation returns 422), and a missing action token returns 403.

GET /api/checks lists the latest 20 jobs.
GET /api/checks/latest returns the most recently submitted job, or null.
GET /api/checks/JOB_ID returns one job, or 404.
GET /api/results lists the latest 20 finished run results, including legacy history.
POST /api/light/off switches Hue off and cancels its alert effect in one request.
It returns 409 while a check is running.

Job status: queued, running, completed, failed or interrupted.
completed means processing finished. Read result.status to determine the outcome:
observed_expected, check_needed or error. A completed job may contain camera/API
errors because the other coop was still checked and alerts were attempted.
failed means orchestration failed before a full result was available.
Interrupted jobs remain recorded after process restart; they are not resumed.
Job metadata follows RETENTION_DAYS cleanup after checks.

The UI uses these REST endpoints. The timer in scheduler.py calls the same
CheckService.submit method in-process. It does not make a localhost HTTP request.
Manual and scheduled checks share concurrency and persistence behavior.
Scheduled jobs are deduplicated by local date, including existing scheduled runs.
An interrupted or failed scheduled job is not automatically retried that night.

There are no changes to ports, volumes, environment variables or normal alerts.
Existing run history and images are retained. API routes /api/check and /api/hue/off
from the earlier dashboard are replaced by /api/checks and /api/light/off.

Example client (Python standard library):

    import json, urllib.request
    base = "http://ZIMA_IP:8080"
    with urllib.request.urlopen(base + "/api/status") as response:
        token = json.load(response)["token"]
    request = urllib.request.Request(
        base + "/api/checks",
        json.dumps({"coop_ids": [1, 2]}).encode(),
        {"Content-Type": "application/json", "X-Check-Token": token},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        job = json.load(response)
    print(job["job_id"])
    # Poll GET /api/checks/<job_id> to follow progress and receive the result.

FastAPI exposes OpenAPI at /openapi.json and interactive documentation at /docs.
