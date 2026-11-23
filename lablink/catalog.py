"""Campus catalogue. Each ID represents one independently bookable unit."""
def resource(code, name, department, room, group, skills, description):
    return dict(id=code, name=name, department=department, room=room, group=group,
                skills=skills, description=description)

CATALOG = [
    resource("EE-01", "Digital oscilloscope", "Electronics", "Signal Lab · E204", "Instruments",
             ["waveforms", "two channels"], "Capture and compare analogue signals on two channels."),
    resource("PH-02", "Mixed-signal oscilloscope", "Physics", "Instrumentation · P112", "Instruments",
             ["waveforms", "two channels", "logic analysis"], "Inspect analogue waveforms alongside digital logic."),
    resource("CS-03", "GPU workstation", "Computing", "Compute Lab · C301", "Workstations",
             ["cuda", "16 gb vram"], "Train and benchmark CUDA models with 16 GB of GPU memory."),
    resource("DS-04", "Vision workstation", "Data Science", "Vision Lab · D206", "Workstations",
             ["cuda", "16 gb vram", "camera input"], "Run computer vision experiments with a dedicated camera input."),
    resource("EE-05", "ESP32 development kit", "Electronics", "Embedded Lab · E105", "Development kits",
             ["wifi", "gpio", "bluetooth"], "Prototype wireless sensor nodes with GPIO and Bluetooth."),
    resource("CS-06", "Raspberry Pi bench", "Computing", "Systems Lab · C104", "Development kits",
             ["wifi", "gpio", "linux"], "Build Linux-based prototypes with sensors and network access."),
]
BY_ID = {item["id"]: item for item in CATALOG}

