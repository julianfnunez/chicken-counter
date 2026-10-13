import importlib
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
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import web

class WebTests(unittest.TestCase):
    def test_endpoints_and_images(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(web,"DATA",Path(tmp)), patch.dict(os.environ,{"COOP_COUNT":"2","COOP_1_EXPECTED_CHICKENS":"3","COOP_2_EXPECTED_CHICKENS":"1"}):
            db=web.counter.connect(web.DATA);db.close()
            server=web.ThreadingHTTPServer(("127.0.0.1",0),web.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f"http://127.0.0.1:{server.server_port}"
            try:
                with urllib.request.urlopen(base+"/api/status") as r:
                    data=json.load(r)
                self.assertEqual(len(data["coops"]),2)
                self.assertNotIn("url",data["coops"][0])
                req=urllib.request.Request(base+"/api/check",b'{"coop":null}',{"Content-Type":"application/json"})
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(req)
                self.assertEqual(error.exception.code,403)
                req.add_header("X-Check-Token",web.TOKEN)
                with patch.object(web,"start",return_value=True) as start:
                    with urllib.request.urlopen(req) as r:self.assertEqual(r.status,202)
                    start.assert_called_once_with(None)
                with patch.object(web,"start",return_value=False):
                    with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(req)
                    self.assertEqual(error.exception.code,409)
                off=urllib.request.Request(base+"/api/hue/off",b"",{"X-Check-Token":web.TOKEN})
                with patch.object(web.counter,"hue_off",return_value="off_requested") as hue:
                    with urllib.request.urlopen(off) as r:self.assertEqual(json.load(r)["hue"],"off_requested")
                    hue.assert_called_once()
                with patch.object(web.counter,"hue_off",side_effect=RuntimeError("Hue Bridge request failed")):
                    with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(off)
                    self.assertEqual(error.exception.code,502)
                with urllib.request.urlopen(base+"/") as r:self.assertIn(b"Latest results",r.read())
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(base+"/images/run-x/coop-1/../../counter.py")
            finally:
                server.shutdown();server.server_close();thread.join()

    def test_per_run_lock_and_image_association(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(web,"DATA",Path(tmp)):
            def fake(data,db,zone,scheduled=False,coop_id=None):
                folder=data/"run-test";folder.mkdir()
                result={"status":"check_needed","coops":[]}
                db.execute("INSERT INTO runs (created,local_date,scheduled,status,result) VALUES (?,?,?,?,?)",
                           ("now","today",int(scheduled),"check_needed",json.dumps(result)));db.commit()
                return result
            with patch.object(web.counter,"run",side_effect=fake):
                result=web.perform()
            self.assertEqual(result["image_folder"],"run-test")
            self.assertEqual(web.history()[0]["result"]["image_folder"],"run-test")
            # Lock was released when run completed.
            with (web.DATA/"counter.lock").open("w") as lock:
                web.fcntl.flock(lock,web.fcntl.LOCK_EX|web.fcntl.LOCK_NB)
                with self.assertRaises(RuntimeError):web.perform()

if __name__=="__main__":unittest.main()
