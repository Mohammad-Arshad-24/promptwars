from datetime import date, timedelta
from functools import lru_cache
import os
import secrets
import time
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict

from .advisor import match_project
from .auth import decode, encode, signing_key
from copy import deepcopy
from .catalog import CATALOG
from . import timetable as tt
from .reminders import calendar_file
from .slots import SlotRequest, submit_slots, reserved, people, LUNCH
from .inventory import InventoryChange, save_unit, occupancy_slots
from .scheduler import campus_now, plan, next_openings, OPEN, CLOSE, HORIZON
from .storage import FirestoreStore, SQLiteStore
from .blob_store import BlobStore

app = FastAPI(title="LabLink", docs_url=None, redoc_url=None, openapi_url=None)
STATIC = Path(__file__).resolve().parents[1] / "web"
app.mount("/assets", StaticFiles(directory=STATIC), name="assets")
KEY = signing_key()
TTL = 8 * 3600

@lru_cache
def store():
    if os.getenv("K_SERVICE") or os.getenv("LABLINK_STORE") == "firestore":
        return FirestoreStore()
    if os.getenv("VERCEL"):
        if os.getenv("BLOB_READ_WRITE_TOKEN") or os.getenv("VERCEL_BLOB_READ_WRITE_TOKEN"):
            return BlobStore()
        return SQLiteStore(os.getenv("LABLINK_DB", "/tmp/lablink.sqlite"))
    return SQLiteStore(os.getenv("LABLINK_DB", ".lablink.sqlite"))

@app.middleware("http")
async def protect(request, call_next):
    if request.method == "POST" and request.headers.get("x-lablink") != "1":
        return Response("Missing same-origin request header", status_code=403)
    if request.method == "POST" and int(request.headers.get("content-length") or 0) > 8192:
        return Response("Request too large", status_code=413)
    response = await call_next(request)
    response.headers.update({"X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer",
        "Permissions-Policy":"camera=(), microphone=(), geolocation=(), payment=()",
        "Cross-Origin-Opener-Policy":"same-origin",
        "Content-Security-Policy":"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        "Cache-Control":"no-store" if request.url.path.startswith("/api") else "no-cache"})
    return response

def identity(request):
    user = decode(request.cookies.get("lablink", ""), KEY, "session")
    if not user:
        raise HTTPException(401, "Open a demo or enter your campus access pass.")
    return user

def session(response, info):
    info = dict(info, purpose="session", exp=int(time.time()) + TTL)
    response.set_cookie("lablink", encode(info, KEY), httponly=True, samesite="strict",
                        secure=bool(os.getenv("K_SERVICE") or os.getenv("VERCEL")), max_age=TTL)
    return {"role": info["role"]}

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class Access(Input):
    token: str = Field(min_length=10, max_length=1800)

class Role(Input):
    role: Literal["student", "faculty"]

class Project(Input):
    project: str = Field(min_length=5, max_length=500)

class Booking(Input):
    student_name: str = Field(min_length=1, max_length=100)
    registration_id: str = Field(min_length=1, max_length=40)
    id: UUID
    project: str = Field(min_length=5, max_length=140)
    unit: str = Field(max_length=10)
    skills: list[str] = Field(min_length=1, max_length=5)
    earliest: date
    deadline: date
    from_hour: int = Field(ge=OPEN, lt=CLOSE)
    until_hour: int = Field(gt=OPEN, le=CLOSE)
    preferred: int = Field(ge=OPEN, lt=CLOSE)
    hours: int = Field(ge=1, le=4)
    flexible: bool

class Decision(Input):
    action: Literal["approve", "decline", "cancel"]
    unit: str = Field(default="", max_length=10)
    day: str = Field(default="", max_length=10)
    hour: int = Field(default=0, ge=0, le=16)

def seed(demo, now):
    rows = []
    if demo:
        day = now.date() + timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        base = dict(unit="EE-01", earliest=day.isoformat(), from_hour=10, until_hour=12,
                    preferred=10, hours=2, skills=["waveforms","two channels"], status="pending")
        for owner, title, late, flexible in [("team-river","Sensor calibration",0,False),
                                             ("student","Audio filter validation",2,True)]:
            rows.append(dict(base, id=str(uuid4()), owner=owner, project=title,
                             deadline=(day+timedelta(days=late)).isoformat(), flexible=flexible,
                             created=now.isoformat()))
    timetable = []
    if demo:
        classes = [
            (0, "Signal Lab · E204", "Analog Systems", "ECE", "A", "09:00", "11:00"),
            (0, "Compute Lab · C301", "CUDA Programming", "CSE", "A", "12:00", "14:00"),
            (0, "Vision Lab · D206", "Data Visualisation", "DS", "B", "14:30", "16:30"),
            (1, "Instrumentation · P112", "Physics Laboratory", "PHY", "A", "09:30", "11:30"),
            (1, "Embedded Lab · E105", "IoT and Sensors", "ECE", "B", "11:00", "13:00"),
            (1, "Systems Lab · C104", "Linux Administration", "CSE", "B", "13:30", "15:30"),
            (2, "Signal Lab · E204", "Programming practical", "CSE", "A", "13:30", "15:30"),
            (2, "Compute Lab · C301", "Machine Learning Lab", "DS", "A", "09:00", "12:00"),
            (2, "Instrumentation · P112", "Electronic Measurements", "ECE", "C", "14:00", "16:00"),
            (3, "Vision Lab · D206", "Computer Vision Lab", "DS", "A", "10:00", "12:30"),
            (3, "Embedded Lab · E105", "Embedded Systems", "ECE", "A", "13:00", "15:00"),
            (3, "Systems Lab · C104", "Network Security", "CSE", "C", "15:00", "17:00"),
            (4, "Compute Lab · C301", "AI Project Workshop", "CSE", "A", "09:00", "11:00"),
            (4, "Signal Lab · E204", "Oscilloscope Techniques", "PHY", "B", "11:30", "13:30"),
            (4, "Vision Lab · D206", "Model Deployment", "DS", "C", "14:00", "16:00"),
        ]
        for weekday, room, subject, department, section, start, end in classes:
            room_department = next(u["department"] for u in CATALOG if u["room"] == room)
            timetable.append(dict(id=str(uuid4()),lab_id=tt.lab_key(room_department,room),
                                  weekday=weekday,start=start,end=end,subject=subject,
                                  section=department+" "+section,department=department))
    return {"rows":rows, "calls":[], "timetable":timetable}

def transaction(user, change):
    now = campus_now()
    def perform(state):
        if "inventory" not in state:
            state["inventory"] = deepcopy(CATALOG)
        tt.register_inventory_rooms(state)
        state.setdefault("timetable", [])
        cutoff = (now.date() - timedelta(days=30)).isoformat()
        state["rows"] = [r for r in state["rows"] if r["deadline"] >= cutoff]
        for r in state["rows"]:
            if "slots" in r and r["status"]=="pending" and (r["earliest"],r["preferred"]) <= (now.date().isoformat(),now.hour):
                r.update(status="expired",decided_at=now.isoformat())
        return change(state, now)
    return store().transact(user["space"], perform, lambda:seed(user["demo"], now))

@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")

@app.get("/healthz")
def health():
    return {"status":"ok"}

@app.post("/api/demo")
def demo(response: Response):
    return session(response, dict(space="demo-"+secrets.token_hex(16), owner="student",
                                  dept="*", role="student", demo=True))

@app.post("/api/access")
def access(data: Access, response: Response):
    info = decode(data.token, KEY, "pass")
    if not info:
        raise HTTPException(401, "Invalid or expired access pass.")
    return session(response, info)

@app.post("/api/demo/role")
def switch(data: Role, request: Request, response: Response):
    user = identity(request)
    if not user["demo"]:
        raise HTTPException(403, "Role switching belongs to private demos.")
    return session(response, dict(user, role=data.role))

@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie("lablink")
    return {"closed":True}

@app.post("/api/inventory")
def inventory_update(data: InventoryChange, request: Request):
    user = identity(request)
    if user["role"] != "faculty":
        raise HTTPException(403, "Faculty access required.")
    return transaction(user, lambda state, now: save_unit(state, now, user, data))


@app.post("/api/labs")
def create_lab(data: tt.NewLab, request: Request):
    user = identity(request)
    return transaction(user, lambda state, now: tt.add_lab(state, user, data))


@app.post("/api/timetable")
def create_class(data: tt.ClassSlot, request: Request):
    user = identity(request)
    return transaction(user, lambda state, now: tt.add_class(state, now, user, data))


@app.post("/api/timetable/{slot_id}/edit/{revision}")
def edit_class(slot_id: UUID, revision: int, data: tt.ClassSlot, request: Request):
    user = identity(request)
    def edit(state, now):
        old = tt.find_class(state, user, str(slot_id))
        if old.get("revision", 1) != revision:
            raise HTTPException(409, "This class has changed. Reopen the timetable to edit its latest version.")
        return tt.add_class(state, now, user, data, existing=old)
    return transaction(user, edit)


@app.post("/api/timetable/{slot_id}/remove/{revision}")
def delete_class(slot_id: UUID, revision: int, request: Request):
    user = identity(request)
    def remove(state, now):
        entry = tt.find_class(state, user, str(slot_id))
        if entry.get("revision", 1) != revision:
            raise HTTPException(409, "The class has changed. Refresh before removing it.")
        state["timetable"].remove(entry)
        return {"removed": True}
    return transaction(user, remove)


def department_can_review(user, row, proposal, by_id):
    unit = (proposal or row.get("assigned") or {}).get("unit", row["unit"])
    return user["dept"] in ("*", by_id[unit]["department"])

@app.get("/api/state")
def state(request: Request):
    user = identity(request)
    def read(state, now):
        rows = state["rows"]
        catalog = state["inventory"]
        by_id = {u["id"]: u for u in catalog}
        blocked = tt.class_hours(state)
        proposals = plan(rows, now, catalog, blocked)
        visible = []
        for r in rows:
            proposal = proposals.get(r["id"])
            if user["role"] == "student" and user["owner"].casefold() not in people(r):
                continue
            if user["role"] == "faculty" and not department_can_review(user, r, (proposal or {}).get("slot"), by_id):
                continue
            visible.append(dict(r, proposal=proposal, can_cancel=r["owner"]==user["owner"]))
        days, cursor = [], now.date()
        while len(days) < 5:
            if cursor.weekday() < 5:
                days.append(cursor.isoformat())
            cursor += timedelta(days=1)
        used = {uid:0 for uid in by_id}
        busy = []
        for r in rows:
            mine = r["owner"]==user["owner"] or user["owner"].casefold() in people(r)
            for slot in reserved(r):
                if slot["day"] < now.date().isoformat():
                    continue
                busy.append(dict(**slot, mine=mine, pending=r["status"]=="pending"))
            if r["status"]=="approved":
                for slot in reserved(r):
                    if slot["day"] in days:
                        used[slot["unit"]] += slot["hours"]
        ordered = list(reversed(visible))
        if user["role"] == "faculty":
            ordered.sort(key=lambda r: (r["status"] != "pending", r.get("decided_at", "")))
        return dict(busy=busy, lunch=LUNCH, labs=state["labs"], timetable=state["timetable"], role=user["role"], demo=user["demo"], dept=user["dept"], catalog=catalog,
                    occupancy=occupancy_slots(rows, now.date().isoformat(), (now.date()+timedelta(days=HORIZON)).isoformat()),
                    rows=ordered, openings=next_openings(rows, now, catalog, blocked),
                    today=now.date().isoformat(), now=now.isoformat(),
                    max_day=(now.date()+timedelta(days=HORIZON)).isoformat(), metrics=used, days=days)
    return transaction(user, read)

@app.get("/api/requests/{request_id}/calendar")
def calendar(request_id: UUID, request: Request):
    user = identity(request)
    def export(state, now):
        row=next((r for r in state["rows"] if r["id"]==str(request_id)), None)
        if not row or row["status"]!="approved" or user["role"]!="student" or user["owner"].casefold() not in people(row):
            raise HTTPException(404,"Approved booking unavailable.")
        return calendar_file(row,state["inventory"])
    return Response(transaction(user,export),media_type="text/calendar",
                    headers={"Content-Disposition":'attachment; filename="LabLink-booking.ics"'})


@app.post("/api/slot-requests")
def create_slot_request(data: SlotRequest, request: Request):
    user = identity(request)
    if user["role"] != "student":
        raise HTTPException(403,"Student access required.")
    return transaction(user, lambda state, now: submit_slots(state,now,user,data,tt.class_hours(state),HORIZON))


@app.post("/api/requests")
def submit(data: Booking, request: Request):
    user = identity(request)
    if user["role"] != "student":
        raise HTTPException(403, "Student access required.")
    if not data.from_hour <= data.preferred <= data.until_hour - data.hours:
        raise HTTPException(422, "The preferred session must fit inside your available hours.")
    def add(state, now):
        values = data.model_dump(mode="json")
        rows = state["rows"]
        existing = next((r for r in rows if r["id"] == values["id"]), None)
        if existing:
            if existing["owner"] == user["owner"] and all(existing.get(k) == v for k,v in values.items()):
                return {"id":existing["id"]}
            raise HTTPException(409, "Request identifier already in use.")
        unit = next((u for u in state["inventory"] if u["id"] == data.unit), None)
        if not unit or unit.get("status", "active") != "active" or not set(data.skills).issubset(unit["skills"]):
            raise HTTPException(422, "Choose an available unit that supports the requested capabilities.")
        if not now.date() <= data.earliest <= data.deadline <= now.date()+timedelta(days=HORIZON):
            raise HTTPException(422, "Choose a valid date window in the next 14 days.")
        if len(rows) >= 250 or sum(r["owner"]==user["owner"] and r["status"]=="pending" for r in rows) >= 12:
            raise HTTPException(429, "Active request capacity reached.")
        rows.append(dict(values, owner=user["owner"], created=now.isoformat(), status="pending"))
        return {"id":values["id"]}
    return transaction(user, add)

@app.post("/api/requests/{request_id}/decision")
def decide(request_id: UUID, data: Decision, request: Request):
    user = identity(request)
    def apply(state, now):
        rows = state["rows"]
        row = next((r for r in rows if r["id"] == str(request_id)), None)
        if not row:
            raise HTTPException(404, "Request unavailable.")
        if data.action == "cancel":
            if user["role"] != "student" or row["owner"] != user["owner"]:
                raise HTTPException(403, "Only the requesting student can cancel.")
            if row["status"] == "approved":
                slot = row["assigned"]
                if (slot["day"],slot["hour"]) <= (now.date().isoformat(),now.hour):
                    raise HTTPException(409, "This booking has already started.")
            target = "cancelled"
        else:
            if user["role"] != "faculty":
                raise HTTPException(403, "Faculty access required.")
            catalog = state["inventory"]
            by_id = {u["id"]: u for u in catalog}
            slot = (plan(rows, now, catalog, tt.class_hours(state)).get(row["id"]) or {}).get("slot")
            if not department_can_review(user, row, slot, by_id):
                raise HTTPException(403, "This equipment belongs to another department.")
            if row["status"] != "pending":
                raise HTTPException(409, "This request already has a decision.")
            if data.action == "approve":
                if not slot or slot != {"unit":data.unit,"day":data.day,"hour":data.hour}:
                    raise HTTPException(409, "Availability changed. Refresh and review the new recommendation.")
                row["assigned"] = slot
            target = "approved" if data.action == "approve" else "declined"
        if row["status"] not in ("pending","approved"):
            raise HTTPException(409, "This request is closed.")
        row.update(status=target, decided_at=now.isoformat(), decided_by=user["owner"])
        return {"status":target}
    return transaction(user, apply)

@app.post("/api/advice")
def advice(data: Project, request: Request):
    user = identity(request)
    def meter(state, now):
        calls = [t for t in state.get("calls",[]) if t > now.timestamp()-3600]
        if len(calls) >= 20:
            raise HTTPException(429, "This workspace reached its hourly advisor limit.")
        state["calls"] = calls + [now.timestamp()]
        return state["inventory"]
    catalog = transaction(user, meter)
    allow_model = True
    if os.getenv("VERTEX_MODEL"):
        # Shared by every Cloud Run instance and demo. Creating a fresh demo never resets it.
        stamp = int(time.time()) // 3600
        def reserve_call(budget):
            if budget.get("hour") != stamp:
                budget.update(hour=stamp, count=0)
            if budget["count"] >= 60:
                return False
            budget["count"] += 1
            return True
        allow_model = store().transact("advisor-hourly-budget", reserve_call, dict)
    return match_project(data.project, allow_model, catalog)

@app.get("/favicon.svg")
def favicon():
    return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")

