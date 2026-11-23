"""Verify the public judge journey against a deployed service in an isolated demo."""
import argparse
import http.cookiejar
import json
import urllib.request
from urllib.parse import urlsplit

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    if urlsplit(base).scheme != "https":
        parser.error("Use the public HTTPS service URL")
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(path, data=None):
        body = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request(base+path, data=body, headers={"X-LabLink":"1","Content-Type":"application/json"})
        with opener.open(req, timeout=45) as response:
            return json.load(response)

    with opener.open(base, timeout=45) as page:
        assert b"LabLink" in page.read(), "Public home page unavailable"
    assert call("/healthz")["status"] == "ok"
    call("/api/demo", {})
    state = call("/api/state")
    assert state["demo"] and len(state["catalog"]) >= 3
    answer = call("/api/advice", {"project":"I need a GPU workstation for CUDA vision model training."})
    assert answer["mode"] == "Gemini" and answer["matches"], "Live Gemini unavailable. Check model, region, IAM and quota."
    call("/api/demo/role", {"role":"faculty"})
    queue = call("/api/state")["rows"]
    row = next(r for r in queue if r["project"]=="Audio filter validation")
    slot = row["proposal"]["slot"]
    assert slot and slot["unit"] != row["unit"], "Equivalent-unit recommendation missing"
    call("/api/requests/"+row["id"]+"/decision", {"action":"approve", **slot})
    call("/api/demo/role", {"role":"student"})
    state = call("/api/state")
    assert state["rows"][0]["status"]=="approved" and sum(state["metrics"].values())==2
    print("PASS: public home, storage, live Gemini, fair conflict resolution, faculty approval, student confirmation and utilisation.")

if __name__ == "__main__":
    main()

