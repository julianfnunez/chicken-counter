# Nightly chicken counter for ZimaBoard 2 / ZimaOS

A Docker service captures four RTSP frames about ten seconds apart, analyzes each frame in a separate OpenAI Responses API request, and records individual counts. The expected count is deliberately withheld from the model. Four clear matching counts produce “expected count observed”; any discrepancy or ambiguity asks you to inspect the camera. Camera and API failures are recorded as errors. This is a visual check, not proof that every chicken is safely inside.

Defaults: two coops (3 chickens in the main coop, 1 in the separate pen), 10 PM America/New_York, 30-day retention. Change these to match the birds expected in this particular coop. A model can confidently miscount overlapping birds, so review initial nightly results before relying on alerts.

## Install on your ZimaBoard

Download and extract this ZIP, then copy the chicken-counter folder to a persistent data folder on your ZimaBoard using its file manager or network share. Open a terminal on the ZimaBoard, or SSH into it if SSH is enabled. Run the following commands from that folder:

    cp .env.example .env
    chmod 600 .env
    nano .env

Set each COOP_n_RTSP_URL to the camera's actual stream URL. The example path is a placeholder. URL-encode special characters in the camera username/password. Keep the value single-quoted. Set OPENAI_API_KEY to your own OpenAI API key and verify each COOP_n_EXPECTED_CHICKENS. API billing is separate from your ChatGPT subscription; add API credit/billing in the OpenAI dashboard. Never paste the key into chat.

The default model is gpt-4.1, a configurable starting point; verify model access and assess counting quality with your own nighttime images. Set a different vision/structured-output compatible model through OPENAI_MODEL if needed. No model-specific price estimate is assumed.

Build and perform a live check before starting the scheduler:

    docker compose build
    docker compose run --rm chicken-counter python /app/counter.py --once

Inspect the JSON result and the four JPEGs in data/run-*/. Confirm that the field of view includes all roosts and floor areas. Then start:

    docker compose up -d
    docker compose logs --tail=50 -f

The container needs LAN access to the camera and outbound HTTPS to api.openai.com (and your notification server if enabled). It exposes no web port and needs no privileged mode. The build requires internet access for the Python image and Debian packages. Use a terminal with Docker access; if Docker reports permission denied, use your ZimaOS administrator terminal or sudo as appropriate.

If your ZimaOS app installer cannot build local Dockerfiles, use the terminal commands above. This package intentionally does not assume a particular ZimaOS GUI version or import format.

## Phone notifications (optional)

Install ntfy on your phone and subscribe to your chosen topic/server. Configure NTFY_URL as the full topic URL, for example https://your-ntfy-server.example/chickens, and NTFY_TOKEN if authentication is required. Follow your server's access-control setup and verify both publishing and phone delivery. An unprotected public topic can be read or spoofed by others who know its name.

NOTIFY_SUCCESS=false (the default) sends discrepancies/errors only. Set true to send a message after every check. Leaving NTFY_URL empty disables notifications. Images are not attached to notifications. Notification delivery failures are logged and stored, but cannot be reported through the same failed notification channel. Check the logs periodically.

## Operations

Run another immediate check while the scheduler is active:

    docker compose stop
    docker compose run --rm chicken-counter python /app/counter.py --once
    docker compose up -d

A shared file lock prevents simultaneous runs against the same data folder. Manual checks do not suppress that evening's scheduled run.

Test local pictures without the camera (put JPG/PNG files in a samples folder):

    docker compose stop
    docker compose run --rm -v ./samples:/samples:ro chicken-counter python /app/counter.py --images /samples/a.jpg /samples/b.jpg /samples/c.jpg /samples/d.jpg
    docker compose up -d

A single image can be analyzed but is always marked check_needed. Local sample files remain in samples; this mode does not copy them into retained run folders.

Change settings by editing .env and recreating:

    docker compose up -d --force-recreate

Stop the service:

    docker compose down

The data folder survives container replacement. Back it up if needed. history.sqlite contains counts, model/usage metadata and notification outcome; run folders contain JPEGs and result.json. Images and history older than RETENTION_DAYS are deleted after a run. No secret values are deliberately written to results or logs. Docker administrators can inspect the container environment and FFmpeg process arguments; protect host access and .env.

The scheduler uses the configured local timezone, including daylight saving. Restarting after CHECK_TIME performs one late check if today's scheduled result is absent. Restarting before CHECK_TIME waits. A failed scheduled check is recorded and is not retried that night; this bounds API spending and duplicate notifications. API requests retry transient errors up to three attempts, which can incur additional charges if a response was lost. A crash before a result is committed can cause a repeated check on restart. No historical nights are backfilled.

## Troubleshooting

- Camera error: verify RTSP is enabled, credentials/path, camera wake behavior and LAN reachability. Test the stream in VLC on the same network. The capture timeout is 75 seconds.
- HTTP 401: API key invalid. HTTP 429: quota, billing or rate limit. HTTP 400: request/model compatibility. Model output validation errors: review samples and try a compatible model.
- check_needed: review all four images and location descriptions. Overlap can produce a consistent undercount; changing the camera angle often helps.
- No nightly record: check container status, logs, CHECK_TIME/TZ, and writable data volume.
- No phone message: verify NTFY_URL, token, topic subscription and phone background notification settings.

## Development and verification

Python's standard library handles HTTP, SQLite and scheduling; FFmpeg handles RTSP. No Python package installation is needed.

    python -m unittest discover -s tests -v

Tests mock the API/camera and cover count disagreement, unclear images, malformed results, persistence and failure notification handling. They do not establish real-world vision accuracy. A live camera/API check is required after configuration.

Official API references:
https://developers.openai.com/api/docs/guides/images-vision
https://developers.openai.com/api/docs/guides/structured-outputs

## Multiple coops and updating an existing install

Replace counter.py with this version; keep your existing .env and data. Add:

    COOP_COUNT=2
    COOP_1_NAME='Main coop'
    COOP_1_EXPECTED_CHICKENS=3
    COOP_1_RTSP_URL='your-main-coop-RTSP-URL'
    COOP_2_NAME='Separate pen'
    COOP_2_EXPECTED_CHICKENS=1
    COOP_2_RTSP_URL='your-separate-pen-RTSP-URL'

COOP_COUNT selects consecutive coop IDs from 1 through that number (maximum 20).
Expected counts may be zero. If COOP_COUNT is absent, the old RTSP_URL and
EXPECTED_CHICKENS settings still work for one coop. With COOP_COUNT present,
the numbered settings are authoritative.

Every coop is checked even if another camera or API check fails. Results live
in data/run-*/coop-1/ and coop-2/, with one overall result.json and database row.
Overall success requires every coop to pass independently. Notifications combine
all coops into one message. NTFY_URL can remain empty; SMS is not implemented.

WSL, without Docker:

    set -a
    source .env
    set +a
    DATA_DIR=./data python3 counter.py --once

Test a particular camera:

    DATA_DIR=./data python3 counter.py --once --coop 2

Test saved images against a particular coop's expected count:

    DATA_DIR=./data python3 counter.py --coop 1 --images ./samples/frame-*.jpg

Selected-coop runs are manual only and do not affect the nightly schedule.
Two coops with four frames each make eight API requests per full check, before
transient retries. Each frame request is independent; agreement does not guarantee
accuracy. Test both occupied and empty images for each camera.

## Optional Hue light alert

Add HUE_ENABLED=false, HUE_BRIDGE_URL, HUE_API_KEY and HUE_LIGHT_ID to
your existing .env (see .env.example). This uses the local Hue v1 REST API.
After pairing the Bridge and identifying your living-room color light, set
HUE_ENABLED=true and reload the environment or recreate the Docker container.

When any checked coop needs inspection or has a capture/API error, the selected
light is switched on at full brightness and set to solid red. Success leaves
the light unchanged. Clear it manually in the Hue app or with your usual controls.
Manual single-coop and saved-image checks also trigger this behavior when enabled.
An unreachable Bridge or rejected command is recorded under the overall result's
hue field and does not prevent ntfy delivery. red_requested means the Bridge
confirmed the requested settings, not proof that the physical bulb changed.

Test without capturing pictures or spending API credit:

    DATA_DIR=./data python3 counter.py --test-hue

Docker equivalent:

    docker compose run --rm chicken-counter python /app/counter.py --test-hue

This test bypasses camera and coop configuration and turns the light red immediately.
No Bridge connection is made while HUE_ENABLED=false. HUE_LIGHT_ID is the numeric
v1 light ID, not a v2 UUID or the name of a room. Use a color-capable Hue light.
The sample HTTP URL is for your trusted local network; HTTPS URLs use normal
certificate verification. No blanket TLS-verification bypass is included.
Keep the Bridge API key private. Pairing and listing lights are described here:
https://developers.meethue.com/develop/get-started-2/
