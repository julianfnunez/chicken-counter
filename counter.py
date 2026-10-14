import argparse, datetime as dt, fcntl, json, logging, os
from pathlib import Path
import shutil, sqlite3, time
from zoneinfo import ZoneInfo

from ai import analyze
from camera import capture
from config import load_coops
from notifications import notify, hue_alert, hue_off, notification_text

LOG = logging.getLogger("chickens")

def classify(frames, expected):
    # Agreement is evidence, not a calibrated probability. One photo cannot pass.
    ok = len(frames) >= 3 and all(f["clear"] and f["count"] == expected for f in frames)
    return "observed_expected" if ok else "check_needed"

def connect(data):
    db = sqlite3.connect(data / "history.sqlite")
    db.execute("CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, created TEXT, local_date TEXT, scheduled INTEGER, status TEXT, result TEXT)")
    return db

def summary_status(coops):
    if any(c["status"] == "error" for c in coops):
        return "error"
    if all(c["status"] == "observed_expected" for c in coops):
        return "observed_expected"
    return "check_needed"

def run(data, db, zone, scheduled=False, images=None, coop_id=None, coop_ids=None, progress=None):
    now = dt.datetime.now(zone)
    folder = data / ("run-" + now.strftime("%Y%m%d-%H%M%S-%f"))
    folder.mkdir()
    configured = load_coops()
    if coop_id is not None:
        configured = [c for c in configured if c["id"] == coop_id]
        if not configured:
            raise ValueError("Selected coop is not configured")
    if coop_ids is not None:
        configured = [c for c in configured if c["id"] in coop_ids]
    result = {"created": now.isoformat(), "status": "error", "coops": []}
    for config in configured:
        coop = {"id": config["id"], "name": config["name"], "expected": config["expected"],
                "status": "error", "frames": [], "usage": []}
        coop_folder = folder / f"coop-{config['id']}"
        coop_folder.mkdir()
        try:
            if progress:
                progress(f"Capturing {config['name']}")
            paths = images if images else capture(coop_folder, config["url"])
            # Each frame is a fresh independent request.
            analyses = []
            for index, path in enumerate(paths, 1):
                if progress:
                    progress(f"Counting {config['name']}: frame {index}/{len(paths)}")
                analyses.append(analyze([path]))
            coop["frames"] = [a["frames"][0] for a in analyses]
            coop["usage"] = [a["usage"] for a in analyses]
            coop["model"] = analyses[0]["model"]
            coop["status"] = classify(coop["frames"], coop["expected"])
        except Exception as exc:
            coop["error"] = str(exc) if isinstance(exc, RuntimeError) else f"Processing failed ({type(exc).__name__})"
        (coop_folder / "result.json").write_text(json.dumps(coop, indent=2))
        result["coops"].append(coop)
    result["image_folder"] = folder.name
    result["status"] = summary_status(result["coops"])
    if progress:
        progress("Sending alerts and saving results")
    try:
        result["hue"] = hue_alert(result)
    except RuntimeError as exc:
        result["hue"] = str(exc)
        LOG.error("Hue alert failed; ntfy will still be attempted")
    try:
        notify(result)
        result["notification"] = "attempted" if os.environ.get("NTFY_URL") else "disabled"
    except RuntimeError as exc:
        result["notification"] = str(exc)
        LOG.error("Notification failed; inspect history and notification configuration")
    (folder / "result.json").write_text(json.dumps(result,indent=2))
    db.execute("INSERT INTO runs (created,local_date,scheduled,status,result) VALUES (?,?,?,?,?)",
               (now.isoformat(),now.date().isoformat(),int(scheduled),result["status"],json.dumps(result)))
    db.commit()
    LOG.info("%s: %s", result["status"], notification_text(result))
    retention = int(os.environ.get("RETENTION_DAYS","30"))
    cutoff = time.time() - retention * 86400
    for old in data.glob("run-*"):
        if old.is_dir() and old.stat().st_mtime < cutoff:
            shutil.rmtree(old)
    db.execute("DELETE FROM runs WHERE created < ?",((now-dt.timedelta(days=retention)).isoformat(),))
    db.commit()
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once",action="store_true")
    parser.add_argument("--images",nargs="+",type=Path,help="Analyze JPG/PNG files instead of RTSP")
    parser.add_argument("--coop", type=int, help="Check one configured coop; required with --images when multiple coops exist")
    parser.add_argument("--test-hue", action="store_true", help="Turn configured Hue light red without camera/API calls")
    args = parser.parse_args()
    if args.test_hue:
        try:
            outcome = hue_alert({"status": "check_needed"}, force=True)
        except RuntimeError as exc:
            parser.exit(1, str(exc) + "\n")
        print("Hue test: " + outcome)
        return 0 if outcome == "red_requested" else 1
    try:
        coops = load_coops()
    except (ValueError, KeyError):
        parser.error("Invalid coop configuration; check COOP_COUNT and each EXPECTED_CHICKENS value")
    if args.coop is not None and args.coop not in [c["id"] for c in coops]:
        parser.error("--coop is not configured")
    if args.images and len(coops) > 1 and args.coop is None:
        parser.error("Specify --coop with --images when multiple coops are configured")
    zone = ZoneInfo(os.environ.get("TZ","America/New_York"))
    hour,minute = map(int,os.environ.get("CHECK_TIME","22:00").split(":"))
    dt.time(hour,minute)
    if any(not 0 <= c["expected"] <= 100 for c in coops) or int(os.environ.get("RETENTION_DAYS","30")) < 1:
        parser.error("Expected count and retention must be positive")
    data = Path(os.environ.get("DATA_DIR","/data"))
    data.mkdir(parents=True,exist_ok=True)
    with (data / "counter.lock").open("w") as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1,"Another chicken check is running; try again shortly.\n")
        db = connect(data)
        if args.once or args.images or args.coop is not None:
            result = run(data,db,zone,images=args.images,coop_id=args.coop)
            print(json.dumps(result,indent=2))
            return 1 if result["status"] == "error" else 0
        LOG.info("Nightly check at %02d:%02d %s",hour,minute,zone)
        while True:
            now = dt.datetime.now(zone)
            done = db.execute("SELECT 1 FROM runs WHERE local_date=? AND scheduled=1",(now.date().isoformat(),)).fetchone()
            if (now.hour,now.minute) >= (hour,minute) and not done:
                run(data,db,zone,scheduled=True)
            time.sleep(20)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(main())
