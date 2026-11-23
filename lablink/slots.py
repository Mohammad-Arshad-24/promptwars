"""Exact-slot group requests and shared occupancy rules."""
from datetime import date, timedelta
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

LUNCH = 13


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Member(Input):
    name: str = Field(min_length=1, max_length=100)
    registration_id: str = Field(min_length=1, max_length=40)


class Cell(Input):
    unit: str = Field(min_length=1, max_length=10)
    hour: int = Field(ge=9, lt=17)


class SlotRequest(Input):
    id: UUID
    day: date
    project: str = Field(min_length=5, max_length=140)
    members: list[Member] = Field(min_length=1, max_length=3)
    slots: list[Cell] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def limits(self):
        if len({m.registration_id.casefold() for m in self.members}) != len(self.members):
            raise ValueError("Each student needs a different registration ID.")
        if len({c.unit for c in self.slots}) > len(self.members):
            raise ValueError("Select at most one equipment unit per group member.")
        if len({c.hour for c in self.slots}) > 2:
            raise ValueError("Choose one or two hours on this date.")
        if len({(c.unit,c.hour) for c in self.slots}) != len(self.slots):
            raise ValueError("The same slot was selected twice.")
        return self


def reserved(row):
    """Return occupied intervals for both legacy and date-first requests."""
    if row["status"] not in ("approved", "pending"):
        return []
    if "slots" in row:
        return [dict(**cell, day=row["earliest"], hours=1) for cell in row["slots"]]
    if row["status"] == "approved":
        return [dict(**row["assigned"], hours=row["hours"])]
    return []


def people(row):
    keys = {row["owner"].casefold()}
    for member in row.get("members", []):
        keys.add(member["registration_id"].casefold())
    if row.get("registration_id"):
        keys.add(row["registration_id"].casefold())
    return keys


def submit_slots(state, now, user, data, blocked, horizon):
    day = data.day.isoformat()
    values = data.model_dump(mode="json")
    values["slots"].sort(key=lambda c:(c["hour"],c["unit"]))
    rows = state["rows"]
    prior = next((r for r in rows if r["id"] == values["id"]), None)
    if prior:
        if (prior["owner"]==user["owner"] and prior["earliest"]==day and
                all(prior.get(k)==values[k] for k in ("members","slots","project"))):
            return {"id":prior["id"]}
        raise HTTPException(409,"This request ID has already been used.")
    if not now.date() <= data.day <= now.date()+timedelta(days=horizon) or data.day.weekday()>=5:
        raise HTTPException(422,"Choose a campus weekday within the booking window.")
    inventory = {u["id"]:u for u in state["inventory"]}
    units, hours = {c.unit for c in data.slots}, {c.hour for c in data.slots}
    if any(uid not in inventory or inventory[uid].get("status","active")!="active" for uid in units):
        raise HTTPException(409,"One of the selected units is unavailable.")
    if len({(inventory[uid]["department"],inventory[uid]["room"]) for uid in units})!=1:
        raise HTTPException(422,"Choose equipment from one lab per request.")
    if any(c.hour==LUNCH or (data.day==now.date() and c.hour<=now.hour) or
           (data.day.weekday(),c.hour) in blocked.get(c.unit,()) for c in data.slots):
        raise HTTPException(409,"A selected hour is closed, in the past, or reserved for class.")
    primary = values["slots"][0]["unit"]
    row = dict(id=values["id"], owner=user["owner"], project=data.project, earliest=day, deadline=day,
               unit=primary, hours=len(hours), members=values["members"], slots=values["slots"],
               student_name=data.members[0].name, registration_id=data.members[0].registration_id,
               skills=[], flexible=False, from_hour=min(hours), until_hour=max(hours)+1,
               preferred=min(hours), created=now.isoformat(), status="pending")
    selected = {(c.unit,c.hour) for c in data.slots}
    group = people(row)
    for other in rows:
        for slot in reserved(other):
            if slot["day"]!=day:
                continue
            for h in range(slot["hour"], slot["hour"]+slot["hours"]):
                if (slot["unit"],h) in selected or (h in hours and group & people(other)):
                    raise HTTPException(409,"Equipment or a group member already has a booking or pending hold at that hour.")
    if len(rows)>=250 or sum(r["owner"]==user["owner"] and r["status"]=="pending" for r in rows)>=12:
        raise HTTPException(429,"Active request capacity reached.")
    rows.append(row)
    return {"id":row["id"]}
