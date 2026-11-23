"""One-hour campus slots, 09:00–17:00, Monday through Friday, in Indian Standard Time."""
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone

from .catalog import CATALOG
from .slots import reserved, people, LUNCH

IST = timezone(timedelta(hours=5, minutes=30))
OPEN, CLOSE, HORIZON = 9, 17, 14


def campus_now():
    return datetime.now(IST)


def day_slots(day, start, hours):
    return [(day, hour) for hour in range(start, start + hours)]


def next_openings(rows, now, catalog=CATALOG, blocked=None):
    """First hour clear of confirmed bookings for each resource in the booking horizon."""
    blocked = blocked or {}
    active = [u["id"] for u in catalog if u.get("status", "active") == "active"]
    occupied = set()
    for row in rows:
        for slot in reserved(row):
            for cell in day_slots(slot["day"], slot["hour"], slot["hours"]):
                occupied.add((slot["unit"], *cell))
    openings = {}
    for offset in range(HORIZON + 1):
        day = now.date() + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        iso = day.isoformat()
        for hour in range(OPEN, CLOSE):
            if hour == LUNCH or (offset == 0 and hour <= now.hour):
                continue
            for uid in active:
                if uid not in openings and (uid, iso, hour) not in occupied and (day.weekday(), hour) not in blocked.get(uid, ()):
                    openings[uid] = dict(day=iso, hour=hour)
            if len(openings) == len(active):
                return openings
    return openings


def priority(row, history, now):
    # Waiting offsets deadline pressure by one day for each full day in the queue.
    waited = max(0, (now.date() - datetime.fromisoformat(row["created"]).date()).days)
    return ((date.fromisoformat(row["deadline"]) - now.date()).days - waited,
            history[row["owner"]], row["created"], row["id"])


def plan(rows, now, catalog=CATALOG, blocked=None):
    """Reserve confirmed slots first, then simulate pending requests in fair order."""
    occupied, students, history, load = set(), set(), Counter(), Counter()
    blocked = blocked or {}
    by_id = {u["id"]: u for u in catalog}
    active = [u for u in catalog if u.get("status", "active") == "active"]
    result = {}
    def reserve(person_ids, unit, day, hour, duration):
        for cell in day_slots(day, hour, duration):
            occupied.add((unit, *cell))
            students.update((person, *cell) for person in person_ids)
        load[unit, day] += duration

    for row in rows:
        for slot in reserved(row):
            reserve(people(row), slot["unit"], slot["day"], slot["hour"], slot["hours"])
            if row["status"]=="approved" and slot["day"] >= (now.date()-timedelta(days=30)).isoformat():
                history[row["owner"]] += slot["hours"]
        if row["status"]=="pending" and "slots" in row:
            first=row["slots"][0]
            future=(row["earliest"],first["hour"])>(now.date().isoformat(),now.hour)
            result[row["id"]]=dict(slot=dict(**first,day=row["earliest"]) if future else None,
                                   previous_hours=history[row["owner"]], effective_days=0)

    waiting = sorted((r for r in rows if r["status"]=="pending" and "slots" not in r),
                     key=lambda r: priority(r, history, now))
    for row in waiting:
        pref = by_id[row["unit"]]
        units = [u for u in active if u["group"] == pref["group"]
                 and set(row["skills"]).issubset(u["skills"])
                 and (u["id"] == pref["id"] or row["flexible"])]
        day = max(now.date(), date.fromisoformat(row["earliest"]))
        last = min(date.fromisoformat(row["deadline"]), now.date() + timedelta(days=HORIZON))
        best = None
        while day <= last:
            if day.weekday() < 5:
                iso = day.isoformat()
                for hour in range(row["from_hour"], row["until_hour"] - row["hours"] + 1):
                    if datetime.combine(day, time(hour), IST) <= now:
                        continue
                    cells = day_slots(iso, hour, row["hours"])
                    if hour <= LUNCH < hour+row["hours"] or any((person, *c) in students for c in cells for person in people(row)):
                        continue
                    for unit in units:
                        if any((unit["id"], d, h) in occupied or (day.weekday(), h) in blocked.get(unit["id"], ()) for d, h in cells):
                            continue
                        # Earliest day, preferred start, lowest daily load, then preferred unit.
                        key = (abs(hour - row["preferred"]), load[unit["id"], iso],
                               unit["id"] != pref["id"], unit["id"], hour)
                        if best is None or key < best[0]:
                            best = (key, dict(unit=unit["id"], day=iso, hour=hour))
            if best:
                break
            day += timedelta(days=1)
        allocation = best[1] if best else None
        result[row["id"]] = dict(slot=allocation, previous_hours=history[row["owner"]],
                                 effective_days=priority(row, history, now)[0])
        if allocation:
            reserve(people(row), allocation["unit"], allocation["day"], allocation["hour"], row["hours"])
    return result

