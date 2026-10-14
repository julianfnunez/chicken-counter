import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import web
import service

class WebTests(unittest.TestCase):
    def test_rest_lifecycle(self):
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{"COOP_COUNT":"2","COOP_1_EXPECTED_CHICKENS":"3","COOP_2_EXPECTED_CHICKENS":"1"}):
            app=web.create_app(tmp,ZoneInfo("America/New_York"),schedule=False)
            gate=threading.Event(); entered=threading.Event()
            def fake(*args,**kwargs):
                kwargs["progress"]("Counting test")
                entered.set();gate.wait(5)
                return {"status":"check_needed","coops":[]}
            with TestClient(app) as client:
                svc=app.state.service
                data=client.get("/api/status").json()
                self.assertNotIn("url",data["coops"][0])
                self.assertEqual(client.post("/api/checks",json={"coop_ids":[1,2]}).status_code,403)
                headers={"X-Check-Token":data["token"]}
                self.assertEqual(client.post("/api/checks",headers=headers,json={"coop_ids":["1"]}).status_code,422)
                self.assertEqual(client.post("/api/checks",headers=headers,json={"coop_ids":[True]}).status_code,422)
                self.assertEqual(client.post("/api/checks",headers=headers,json={"coop_ids":[99]}).status_code,400)
                with patch.object(service.counter,"run",side_effect=fake):
                    response=client.post("/api/checks",headers=headers,json={"coop_ids":[1,2]})
                    self.assertEqual(response.status_code,202);job=response.json()
                    self.assertTrue(entered.wait(2))
                    self.assertEqual(client.get("/api/checks/"+job["job_id"]).json()["progress"],"Counting test")
                    self.assertEqual(client.post("/api/checks",headers=headers,json={}).status_code,409)
                    self.assertEqual(client.post("/api/light/off",headers=headers).status_code,409)
                    gate.set()
                    self.assertTrue(svc.mutex.acquire(timeout=2));svc.mutex.release()
                self.assertEqual(svc.get(job["job_id"])["status"],"completed")
                with patch.object(service,"hue_off",return_value="off_requested") as hue:
                    self.assertEqual(client.post("/api/light/off",headers=headers).json()["hue"],"off_requested")
                    hue.assert_called_once()
                image_dir=Path(tmp)/"run-test"/"coop-1"
                image_dir.mkdir(parents=True)
                (image_dir/"frame-01.jpg").write_bytes(b"test-image")
                self.assertEqual(client.get("/images/run-test/coop-1/frame-01.jpg").content,b"test-image")
                self.assertEqual(client.get("/images/run-test/coop-1/not-image.txt").status_code,404)
                self.assertIn("Latest results",client.get("/").text)
                self.assertEqual(client.get("/docs").status_code,200)
                schema=client.get("/openapi.json").json()
                self.assertIn("/api/checks",schema["paths"])
                self.assertEqual(client.get("/api/checks/missing").status_code,404)

    def test_validation_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{"COOP_COUNT":"1","COOP_1_EXPECTED_CHICKENS":"3"}):
            svc=service.CheckService(tmp,ZoneInfo("America/New_York"))
            for ids in ([],[99],[1,1],[True],"1"):
                with self.assertRaises(ValueError):svc.submit(ids)
            db=svc.connect()
            db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)",
                ("test","today","scheduled","today","[1]","running","Counting",None,None));db.commit();db.close()
            svc=service.CheckService(tmp,ZoneInfo("America/New_York"))
            self.assertEqual(svc.get("test")["status"],"interrupted")
            self.assertTrue(svc.scheduled_done("today"))

    def test_cross_process_lock(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{"COOP_COUNT":"1","COOP_1_EXPECTED_CHICKENS":"3"}):
            svc=service.CheckService(tmp,ZoneInfo("America/New_York"))
            with (Path(tmp)/"counter.lock").open("w") as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaises(service.BusyError):svc.submit()
            self.assertFalse(svc.mutex.locked())

if __name__=="__main__":unittest.main()
