# Chicken Counter

Checks RTSP camera images to confirm the expected number of chickens in each coop.
Run checks from a web dashboard or on a nightly schedule. Unexpected or unclear
counts and camera/API errors can trigger an ntfy notification and a red Hue light.

## How it works

FFmpeg captures four frames per coop, about ten seconds apart. Each frame is sent
individually to OpenAI for a count and bird locations. A coop passes when all four
frames are clear and match its expected count; every coop must pass independently.

FastAPI serves the dashboard and REST API. A shared background service executes
manual and scheduled checks, prevents overlapping runs, and records job progress.
SQLite stores results; captured images are retained alongside them in /data.

The dashboard shows recent results and images, runs checks for all or selected
coops, and turns the Hue light off. Hue alerts pulse briefly, then remain red,
using one Bridge request. Successful checks leave the light unchanged.

Counts are estimates. Validate empty and occupied images from each camera,
including night vision, before relying on alerts.

## Install on ZimaOS

Use this Docker image:

    ghcr.io/julianfnunez/chicken-counter:latest

Configure the container:

- Map host port 8080 to container port 8080.
- Mount a persistent folder, such as /DATA/AppData/chicken-counter, to /data.
- Set restart policy to unless-stopped and keep the default command.
- Supply your API key, camera URLs, and desired notification connection settings.

Open http://ZIMA_IP:8080. Interactive API documentation is at /docs.

The image includes non-secret settings from .env.defaults. Container environment
variables override those values. Personal credentials belong in the container
configuration or your local .env, not in the repository.

### Docker Compose

Copy .env.example to .env and fill in your connection settings:

    cp .env.example .env
    docker compose -f compose.registry.yaml up -d

To update the image:

    docker compose -f compose.registry.yaml pull
    docker compose -f compose.registry.yaml up -d

To build from source instead:

    docker compose up -d --build

## Configuration

| Variable | Purpose / bundled default |
| --- | --- |
| OPENAI_API_KEY | Required OpenAI API key; API billing is separate from ChatGPT |
| COOP_1_RTSP_URL, COOP_2_RTSP_URL | Required camera stream URLs |
| OPENAI_MODEL | gpt-4.1 |
| COOP_COUNT | 2; supports 1–20 coops |
| COOP_n_NAME | Coop 1 / Coop 2 |
| COOP_n_EXPECTED_CHICKENS | 3 / 1; required for additional coops |
| CHECK_TIME | 22:00, in 24-hour format |
| TZ | America/New_York, including daylight saving |
| RETENTION_DAYS | 30 |
| NTFY_URL | Full topic URL; empty disables notifications |
| NTFY_TOKEN | Optional authentication token |
| NOTIFY_SUCCESS | false; true also sends successful checks |
| HUE_ENABLED | true; set false when Hue is unused |
| HUE_BRIDGE_URL | Local Bridge URL, e.g. http://192.168.1.60 |
| HUE_API_KEY | Bridge-issued API username/key |
| HUE_LIGHT_ID | Numeric v1 ID of a color-capable light |
| WEB_PORT | 8080 |
| DATA_DIR | /data |

A scheduled check runs once per local date. Starting after CHECK_TIME triggers
today's check if it has not been attempted. Failed or interrupted scheduled jobs
are recorded and are not automatically retried that night.

## Run locally in Linux / WSL

Requires Python 3.10+ and FFmpeg.

    sudo apt install python3-venv ffmpeg
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env

Edit .env, then start:

    set -a
    source .env.defaults
    source .env
    set +a
    DATA_DIR=./data python web.py

Open http://localhost:8080. Stop with Ctrl+C.

CLI checks:

    DATA_DIR=./data python counter.py --once
    DATA_DIR=./data python counter.py --once --coop 2
    DATA_DIR=./data python counter.py --coop 1 --images ./samples/frame-*.jpg
    python counter.py --test-hue

## API and development

See [API.md](API.md) for endpoints and job states.

- web.py and static/index.html: REST endpoints and dashboard.
- service.py and scheduler.py: jobs, concurrency, and nightly triggers.
- counter.py: check coordination, persistence, and retention.
- ai.py, camera.py, notifications.py: external integrations.
- config.py: coop configuration.
- docker-entrypoint.py: bundled defaults.

Run tests:

    pip install -r requirements-dev.txt
    python -m unittest discover -s tests -v

GitHub Actions tests and publishes the Docker image on pushes to main and version
tags. See [PUBLISH-GITHUB.md](PUBLISH-GITHUB.md) for registry setup.
