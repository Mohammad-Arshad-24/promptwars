"""Desktop, keyboard, narrow viewport and WCAG checks. Executed by GitHub Actions."""
from datetime import date, timedelta
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8791"
AXE = ROOT / "node_modules/axe-core/axe.min.js"

def audit(page):
    page.add_script_tag(path=str(AXE))
    violations = page.evaluate("""async () => (await axe.run(document, {
        runOnly: {type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}
    })).violations.map(v=>[v.id,v.nodes.map(n=>n.target)])""")
    assert not violations, violations

def run():
    with tempfile.TemporaryDirectory() as tmp:
        env=dict(os.environ,LABLINK_SECRET="temporary-ci-secret-value-adequate-length",LABLINK_DB=str(Path(tmp)/"demo.sqlite"),VERTEX_MODEL="")
        server=subprocess.Popen([sys.executable,"-m","uvicorn","lablink.main:app","--port","8791"],cwd=ROOT,env=env)
        try:
            for _ in range(80):
                try:
                    with urllib.request.urlopen(URL+"/healthz",timeout=1):break
                except OSError:
                    time.sleep(.2)
            with sync_playwright() as p:
                browser=p.chromium.launch()
                page=browser.new_page(bypass_csp=True)  # Allow only the test harness to inject axe.
                errors=[]
                page.on("pageerror",lambda error:errors.append(str(error)))
                page.goto(URL)
                expect(page.locator(".card")).to_have_count(6)
                page.keyboard.press("Tab")
                expect(page.get_by_text("Skip to workspace")).to_be_focused()
                page.keyboard.press("Enter")
                expect(page.locator("main")).to_be_focused()
                await_free = page.get_by_label("Search equipment")
                await_free.fill("cuda")
                expect(page.locator(".card")).to_have_count(2)
                await_free.fill("")
                audit(page)
                page.get_by_role("button",name="Request access",exact=True).first.click()
                picker=page.get_by_label("Booking date")
                day=date.fromisoformat(picker.get_attribute("min"))+timedelta(days=1)
                while day.weekday()>=5:
                    day+=timedelta(days=1)
                picker.fill(day.isoformat())
                page.get_by_role("button",name="Digital oscilloscope EE-01, 15:00 to 16:00, Available").click()
                page.get_by_role("button",name="Continue booking").click()
                page.get_by_label("Student name").fill("Demo Student")
                page.get_by_label("Registration ID").fill("DEMO-01")
                page.get_by_label("Project title").fill("Student measurement project")
                audit(page)
                page.get_by_role("button",name="Submit request").click()
                expect(page.get_by_role("heading",name="Student measurement project")).to_be_visible()
                page.get_by_role("button",name="Open faculty demo").click()
                row=page.locator(".queueitem").filter(has=page.get_by_role("heading",name="Audio filter validation"))
                expect(row.locator(".proposal")).to_contain_text("Mixed-signal oscilloscope")
                row.get_by_role("button",name="Approve slot").click()
                expect(row.locator(".overline")).to_have_text("APPROVED")
                page.get_by_role("button",name="Return to student demo").click()
                expect(row.locator(".overline")).to_have_text("APPROVED")
                audit(page)
                page.get_by_role("button",name="Utilisation",exact=True).click()
                expect(page.get_by_text("2 / 40 hours booked · 5%")).to_be_visible()
                page.set_viewport_size({"width":375,"height":780})
                page.get_by_role("button",name="Equipment",exact=True).click()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                audit(page)
                assert not errors, errors
                browser.close()
        finally:
            server.terminate()
            server.wait(timeout=10)

if __name__=="__main__":
    run()

