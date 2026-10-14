"""Nightly trigger using the same check service as REST requests."""
import datetime as dt
import logging
import os
import time
from service import BusyError

def run_scheduler(service, stop=None):
    hour,minute=map(int,os.environ.get("CHECK_TIME","22:00").split(":"))
    dt.time(hour,minute)
    log=logging.getLogger("scheduler")
    log.info("Nightly check at %02d:%02d %s",hour,minute,service.zone)
    while stop is None or not stop.is_set():
        try:
            now=dt.datetime.now(service.zone)
            if (now.hour,now.minute)>=(hour,minute) and not service.scheduled_done(now.date().isoformat()):
                service.submit(source="scheduled")
        except BusyError:
            pass
        except Exception:
            log.exception("Scheduler error")
        if stop is None:
            time.sleep(20)
        else:
            stop.wait(20)
