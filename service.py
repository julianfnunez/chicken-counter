"""Shared asynchronous check service, persistence and concurrency."""
import datetime as dt
import fcntl
import json
import logging
import os
from pathlib import Path
import threading
import uuid
import counter
from notifications import hue_off

class BusyError(RuntimeError):
    pass

class CheckService:
    def __init__(self, data, zone):
        self.data = Path(data)
        self.zone = zone
        self.data.mkdir(parents=True, exist_ok=True)
        self.mutex = threading.Lock()
        db = self.connect()
        db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, created TEXT, source TEXT, local_date TEXT,
            coop_ids TEXT, status TEXT, progress TEXT, result TEXT, error TEXT)""")
        # In-flight work cannot survive a process restart; never silently mark it successful.
        db.execute("UPDATE jobs SET status='interrupted',progress='Interrupted by restart',error='Service restarted before completion' WHERE status IN ('queued','running')")
        db.commit()
        db.close()

    def connect(self):
        return counter.connect(self.data)

    def update(self, job_id, **fields):
        allowed = {"status","progress","result","error"}
        if not fields or not fields.keys() <= allowed:
            raise ValueError("Invalid job update")
        db = self.connect()
        try:
            db.execute("UPDATE jobs SET "+",".join(f"{k}=?" for k in fields)+" WHERE id=?",
                       (*fields.values(),job_id))
            db.commit()
        finally:
            db.close()

    def jobs(self, limit=20):
        db = self.connect()
        try:
            rows=db.execute("SELECT id,created,source,local_date,coop_ids,status,progress,result,error FROM jobs ORDER BY created DESC LIMIT ?",(limit,)).fetchall()
            return [dict(zip(("job_id","created","source","local_date","coop_ids","status","progress","result","error"),
                (r[0],r[1],r[2],r[3],json.loads(r[4]),r[5],r[6],json.loads(r[7]) if r[7] else None,r[8]))) for r in rows]
        finally:
            db.close()

    def get(self, job_id):
        db=self.connect()
        try:
            row=db.execute("SELECT id,created,source,local_date,coop_ids,status,progress,result,error FROM jobs WHERE id=?",(job_id,)).fetchone()
            if not row:return None
            return dict(zip(("job_id","created","source","local_date","coop_ids","status","progress","result","error"),
                (row[0],row[1],row[2],row[3],json.loads(row[4]),row[5],row[6],json.loads(row[7]) if row[7] else None,row[8])))
        finally:db.close()

    def results(self):
        db=self.connect()
        try:
            return [{"id":r[0],"created":r[1],"status":r[2],"result":json.loads(r[3])}
                for r in db.execute("SELECT id,created,status,result FROM runs ORDER BY id DESC LIMIT 20")]
        finally:db.close()

    def scheduled_done(self, date):
        db=self.connect()
        try:
            return bool(db.execute("SELECT 1 FROM jobs WHERE local_date=? AND source='scheduled'",(date,)).fetchone()
                or db.execute("SELECT 1 FROM runs WHERE local_date=? AND scheduled=1",(date,)).fetchone())
        finally:db.close()

    def submit(self, coop_ids=None, source="manual"):
        valid=[c["id"] for c in counter.load_coops()]
        if coop_ids is None:coop_ids=valid
        if not isinstance(coop_ids,list) or not coop_ids or any(type(i) is not int or i not in valid for i in coop_ids) or len(set(coop_ids))!=len(coop_ids):
            raise ValueError("coop_ids must be a nonempty list of distinct configured coop IDs")
        if not self.mutex.acquire(False):raise BusyError("A check is already running")
        lock=None
        try:
            lock=(self.data/"counter.lock").open("w")
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise BusyError("Another chicken check is running") from None
            now=dt.datetime.now(self.zone)
            job_id=str(uuid.uuid4())
            db=self.connect()
            try:
                db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)",
                    (job_id,now.isoformat(),source,now.date().isoformat(),json.dumps(coop_ids),"queued","Queued",None,None))
                db.commit()
            finally:db.close()
            threading.Thread(target=self.worker,args=(job_id,coop_ids,source,lock),daemon=True).start()
            return self.get(job_id)
        except Exception:
            if lock:lock.close()
            self.mutex.release()
            raise

    def worker(self, job_id, coop_ids, source, lock):
        db=None
        try:
            self.update(job_id,status="running",progress="Starting check")
            db=self.connect()
            result=counter.run(self.data,db,self.zone,scheduled=source=="scheduled",coop_ids=coop_ids,
                progress=lambda stage:self.update(job_id,progress=stage))
            self.update(job_id,status="completed",progress="Complete",result=json.dumps(result))
            cutoff=(dt.datetime.now(self.zone)-dt.timedelta(days=int(os.environ.get("RETENTION_DAYS","30")))).isoformat()
            db.execute("DELETE FROM jobs WHERE created < ? AND id != ?",(cutoff,job_id));db.commit()
        except Exception as exc:
            logging.getLogger("service").exception("Job failed")
            self.update(job_id,status="failed",progress="Failed",
                error=str(exc) if isinstance(exc,RuntimeError) else "Check failed; see container logs")
        finally:
            if db:db.close()
            lock.close()
            self.mutex.release()

    def light_off(self):
        if not self.mutex.acquire(False):raise BusyError("Wait for the running check to finish")
        try:return hue_off()
        finally:self.mutex.release()
