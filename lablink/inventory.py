"""Inventory changes share the same transaction as reservations."""
from typing import Annotated, Literal

from .slots import reserved
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class InventoryChange(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]{0,9}$")
    revision: int = Field(ge=0)
    name: Label
    department: Label
    room: Label
    group: Literal["Instruments", "Development kits", "Workstations"]
    skills: list[Label] = Field(min_length=1, max_length=5)
    description: str = Field(min_length=1, max_length=300)
    status: Literal["active", "maintenance", "retired"]

    @field_validator("skills")
    @classmethod
    def normalize_skills(cls, skills):
        return list(dict.fromkeys(skill.lower() for skill in skills))


def save_unit(state, now, user, change):
    inventory = state["inventory"]
    old = next((u for u in inventory if u["id"] == change.id), None)
    if user["dept"] != "*" and (change.department != user["dept"] or
                                (old and old["department"] != user["dept"])):
        raise HTTPException(403, "You can manage equipment only in your department.")
    revision = old.get("revision", 1) if old else 0
    if change.revision != revision:
        raise HTTPException(409, "This ID already exists or the unit has changed. Refresh the inventory.")
    if not old and len(inventory) >= 200:
        raise HTTPException(409, "This workspace has reached its 200-unit inventory limit.")
    updated = change.model_dump()
    updated["revision"] += 1
    if old:
        # Keep commitments valid and pending requests in their original equipment class.
        for row in state["rows"]:
            if row["status"] == "pending" and row["unit"] == change.id and old["group"] != change.group:
                raise HTTPException(409, "Resolve pending requests before changing the equipment category.")
            if not any(slot["unit"]==change.id and (slot["day"],slot["hour"]+slot["hours"]) >
                       (now.date().isoformat(),now.hour) for slot in reserved(row)):
                continue
            if (change.status != "active" or not set(row["skills"]).issubset(change.skills)
                    or any(old[k] != updated[k] for k in ("room", "department", "group"))):
                raise HTTPException(409, "An upcoming or ongoing booking needs this unit and location. Resolve it first.")
        old.update(updated)
    else:
        inventory.append(updated)
    return {"id": change.id, "revision": updated["revision"]}


def occupancy_slots(rows, first_day, last_day):
    """Expose only allocated unit and interval, never student or project identity."""
    return [slot for r in rows if r["status"]=="approved" for slot in reserved(r)
            if first_day <= slot["day"] <= last_day]
