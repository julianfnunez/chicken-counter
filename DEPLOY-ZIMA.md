# Deploy to ZimaOS

Copy this entire chicken-counter folder to a persistent folder on the ZimaBoard.
Copy your working Windows/WSL .env into that folder; do not replace it with the
example. It contains your real camera URLs, API keys, ntfy topic and Hue settings.
Confirm OPENAI_MODEL=gpt-4.1, NOTIFY_SUCCESS=false, and CHECK_TIME/TZ.

Open a ZimaOS administrator terminal or SSH session and cd into that folder.

    docker compose build
    docker compose run --rm chicken-counter python /app/counter.py --once

This live test spends API credit. During daytime, empty coops should trigger ntfy
and Hue red. After confirming the results, start the nightly scheduler:

    docker compose up -d
    docker compose logs --tail=50 chicken-counter

The default image command is python /app/counter.py, without --once.
The log should show the configured nightly time. Starting after that time performs
a late check if today's scheduled check is absent. The ./data bind mount persists
images, history and scheduling state across container restarts.

## Settings in ZimaOS Docker properties

The build tags the image chicken-counter:local. If you manage the container through
ZimaOS properties, use that local image and enter your environment variables there.
Use plain values without surrounding quotes. Map a persistent host data folder to
/data. No published ports or privileged mode are required. Restart policy:
unless-stopped. Leave the command at its default (no --once).

Environment variables to carry over:
OPENAI_API_KEY, OPENAI_MODEL, COOP_COUNT,
COOP_1_NAME, COOP_1_EXPECTED_CHICKENS, COOP_1_RTSP_URL,
COOP_2_NAME, COOP_2_EXPECTED_CHICKENS, COOP_2_RTSP_URL,
TZ, CHECK_TIME, RETENTION_DAYS, NTFY_URL, NTFY_TOKEN, NOTIFY_SUCCESS,
HUE_ENABLED, HUE_BRIDGE_URL, HUE_API_KEY, HUE_LIGHT_ID.

Example time settings: CHECK_TIME=22:00 and TZ=America/New_York.
Hue uses your working http:// Bridge URL. The two camera counts default to 3 and 1.

Use one running container against the data folder. If replacing the Compose-created
container with a GUI-managed one, stop it first with docker compose down. Point the
new container at the same absolute host data folder. GUI edits and subsequent
docker compose commands are separate configuration sources: recreating through
Compose reapplies compose.yaml/.env. Pick one for ongoing management.

If you manage with Compose, change .env and apply with:

    docker compose up -d --force-recreate

After code updates, rebuild with:

    docker compose up -d --build

## Verification

Check both cameras and Hue are reachable from the ZimaBoard, and HTTPS access to
OpenAI and ntfy works. A successful count leaves Hue alone and sends no ntfy
message when NOTIFY_SUCCESS=false. Manually clear any red test light.
No live deployment or Docker build was performed in the development environment.

## Dashboard update

The image's default command is now python /app/web.py, which runs both the
dashboard and nightly scheduler. Map port 8080 to 8080 and open http://ZIMA_IP:8080.
This supersedes earlier statements that no ports are needed. Leave the command
at the new default; remove any old override to counter.py.
