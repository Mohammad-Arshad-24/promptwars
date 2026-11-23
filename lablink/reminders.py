"""Portable reminders for approved equipment sessions."""
from datetime import datetime, timedelta, timezone
from .scheduler import IST
from .slots import reserved


def escape(value):
    return value.replace("\\","\\\\").replace("\r\n","\n").replace("\r","\n").replace("\n","\\n").replace(",","\\,").replace(";","\\;")


def fold(line):
    parts, chunk, size = [], "", 0
    for char in line:
        length=len(char.encode("utf8"))
        if size+length>75:
            parts.append(chunk)
            chunk,size=" ",1
        chunk+=char
        size+=length
    return "\r\n".join(parts+[chunk])


def calendar_file(row, catalog):
    by_id={u["id"]:u for u in catalog}
    periods={}
    for slot in reserved(row):
        for h in range(slot["hour"],slot["hour"]+slot["hours"]):
            periods.setdefault(h,set()).add(slot["unit"])
    day=row["assigned"]["day"]
    midnight=datetime.fromisoformat(day).replace(tzinfo=IST)
    def stamp(t):
        return t.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines=["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//LabLink//Campus Bookings//EN","CALSCALE:GREGORIAN"]
    hours=sorted(periods)
    while hours:
        start=hours.pop(0)
        end=start+1
        units=set(periods[start])
        while hours and hours[0]==end:
            units.update(periods[hours.pop(0)])
            end+=1
        location=", ".join(sorted({by_id[u]["room"] for u in units}))
        lines.extend(["BEGIN:VEVENT",f"UID:{row['id']}-{day}-{start}@lablink",
                      "DTSTAMP:"+stamp(datetime.now(timezone.utc)),"DTSTART:"+stamp(midnight+timedelta(hours=start)),
                      "DTEND:"+stamp(midnight+timedelta(hours=end)),"SUMMARY:"+escape(row["project"]),
                      "LOCATION:"+escape(location),"DESCRIPTION:"+escape(", ".join(by_id[u]["name"]+" ("+u+")" for u in sorted(units))),
                      "STATUS:CONFIRMED"])
        for trigger in ("-PT15M","PT0M"):
            lines.extend(["BEGIN:VALARM","TRIGGER:"+trigger,"ACTION:DISPLAY","DESCRIPTION:LabLink booking reminder","END:VALARM"])
        lines.append("END:VEVENT")
    return "\r\n".join(fold(line) for line in [*lines,"END:VCALENDAR"])+"\r\n"
