import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest import TestCase, mock
from uuid import uuid4

from fastapi.testclient import TestClient
from lablink import main
from lablink.auth import decode, encode
from lablink.scheduler import IST, plan
from lablink.storage import SQLiteStore
from lablink.advisor import match_project

NOW = datetime(2030, 3, 4, 8, tzinfo=IST)  # Monday
HEAD = {"X-LabLink":"1"}

def req(**changes):
    row = dict(id=str(uuid4()), student_name="Demo Student", registration_id="DEMO-01", project="Audio filter testing", unit="EE-01",
               skills=["waveforms"], earliest="2030-03-04", deadline="2030-03-06",
               from_hour=10, until_hour=12, preferred=10, hours=2, flexible=True)
    return dict(row, **changes)

def pending(**changes):
    return req(**dict(dict(created=NOW.isoformat(),status="pending",owner="a"),**changes))

class SchedulerTests(TestCase):
    def test_equivalent_and_deadline(self):
        first = pending(owner="b",registration_id="DEMO-B",deadline="2030-03-04",flexible=False)
        second = pending()
        allocations = plan([second,first], NOW)
        self.assertEqual(allocations[first["id"]]["slot"]["unit"],"EE-01")
        self.assertEqual(allocations[second["id"]]["slot"]["unit"],"PH-02")

    def test_hard_skills_and_student_overlap(self):
        r = pending(unit="PH-02", skills=["logic analysis"], deadline="2030-03-04")
        a = pending(unit="EE-01",owner="a",status="approved",assigned=dict(unit="EE-01",day="2030-03-04",hour=10))
        self.assertIsNone(plan([a,r], NOW)[r["id"]]["slot"])
        a["owner"]="b";a["assigned"]["unit"]="PH-02"
        self.assertIsNone(plan([a,r], NOW)[r["id"]]["slot"])

    def test_window_weekend_and_past(self):
        for r,now in [(pending(earliest="2030-03-09",deadline="2030-03-10"),NOW),
                      (pending(deadline="2030-03-04"),NOW.replace(hour=11))]:
            self.assertIsNone(plan([r],now)[r["id"]]["slot"])

    def test_prior_use_and_waiting_affect_priority(self):
        a=pending(owner="a",flexible=False);b=pending(owner="b",flexible=False)
        past=pending(owner="a",status="approved",assigned=dict(unit="EE-01", day="2030-03-01",hour=10))
        self.assertEqual(plan([a,b,past],NOW)[b["id"]]["slot"]["day"],"2030-03-04")
        a["created"]=(NOW-timedelta(days=2)).isoformat()
        self.assertEqual(plan([a,b,past],NOW)[a["id"]]["slot"]["day"],"2030-03-04")

    def test_lower_utilisation_breaks_tie(self):
        busy=pending(owner="b",hours=1,status="approved",assigned=dict(unit="EE-01",day="2030-03-04",hour=9))
        target=pending()
        self.assertEqual(plan([busy,target],NOW)[target["id"]]["slot"]["unit"],"PH-02")

class ApiTests(TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        backend=SQLiteStore(str(Path(tmp.name)/"test.db"))
        for patch in [mock.patch.object(main,"store",return_value=backend),
                      mock.patch.object(main,"campus_now",return_value=NOW),
                      mock.patch.dict(os.environ,{"VERTEX_MODEL":""})]:
            patch.start();self.addCleanup(patch.stop)
        self.c=TestClient(main.app,headers=HEAD);self.addCleanup(self.c.close)
        self.c.post("/api/demo",json={})

    def login(self,role="student",owner="u1",dept="Computing"):
        import time
        data=dict(owner=owner,role=role,dept=dept,demo=False,space="campus-main",exp=int(time.time())+60,purpose="pass")
        return self.c.post("/api/access",json={"token":encode(data,main.KEY)})

    def state(self):
        response=self.c.get("/api/state");self.assertEqual(response.status_code,200);return response.json()

    def decision(self,row,act):
        return self.c.post("/api/requests/"+row["id"]+"/decision",json={"action":act,**((row["proposal"] or {}).get("slot") or {})})

    def test_student_privacy_isolation_and_cross_role(self):
        self.assertEqual(len(self.state()["rows"]),1)
        row=self.state()["rows"][0];self.assertEqual(self.decision(row,"approve").status_code,403)
        self.c.post("/api/demo/role",json={"role":"faculty"});self.assertEqual(len(self.state()["rows"]),2)
        self.assertEqual(self.c.post("/api/requests",json=req()).status_code,403)
        self.c.post("/api/demo",json={});self.assertNotEqual(row["id"],self.state()["rows"][0]["id"])

    def test_approval_metrics_cancel(self):
        row=self.state()["rows"][0]
        self.c.post("/api/demo/role",json={"role":"faculty"})
        self.assertEqual(self.decision(row,"approve").status_code,200)
        self.assertEqual(sum(self.state()["metrics"].values()),2)
        self.c.post("/api/demo/role",json={"role":"student"})
        self.assertEqual(self.decision(row,"cancel").status_code,200)
        self.assertEqual(sum(self.state()["metrics"].values()),0)

    def test_concurrent_approval_commits_once(self):
        row=self.state()["rows"][0]
        self.c.post("/api/demo/role",json={"role":"faculty"})
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(lambda _:self.decision(row,"approve").status_code, range(2)))
        self.assertEqual(sorted(statuses),[200,409])
        self.assertEqual(sum(self.state()["metrics"].values()),2)

    def test_stale_recommendation_is_rejected(self):
        self.login();target=req();self.c.post("/api/requests",json=target);row=self.state()["rows"][0]
        self.login(owner="u2");self.c.post("/api/requests",json=req(deadline="2030-03-04",flexible=False,registration_id="DEMO-B"))
        self.login("faculty","reviewer","Physics")
        self.assertEqual(self.decision(row,"approve").status_code,409)

    def test_departments_and_no_campus_role_switch(self):
        self.login(); self.c.post("/api/requests",json=req())
        self.assertEqual(self.c.post("/api/demo/role",json={"role":"faculty"}).status_code,403)
        row=self.state()["rows"][0]
        self.login("faculty","reviewer","Computing")
        self.assertEqual(self.state()["rows"],[])
        self.assertEqual(self.decision(row,"approve").status_code,403)
        self.login("faculty","reviewer","Electronics")
        self.assertEqual(self.decision(row,"decline").json()["status"],"declined")

    def test_window_capabilities_and_duplicate_requests(self):
        item=req()
        for changes in (dict(skills=["cuda"]),dict(deadline="2030-03-03"),dict(preferred=11),dict(hours=0)):
            self.assertEqual(self.c.post("/api/requests",json=dict(item,**changes)).status_code,422)
        for _ in range(2):
            self.assertEqual(self.c.post("/api/requests",json=item).status_code,200)
        self.assertEqual(len(self.state()["rows"]),2)
        self.assertEqual(self.c.post("/api/requests",json=dict(item,project="Another title")).status_code,409)

    def test_csrf_session_expiry_and_private_content(self):
        client=TestClient(main.app)
        self.assertEqual(client.get("/api/state").status_code,401)
        self.assertEqual(client.post("/api/demo").status_code,403)
        self.assertEqual(self.c.post("/api/access",json={"token":"invalid_access_pass"}).status_code,401)
        self.assertIsNone(decode(encode({"exp":0,"purpose":"pass"},main.KEY),main.KEY,"pass"))
        self.assertEqual(self.c.get("/api/state").headers["Cache-Control"],"no-store")
        self.assertEqual(self.c.post("/api/logout").status_code,200)
        self.assertEqual(self.c.get("/api/state").status_code,401)
        client.close()

    def test_catalogue_advisor_and_budget(self):
        r=self.c.post("/api/advice",json={"project":"I need a CUDA GPU workstation"})
        self.assertEqual(r.json()["matches"][0]["id"],"CS-03")
        self.assertIn("fallback",r.json()["mode"])
        self.assertEqual(match_project("xyzabcdef")["matches"],[])
        for _ in range(19):self.c.post("/api/advice",json={"project":"waveforms"})
        self.assertEqual(self.c.post("/api/advice",json={"project":"waveforms"}).status_code,429)


    def test_inventory_shared_catalogue_booking_and_occupancy_lifecycle(self):
        self.login("faculty", "lab-coordinator", "Computing")
        item = dict(id="CS-08", revision=0, name="FPGA bench", department="Computing",
                    room="Digital Lab D12", group="Development kits", skills=["VHDL"],
                    description="Prototype digital logic with an FPGA.", status="active")
        def save(**changes):
            return self.c.post("/api/inventory", json={**item, **changes})
        self.assertEqual(save().status_code, 200)
        self.assertEqual(save().status_code, 409)
        self.login()
        self.assertEqual(save(revision=1).status_code, 403)
        self.assertIn("CS-08", self.state()["openings"])
        advice = self.c.post("/api/advice", json={"project":"Prototype an FPGA using VHDL"})
        self.assertEqual(advice.json()["matches"][0]["id"], "CS-08")
        booking = req(unit="CS-08", skills=["vhdl"], flexible=False)
        self.assertEqual(self.c.post("/api/requests", json=booking).status_code, 200)
        self.login("faculty", "coordinator", "Computing")
        row = self.state()["rows"][0]
        self.assertEqual(self.state()["occupancy"], [])
        self.assertEqual(self.decision(row, "approve").status_code, 200)
        self.assertEqual(save(revision=1, status="maintenance").status_code, 409)
        faculty_slots = self.state()["occupancy"]
        self.login(owner="other-student")
        self.assertEqual(self.state()["rows"], [])
        self.assertEqual(self.state()["occupancy"], faculty_slots)
        self.assertEqual(faculty_slots, [dict(unit="CS-08",day="2030-03-04",hour=10,hours=2)])
        self.login()
        self.assertEqual(self.decision(self.state()["rows"][0], "cancel").status_code, 200)
        self.assertEqual(self.state()["occupancy"], [])
        self.login("faculty", "coordinator", "Computing")
        self.assertEqual(save(revision=1, status="maintenance").status_code, 200)
        self.assertEqual(save(revision=1, name="Stale edit").status_code, 409)
        self.assertEqual(save(revision=2, status="retired").status_code, 200)
        self.login()
        self.assertNotIn("CS-08", self.state()["openings"])
        self.assertEqual(self.c.post("/api/requests", json=req(unit="CS-08",skills=["vhdl"])).status_code, 422)
        self.assertEqual(self.c.post("/api/advice",json={"project":"FPGA VHDL"}).json()["matches"], [])
        self.c.post("/api/demo", json={})
        self.assertNotIn("CS-08", {u["id"] for u in self.state()["catalog"]})

    def test_existing_inventory_and_department_ownership(self):
        self.login("faculty","coordinator","Computing")
        foreign = next(u for u in self.state()["catalog"] if u["id"]=="EE-01")
        edit = dict(foreign, revision=1, status="maintenance")
        for department in ("Computing","Electronics"):
            self.assertEqual(self.c.post("/api/inventory", json=dict(edit,department=department)).status_code,403)
        self.login("faculty","electronics-coordinator","Electronics")
        self.assertEqual(self.c.post("/api/inventory",json=edit).status_code,200)
        self.assertNotIn("EE-01", self.state()["openings"])

    def test_pending_booking_gets_available_substitute_after_maintenance(self):
        self.login()
        self.c.post("/api/requests",json=req(flexible=True))
        self.login("faculty","electronics-coordinator","Electronics")
        target = next(u for u in self.state()["catalog"] if u["id"]=="EE-01")
        self.assertEqual(self.c.post("/api/inventory",json=dict(target,status="maintenance",revision=1)).status_code,200)
        self.login()
        self.assertEqual(self.state()["rows"][0]["proposal"]["slot"]["unit"],"PH-02")

    def test_numbered_empty_lab_and_weekly_timetable_permissions(self):
        data = dict(name="Network Lab",number="C401",department="Computing",access="Step-free access")
        self.login()
        self.assertEqual(self.c.post("/api/labs",json=data).status_code,403)
        self.login("faculty","coordinator","Computing")
        lab = self.c.post("/api/labs",json=data).json()
        self.assertEqual(lab["number"],"C401")
        self.assertEqual(self.c.post("/api/labs",json=data).status_code,409)
        self.assertEqual(len(self.state()["labs"]),7)
        slot = dict(lab_id=lab["id"],weekday=0,start="10:30",end="12:00",
                    subject="Networks",department="CSE",section="B")
        entry = self.c.post("/api/timetable",json=slot).json()
        path = "/api/timetable/"+entry["id"]
        self.assertEqual(self.c.post("/api/timetable",json=dict(slot,section="A")).status_code,409)
        second = next(l for l in self.state()["labs"] if l["number"]=="C301")
        self.assertEqual(self.c.post("/api/timetable",json=dict(slot,lab_id=second["id"])).status_code,409)
        self.login()
        self.assertIn(entry,self.state()["timetable"])
        self.assertEqual(self.c.post(path+"/remove/1",json={}).status_code,403)
        self.login("faculty","other","Physics")
        self.assertEqual(self.c.post(path+"/edit/1",json=slot).status_code,403)
        self.login("faculty","coordinator","Computing")
        self.assertEqual(self.c.post(path+"/edit/1",json=dict(slot,start="09:30")).status_code,200)
        self.assertEqual(self.c.post(path+"/remove/1",json={}).status_code,409)
        self.assertEqual(self.c.post(path+"/remove/2",json={}).status_code,200)

    def test_partial_hour_class_blocks_bookings_and_respects_confirmations(self):
        self.login("faculty","coordinator","Electronics")
        lab = next(l for l in self.state()["labs"] if l["number"]=="E204")
        slot = dict(lab_id=lab["id"],weekday=0,start="09:30",end="11:30",
                    subject="Signal analysis",department="Electronics",section="A")
        self.assertEqual(self.c.post("/api/timetable",json=slot).status_code,200)
        self.assertEqual(self.state()["openings"]["EE-01"]["hour"],12)
        self.login()
        booking=req(hours=1,deadline="2030-03-04",until_hour=13,flexible=False)
        self.assertEqual(self.c.post("/api/requests",json=booking).status_code,200)
        row=self.state()["rows"][0]
        self.assertEqual(row["proposal"]["slot"]["hour"],12)
        self.login("faculty","coordinator","Electronics")
        self.assertEqual(self.decision(row,"approve").status_code,200)
        self.assertEqual(self.c.post("/api/timetable",json=dict(slot,start="12:30",end="13:00")).status_code,409)
        self.assertEqual(self.c.post("/api/timetable",json=dict(slot,start="13:00",end="14:00")).status_code,200)

    def test_request_identity_privacy_and_faculty_sort(self):
        self.login()
        for key in ("student_name","registration_id"):
            self.assertEqual(self.c.post("/api/requests",json=req(**{key:" "})).status_code,422)
        for title in ["First project","Second project","Third project"]:
            self.assertEqual(self.c.post("/api/requests",json=req(project=title,flexible=False)).status_code,200)
        self.login("faculty","coordinator","Electronics")
        middle=self.state()["rows"][1]
        self.assertEqual(middle["registration_id"],"DEMO-01")
        self.assertEqual(self.decision(middle,"decline").status_code,200)
        rows=self.state()["rows"]
        self.assertEqual([r["status"] for r in rows],["pending","pending","declined"])
        self.assertEqual(rows[-1]["id"],middle["id"])
        self.login(owner="another-student")
        snapshot=self.state()
        self.assertEqual(snapshot["rows"],[])
        self.assertNotIn("DEMO-01",str(snapshot))

    def exact(self, cells, members=("A01",), day="2030-03-04"):
        return dict(id=str(uuid4()),day=day,project="Signal timing",
                    members=[dict(name="Student "+m,registration_id=m) for m in members],
                    slots=[dict(unit=uid,hour=h) for uid,h in cells])

    def test_exact_group_split_booking_approval_and_calendar(self):
        self.login("faculty","reviewer","Electronics")
        template=next(u for u in self.state()["catalog"] if u["id"]=="EE-01")
        self.assertEqual(self.c.post("/api/inventory",json=dict(template,id="EE-07",status="active",revision=0)).status_code,200)
        self.login(owner="A01")
        data=self.exact([("EE-01",9),("EE-07",9),("EE-01",15)],("A01","B02","C03"))
        for _ in range(2):
            self.assertEqual(self.c.post("/api/slot-requests",json=data).status_code,200)
        row=self.state()["rows"][0]
        self.assertEqual(len(self.state()["busy"]),3)
        self.assertTrue(all(s["mine"] and s["pending"] for s in self.state()["busy"]))
        calendar="/api/requests/"+row["id"]+"/calendar"
        self.assertEqual(self.c.get(calendar).status_code,404)
        self.login(owner="B02")
        self.assertFalse(self.state()["rows"][0]["can_cancel"])
        clash=self.exact([("CS-03",15)],("B02",))
        self.assertEqual(self.c.post("/api/slot-requests",json=clash).status_code,409)
        self.login("faculty","reviewer","Electronics")
        self.assertEqual(self.decision(row,"approve").status_code,200)
        self.login(owner="C03")
        self.assertEqual(self.state()["rows"][0]["status"],"approved")
        self.assertEqual(sum(self.state()["metrics"].values()),3)
        events=self.c.get(calendar)
        self.assertEqual(events.status_code,200)
        self.assertEqual(events.text.count("BEGIN:VEVENT"),2)
        self.assertEqual(events.text.count("BEGIN:VALARM"),4)
        self.assertIn("DTSTART:20300304T033000Z",events.text)
        self.login(owner="outsider")
        self.assertEqual(self.state()["rows"],[])
        self.assertEqual(self.c.get(calendar).status_code,404)
        self.login(owner="A01")
        self.assertEqual(self.decision(self.state()["rows"][0],"cancel").status_code,200)
        self.assertEqual(self.state()["busy"],[])
        self.assertEqual(self.c.get(calendar).status_code,404)

    def test_exact_constraints_and_atomic_holds(self):
        self.login(owner="u1")
        for cells,members,expected in [
            ([("EE-01",13)],("A",),409),
            ([("EE-01",9),("EE-01",10),("EE-01",11)],("A",),422),
            ([("EE-01",9),("CS-03",9)],("A",),422),
            ([("EE-01",9),("CS-03",9)],("A","B"),422),
            ([("EE-01",9)],("A","a"),422),
            ([("EE-01",9)],("A","B","C","D"),422)]:
            self.assertEqual(self.c.post("/api/slot-requests",json=self.exact(cells,members)).status_code,expected)
        def send(i):
            data=self.exact([("EE-01",10),("EE-01",11)],("A"+str(i),))
            return self.c.post("/api/slot-requests",json=data).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(send,range(2))),[200,409])
        row=self.state()["rows"][0]
        self.login("faculty","reviewer","Physics")
        self.assertEqual(self.decision(row,"approve").status_code,403)
        self.login("faculty","reviewer","Electronics")
        self.assertEqual(self.decision(row,"approve").status_code,200)
        self.login(owner="u1")
        self.assertEqual(self.c.get("/api/requests/"+row["id"]+"/calendar").text.count("BEGIN:VEVENT"),1)

    def test_class_closes_cells_and_decline_releases_split_hold(self):
        self.login("faculty","reviewer","Electronics")
        lab=next(l for l in self.state()["labs"] if l["number"]=="E204")
        cls=dict(lab_id=lab["id"],weekday=0,start="10:30",end="11:30",subject="Circuits",department="ECE",section="A")
        self.assertEqual(self.c.post("/api/timetable",json=cls).status_code,200)
        self.login()
        self.assertEqual(self.c.post("/api/slot-requests",json=self.exact([("EE-01",11)])).status_code,409)
        self.assertEqual(self.c.post("/api/slot-requests",json=self.exact([("EE-01",9),("EE-01",14)])).status_code,200)
        row=self.state()["rows"][0]
        self.login("faculty","reviewer","Electronics")
        self.assertEqual(self.c.post("/api/timetable",json=dict(cls,start="14:30",end="15:00")).status_code,409)
        self.assertEqual(self.decision(row,"decline").status_code,200)
        self.assertEqual(self.state()["busy"],[])
        self.assertEqual(self.c.post("/api/timetable",json=dict(cls,start="14:30",end="15:00")).status_code,200)

    def test_unreviewed_request_expires_at_first_start(self):
        self.login()
        self.c.post("/api/slot-requests",json=self.exact([("EE-01",9),("EE-01",14)]))
        with mock.patch.object(main,"campus_now",return_value=NOW.replace(hour=9)):
            self.assertEqual(self.state()["rows"][0]["status"],"expired")
            self.assertEqual(self.state()["busy"],[])

    def test_demo_contains_full_week_timetable_across_multiple_labs(self):
        classes = self.state()["timetable"]
        self.assertGreaterEqual(len(classes), 12)
        self.assertEqual({c["weekday"] for c in classes}, {0, 1, 2, 3, 4})
        lab_ids = {c["lab_id"] for c in classes}
        self.assertGreaterEqual(len(lab_ids), 5)

    def test_numbered_empty_lab_and_weekly_timetable_permissions(self):
        data = dict(name="Network Lab",number="C401",department="Computing",access="Step-free access")
        self.login()
        self.assertEqual(self.c.post("/api/labs",json=data).status_code,403)
        self.login("faculty","coordinator","Computing")
        lab = self.c.post("/api/labs",json=data).json()
        self.assertEqual(lab["number"],"C401")
        self.assertEqual(self.c.post("/api/labs",json=data).status_code,409)
        self.assertEqual(len(self.state()["labs"]),7)
        slot = dict(lab_id=lab["id"],weekday=0,start="10:30",end="12:00",
                    subject="Networks",department="CSE",section="B")
        entry = self.c.post("/api/timetable",json=slot).json()
        path = "/api/timetable/"+entry["id"]
        self.assertEqual(self.c.post("/api/timetable",json=dict(slot,section="A")).status_code,409)
        second = next(l for l in self.state()["labs"] if l["number"]=="C301")
        self.assertEqual(self.c.post("/api/timetable",json=dict(slot,lab_id=second["id"])).status_code,409)
        self.login()
        self.assertIn(entry,self.state()["timetable"])
        self.assertEqual(self.c.post(path+"/remove/1",json={}).status_code,403)
        self.login("faculty","other","Physics")
        self.assertEqual(self.c.post(path+"/edit/1",json=slot).status_code,403)
        self.login("faculty","coordinator","Computing")
        self.assertEqual(self.c.post(path+"/edit/1",json=dict(slot,start="09:30")).status_code,200)
        self.assertEqual(self.c.post(path+"/remove/1",json={}).status_code,409)
        self.assertEqual(self.c.post(path+"/remove/2",json={}).status_code,200)

    def test_partial_hour_class_blocks_bookings_and_respects_confirmations(self):
        self.login("faculty","coordinator","Electronics")
        lab = next(l for l in self.state()["labs"] if l["number"]=="E204")
        slot = dict(lab_id=lab["id"],weekday=0,start="09:30",end="11:30",
                    subject="Signal analysis",department="Electronics",section="A")
        self.assertEqual(self.c.post("/api/timetable",json=slot).status_code,200)
        self.assertEqual(self.state()["openings"]["EE-01"]["hour"],12)
        self.login()
        booking=req(hours=1,deadline="2030-03-04",until_hour=13,flexible=False)
        self.assertEqual(self.c.post("/api/requests",json=booking).status_code,200)
        row=self.state()["rows"][0]
        self.assertEqual(row["proposal"]["slot"]["hour"],12)
        self.login("faculty","coordinator","Electronics")
        self.assertEqual(self.decision(row,"approve").status_code,200)
        self.assertEqual(self.c.post("/api/timetable",json=dict(slot,start="12:30",end="13:00")).status_code,409)
        self.assertEqual(self.c.post("/api/timetable",json=dict(slot,start="13:00",end="14:00")).status_code,200)

    def test_request_identity_privacy_and_faculty_sort(self):
        self.login()
        for key in ("student_name","registration_id"):
            self.assertEqual(self.c.post("/api/requests",json=req(**{key:" "})).status_code,422)
        for title in ["First project","Second project","Third project"]:
            self.assertEqual(self.c.post("/api/requests",json=req(project=title,flexible=False)).status_code,200)
        self.login("faculty","coordinator","Electronics")
        middle=self.state()["rows"][1]
        self.assertEqual(middle["registration_id"],"DEMO-01")
        self.assertEqual(self.decision(middle,"decline").status_code,200)
        rows=self.state()["rows"]
        self.assertEqual([r["status"] for r in rows],["pending","pending","declined"])
        self.assertEqual(rows[-1]["id"],middle["id"])
        self.login(owner="another-student")
        snapshot=self.state()
        self.assertEqual(snapshot["rows"],[])
        self.assertNotIn("DEMO-01",str(snapshot))

    def exact(self, cells, members=("A01",), day="2030-03-04"):
        return dict(id=str(uuid4()),day=day,project="Signal timing",
                    members=[dict(name="Student "+m,registration_id=m) for m in members],
                    slots=[dict(unit=uid,hour=h) for uid,h in cells])

    def test_exact_group_split_booking_approval_and_calendar(self):
        self.login("faculty","reviewer","Electronics")
        template=next(u for u in self.state()["catalog"] if u["id"]=="EE-01")
        self.assertEqual(self.c.post("/api/inventory",json=dict(template,id="EE-07",status="active",revision=0)).status_code,200)
        self.login(owner="A01")
        data=self.exact([("EE-01",9),("EE-07",9),("EE-01",15)],("A01","B02","C03"))
        for _ in range(2):
            self.assertEqual(self.c.post("/api/slot-requests",json=data).status_code,200)
        row=self.state()["rows"][0]
        self.assertEqual(len(self.state()["busy"]),3)
        self.assertTrue(all(s["mine"] and s["pending"] for s in self.state()["busy"]))
        calendar="/api/requests/"+row["id"]+"/calendar"
        self.assertEqual(self.c.get(calendar).status_code,404)
        self.login(owner="B02")
        self.assertFalse(self.state()["rows"][0]["can_cancel"])
        clash=self.exact([("CS-03",15)],("B02",))
        self.assertEqual(self.c.post("/api/slot-requests",json=clash).status_code,409)
        self.login("faculty","reviewer","Electronics")
        self.assertEqual(self.decision(row,"approve").status_code,200)
        self.login(owner="C03")
        self.assertEqual(self.state()["rows"][0]["status"],"approved")
        self.assertEqual(sum(self.state()["metrics"].values()),3)
        events=self.c.get(calendar)
        self.assertEqual(events.status_code,200)
        self.assertEqual(events.text.count("BEGIN:VEVENT"),2)
        self.assertEqual(events.text.count("BEGIN:VALARM"),4)
        self.assertIn("DTSTART:20300304T033000Z",events.text)
        self.login(owner="outsider")
        self.assertEqual(self.state()["rows"],[])
        self.assertEqual(self.c.get(calendar).status_code,404)
        self.login(owner="A01")
        self.assertEqual(self.decision(self.state()["rows"][0],"cancel").status_code,200)
        self.assertEqual(self.state()["busy"],[])
        self.assertEqual(self.c.get(calendar).status_code,404)

    def test_exact_constraints_and_atomic_holds(self):
        self.login(owner="u1")
        for cells,members,expected in [
            ([("EE-01",13)],("A",),409),
            ([("EE-01",9),("EE-01",10),("EE-01",11)],("A",),422),
            ([("EE-01",9),("CS-03",9)],("A",),422),
            ([("EE-01",9),("CS-03",9)],("A","B"),422),
            ([("EE-01",9)],("A","a"),422),
            ([("EE-01",9)],("A","B","C","D"),422)]:
            self.assertEqual(self.c.post("/api/slot-requests",json=self.exact(cells,members)).status_code,expected)
        def send(i):
            data=self.exact([("EE-01",10),("EE-01",11)],("A"+str(i),))
            return self.c.post("/api/slot-requests",json=data).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(send,range(2))),[200,409])
        row=self.state()["rows"][0]
        self.login("faculty","reviewer","Physics")
        self.assertEqual(self.decision(row,"approve").status_code,403)
        self.login("faculty","reviewer","Electronics")
        self.assertEqual(self.decision(row,"approve").status_code,200)
        self.login(owner="u1")
        self.assertEqual(self.c.get("/api/requests/"+row["id"]+"/calendar").text.count("BEGIN:VEVENT"),1)

    def test_class_closes_cells_and_decline_releases_split_hold(self):
        self.login("faculty","reviewer","Electronics")
        lab=next(l for l in self.state()["labs"] if l["number"]=="E204")
        cls=dict(lab_id=lab["id"],weekday=0,start="10:30",end="11:30",subject="Circuits",department="ECE",section="A")
        self.assertEqual(self.c.post("/api/timetable",json=cls).status_code,200)
        self.login()
        self.assertEqual(self.c.post("/api/slot-requests",json=self.exact([("EE-01",11)])).status_code,409)
        self.assertEqual(self.c.post("/api/slot-requests",json=self.exact([("EE-01",9),("EE-01",14)])).status_code,200)
        row=self.state()["rows"][0]
        self.login("faculty","reviewer","Electronics")
        self.assertEqual(self.c.post("/api/timetable",json=dict(cls,start="14:30",end="15:00")).status_code,409)
        self.assertEqual(self.decision(row,"decline").status_code,200)
        self.assertEqual(self.state()["busy"],[])
        self.assertEqual(self.c.post("/api/timetable",json=dict(cls,start="14:30",end="15:00")).status_code,200)

    def test_unreviewed_request_expires_at_first_start(self):
        self.login()
        self.c.post("/api/slot-requests",json=self.exact([("EE-01",9),("EE-01",14)]))
        with mock.patch.object(main,"campus_now",return_value=NOW.replace(hour=9)):
            self.assertEqual(self.state()["rows"][0]["status"],"expired")
            self.assertEqual(self.state()["busy"],[])
