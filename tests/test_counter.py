import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import counter
import ai
import notifications

def frames(count=3, clear=True, n=4):
    return [{"count":count,"clear":clear,"locations":["bird"]*count,"note":""} for _ in range(n)]

class Tests(unittest.TestCase):
    def test_agreement(self):
        self.assertEqual(counter.classify(frames(),3),"observed_expected")
        for values in [frames(2),frames(4),frames(clear=False),frames(n=1),frames()[:3]+frames(2,n=1)]:
            self.assertEqual(counter.classify(values,3),"check_needed")

    def test_response_validation(self):
        response = {"status":"completed","output":[{"content":[{"type":"output_text","text":json.dumps({"frames":frames()})}]}]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"test.jpg"
            path.write_bytes(b"image")
            with patch.object(ai,"api_request",return_value=response) as api:
                self.assertEqual(len(counter.analyze([path]*4)["frames"]),4)
                payload = api.call_args.args[0]
                self.assertFalse(payload["store"])
                self.assertNotIn("expected",payload["input"][0]["content"][0]["text"])
            with patch.object(ai,"api_request",return_value=response):
                with self.assertRaises(RuntimeError):
                    counter.analyze([path])

    def test_error_persisted_and_notified(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            db = counter.connect(data)
            with patch.object(counter,"capture",side_effect=RuntimeError("RTSP capture timed out")), patch.object(counter,"notify") as notify:
                result = counter.run(data,db,ZoneInfo("America/New_York"),scheduled=True)
            self.assertEqual(result["status"],"error")
            notify.assert_called_once()
            self.assertEqual(db.execute("SELECT scheduled,status FROM runs").fetchone(),(1,"error"))
            self.assertEqual(len(list(data.glob("run-*/result.json"))),1)

    def test_success_and_notification_failure_persist(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            db = counter.connect(data)
            with patch.object(counter,"capture",return_value=[Path("a.jpg")]*4), patch.object(counter,"analyze",return_value={"frames":frames(n=1),"usage":{},"model":"test"}), patch.object(counter,"notify",side_effect=RuntimeError("Notification delivery failed")):
                result = counter.run(data,db,ZoneInfo("America/New_York"))
            self.assertEqual(result["status"],"observed_expected")
            self.assertEqual(result["notification"],"Notification delivery failed")
            self.assertEqual(db.execute("SELECT count(*) FROM runs").fetchone()[0],1)


    def test_two_coops_failure_isolation(self):
        env = {"COOP_COUNT":"2","COOP_1_EXPECTED_CHICKENS":"3",
               "COOP_2_EXPECTED_CHICKENS":"1","COOP_1_RTSP_URL":"rtsp://first",
               "COOP_2_RTSP_URL":"rtsp://second"}
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,env):
            data = Path(temp)
            db = counter.connect(data)
            with patch.object(counter,"capture",side_effect=[RuntimeError("RTSP capture timed out"),[Path("b.jpg")]*4]), patch.object(counter,"analyze",return_value={"frames":frames(1,n=1),"usage":{},"model":"test"}) as analyze, patch.object(counter,"notify") as notify:
                result = counter.run(data,db,ZoneInfo("America/New_York"))
            self.assertEqual(result["status"],"error")
            self.assertEqual(result["coops"][1]["status"],"observed_expected")
            self.assertEqual(analyze.call_count,4)
            self.assertTrue(all(len(call.args[0]) == 1 for call in analyze.call_args_list))
            notify.assert_called_once()
            self.assertEqual(len(list(data.glob("run-*/coop-*/result.json"))),2)

    def test_mismatches_not_hidden_by_totals(self):
        self.assertEqual(counter.summary_status([
            {"status":"check_needed"},{"status":"check_needed"}]),"check_needed")

    def test_invalid_configuration(self):
        with patch.dict(os.environ,{"COOP_COUNT":"2","COOP_1_EXPECTED_CHICKENS":"3","COOP_2_EXPECTED_CHICKENS":"-1"}):
            with self.assertRaises(ValueError):
                counter.load_coops()


    def test_hue_disabled_and_success_no_network(self):
        with patch.dict(os.environ, {"HUE_ENABLED":"false"}), patch.object(notifications.urllib.request,"urlopen") as request:
            self.assertEqual(counter.hue_alert({"status":"error"}),"disabled")
            request.assert_not_called()
        with patch.dict(os.environ, {"HUE_ENABLED":"true"}), patch.object(notifications.urllib.request,"urlopen") as request:
            self.assertEqual(counter.hue_alert({"status":"observed_expected"}),"unchanged")
            request.assert_not_called()

    def test_hue_request_and_http200_error(self):
        import io
        env = {"HUE_ENABLED":"true","HUE_BRIDGE_URL":"http://192.168.1.60",
               "HUE_API_KEY":"test-key","HUE_LIGHT_ID":"2"}
        reply = [{"success":{f"/lights/2/state/{k}":v}}
                 for k,v in {"on":True,"hue":0,"sat":254,"bri":254,"alert":"lselect"}.items()]
        with patch.dict(os.environ,env), patch.object(notifications.urllib.request,"urlopen",return_value=io.BytesIO(json.dumps(reply).encode())) as request:
            self.assertEqual(counter.hue_alert({"status":"check_needed"}),"red_requested")
            req = request.call_args.args[0]
            self.assertEqual(req.get_method(),"PUT")
            self.assertEqual(json.loads(req.data)["hue"],0)
            self.assertEqual(json.loads(req.data)["alert"],"lselect")
            request.assert_called_once()
        with patch.dict(os.environ,env), patch.object(notifications.urllib.request,"urlopen",return_value=io.BytesIO(b'[{"error":{"type":1}}]')):
            with self.assertRaises(RuntimeError):
                counter.hue_alert({"status":"error"})

    def test_hue_failure_does_not_block_ntfy(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            db = counter.connect(data)
            with patch.object(counter,"capture",side_effect=RuntimeError("RTSP capture timed out")), patch.object(counter,"hue_alert",side_effect=RuntimeError("Hue Bridge request failed")), patch.object(counter,"notify") as notify:
                result = counter.run(data,db,ZoneInfo("America/New_York"))
            notify.assert_called_once()
            self.assertEqual(result["hue"],"Hue Bridge request failed")

    def test_hue_off_one_request(self):
        import io
        env = {"HUE_BRIDGE_URL":"http://192.168.1.60","HUE_API_KEY":"test-key","HUE_LIGHT_ID":"2"}
        reply = [{"success":{"/lights/2/state/on":False}},
                 {"success":{"/lights/2/state/alert":"none"}}]
        with patch.dict(os.environ,env), patch.object(notifications.urllib.request,"urlopen",return_value=io.BytesIO(json.dumps(reply).encode())) as request:
            self.assertEqual(counter.hue_off(),"off_requested")
            request.assert_called_once()
            self.assertEqual(json.loads(request.call_args.args[0].data),{"on":False,"alert":"none"})

if __name__ == "__main__":
    unittest.main()
