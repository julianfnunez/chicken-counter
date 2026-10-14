"""FastAPI REST interface and dashboard."""
from contextlib import asynccontextmanager
import datetime as dt
import logging
import os
from pathlib import Path
import secrets
import threading
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Depends, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt
import uvicorn

from config import load_coops
from service import CheckService, BusyError
from scheduler import run_scheduler

class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    coop_ids: list[StrictInt] | None = Field(default=None, min_length=1)

class CheckJob(BaseModel):
    job_id: str
    created: str
    source: str
    local_date: str
    coop_ids: list[int]
    status: Literal["queued","running","completed","failed","interrupted"]
    progress: str
    result: dict | None = None
    error: str | None = None

class LightResult(BaseModel):
    hue: str

def create_app(data=None, zone=None, schedule=True):
    data=Path(data or os.environ.get("DATA_DIR","/data"))
    zone=zone or ZoneInfo(os.environ.get("TZ","America/New_York"))

    @asynccontextmanager
    async def lifespan(app):
        load_coops()
        dt.time(*map(int,os.environ.get("CHECK_TIME","22:00").split(":")))
        app.state.service=CheckService(data,zone)
        app.state.token=secrets.token_urlsafe(32)
        stop=threading.Event()
        thread=None
        if schedule:
            thread=threading.Thread(target=run_scheduler,args=(app.state.service,stop),daemon=True)
            thread.start()
        yield
        stop.set()
        if thread:thread.join(timeout=2)

    app=FastAPI(title="Chicken Counter API",version="1.0",lifespan=lifespan)

    @app.middleware("http")
    async def response_headers(request, call_next):
        response=await call_next(request)
        response.headers["Cache-Control"]="no-store"
        response.headers["X-Content-Type-Options"]="nosniff"
        return response

    @app.exception_handler(BusyError)
    async def busy_error(request, exc):
        return JSONResponse(status_code=409,content={"error":str(exc)})

    def authorize(request: Request, x_check_token: str | None = Header(default=None)):
        if x_check_token != request.app.state.token:
            from fastapi import HTTPException
            raise HTTPException(403,detail="Refresh the dashboard and try again")

    @app.get("/",include_in_schema=False)
    def dashboard():
        return FileResponse(Path(__file__).parent/"static"/"index.html",media_type="text/html")

    @app.get("/api/status")
    def status(request: Request):
        jobs=request.app.state.service.jobs()
        active=next((j for j in jobs if j["status"] in ("queued","running")),None)
        return {"token":request.app.state.token,"running":bool(active),"active_job":active,
            "error":jobs[0]["error"] if jobs else None,
            "coops":[{"id":c["id"],"name":c["name"],"expected":c["expected"]} for c in load_coops()],
            "time":os.environ.get("CHECK_TIME","22:00"),"timezone":str(zone)}

    @app.get("/api/results")
    def results(request: Request):
        return request.app.state.service.results()

    @app.get("/api/checks",response_model=list[CheckJob])
    def checks(request: Request):
        return request.app.state.service.jobs()

    @app.get("/api/checks/latest",response_model=CheckJob | None)
    def latest(request: Request):
        jobs=request.app.state.service.jobs(1)
        return jobs[0] if jobs else None

    @app.get("/api/checks/{job_id}",response_model=CheckJob)
    def check_job(job_id: str,request: Request):
        job=request.app.state.service.get(job_id)
        if job is None:return JSONResponse(status_code=404,content={"error":"Job not found"})
        return job

    @app.get("/images/{folder}/{coop}/{filename}",include_in_schema=False)
    def image(folder: str,coop: str,filename: str):
        if not folder.startswith("run-") or not coop.startswith("coop-") or not filename.startswith("frame-") or not filename.endswith(".jpg"):
            return JSONResponse(status_code=404,content={"error":"Image not found"})
        path=(data/folder/coop/filename).resolve()
        if not path.is_relative_to(data.resolve()) or not path.is_file():
            return JSONResponse(status_code=404,content={"error":"Image not found"})
        return FileResponse(path,media_type="image/jpeg")

    @app.post("/api/checks",status_code=202,response_model=CheckJob,dependencies=[Depends(authorize)])
    def submit(body: CheckRequest,request: Request):
        try:return request.app.state.service.submit(body.coop_ids)
        except ValueError as exc:return JSONResponse(status_code=400,content={"error":str(exc)})

    @app.post("/api/light/off",response_model=LightResult,dependencies=[Depends(authorize)])
    def light_off(request: Request):
        try:return {"hue":request.app.state.service.light_off()}
        except BusyError:raise
        except RuntimeError as exc:return JSONResponse(status_code=502,content={"error":str(exc)})

    return app

app=create_app()

if __name__=="__main__":
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    # Single process: the scheduler and active-job mutex belong to this service.
    uvicorn.run(app,host="0.0.0.0",port=int(os.environ.get("WEB_PORT","8080")),workers=1)
