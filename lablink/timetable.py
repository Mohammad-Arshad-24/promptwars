"""Shared lab directory and recurring college classes, in campus local time."""
from datetime import date
from uuid import uuid4, uuid5, NAMESPACE_URL

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from .inventory import Label
from .slots import reserved


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NewLab(Record):
    name: Label
    number: str = Field(min_length=1, max_length=24)
    department: Label
    access: Literal["Not recorded", "Step-free access", "Stairs required"] = "Not recorded"


class ClassSlot(Record):
    lab_id: str = Field(max_length=40)
    weekday: int = Field(ge=0, le=4)
    start: str = Field(pattern=r"^(09|1[0-7]):[0-5][0-9]$")
    end: str = Field(pattern=r"^(09|1[0-7]):[0-5][0-9]$")
    subject: Label
    department: Label
    section: Label


def lab_key(department, room):
    return str(uuid5(NAMESPACE_URL, str((department, room))))


def register_inventory_rooms(state):
    labs = state.setdefault("labs", [])
    known = {(l["department"], l["room"]) for l in labs}
    for u in state["inventory"]:
        room, dept = u["room"], u["department"]
        if (dept, room) not in known:
            name, sep, number = room.rpartition(" · ")
            labs.append(dict(id=lab_key(dept,room), name=name if sep else room,
                             number=number if sep else "", room=room, department=dept, access="Not recorded"))
            known.add((dept, room))


def authorize(user, department):
    if user["role"] != "faculty" or user["dept"] not in ("*", department):
        raise HTTPException(403, "Only faculty responsible for this lab can change it.")


def add_lab(state, user, data):
    authorize(user, data.department)
    room = f"{data.name} · {data.number}"
    if len(room)>80:
        raise HTTPException(422, "Use a shorter lab name and number (80 characters combined).")
    for lab in state["labs"]:
        if lab["department"].casefold()==data.department.casefold() and (
                lab["number"].casefold()==data.number.casefold() or lab["room"].casefold()==room.casefold()):
            raise HTTPException(409, "This department already has that lab number.")
    if len(state["labs"]) >= 250:
        raise HTTPException(409, "Lab directory limit reached.")
    record = dict(**data.model_dump(), id=lab_key(data.department, room), room=room)
    state["labs"].append(record)
    return record


def overlaps(start, end, other_start, other_end):
    return start < other_end and other_start < end


def add_class(state, now, user, data, existing=None):
    lab = next((l for l in state["labs"] if l["id"] == data.lab_id), None)
    if lab is None:
        raise HTTPException(404, "Select a listed lab.")
    authorize(user, lab["department"])
    if not "09:00" <= data.start < data.end <= "17:00":
        raise HTTPException(422, "Choose a start before the end, within 09:00–17:00.")
    for slot in state["timetable"]:
        if slot is existing:
            continue
        same_section = (slot["department"].casefold(),slot["section"].casefold()) == (data.department.casefold(),data.section.casefold())
        if (slot["lab_id"] == data.lab_id or same_section) and slot["weekday"] == data.weekday and overlaps(data.start,data.end,slot["start"],slot["end"]):
            raise HTTPException(409, "This lab or student section already has a class at that time.")
    units = {u["id"] for u in state["inventory"] if (u["department"],u["room"])==(lab["department"],lab["room"])}
    for row in state["rows"]:
        for slot in reserved(row):
            if slot["unit"] not in units:
                continue
            day = date.fromisoformat(slot["day"])
            start, end = slot["hour"], slot["hour"] + slot["hours"]
            if (day, end) > (now.date(), now.hour) and day.weekday()==data.weekday and overlaps(data.start,data.end,f"{start:02}:00",f"{end:02}:00"):
                raise HTTPException(409, "An equipment booking or pending hold overlaps this class.")
    if existing is None and len(state["timetable"]) >= 500:
        raise HTTPException(409, "Timetable limit reached.")
    if existing is not None:
        existing.update(data.model_dump(), revision=existing.get("revision", 1)+1)
        return existing
    entry = dict(**data.model_dump(), id=str(uuid4()), revision=1)
    state["timetable"].append(entry)
    return entry


def find_class(state, user, slot_id):
    for slot in state["timetable"]:
        if slot["id"] == slot_id:
            lab = next(l for l in state["labs"] if l["id"] == slot["lab_id"])
            authorize(user, lab["department"])
            return slot
    raise HTTPException(404, "This class has already been removed.")


def class_hours(state):
    """Index weekly class occupancy once per lab and share across all its units."""
    hours = {}
    for slot in state["timetable"]:
        cells = hours.setdefault(slot["lab_id"], set())
        for hour in range(9,17):
            if overlaps(slot["start"],slot["end"],f"{hour:02}:00",f"{hour+1:02}:00"):
                cells.add((slot["weekday"],hour))
    by_room = {(l["department"],l["room"]):hours.get(l["id"], ()) for l in state["labs"]}
    return {u["id"]:by_room.get((u["department"],u["room"]), ()) for u in state["inventory"]}
