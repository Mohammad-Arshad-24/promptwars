# LabLink

A campus equipment exchange for students and faculty. Students search a shared catalogue, describe their project to a Gemini advisor and request time on equipment. Faculty review a feasible allocation that preserves the student’s project requirements and accounts for competing deadlines, waiting time and previous usage.

## Try it locally

Python 3.12 is recommended. Open this folder in VS Code. On Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-test.txt
.\.venv\Scripts\python -m uvicorn lablink.main:app --port 8080
```

Open http://127.0.0.1:8080. A new browser receives its own isolated demo with six units across four departments. Local mode uses SQLite and a labelled keyword matcher until a Gemini model is configured. The public Cloud Run service uses Firestore. No external images, fonts or CDN assets are required to open the app.

## Two-minute demonstration

1. Open **Requests** in a fresh demo. The audio-filter team asked for the electronics oscilloscope for two hours. Another team needs that same instrument and time, has an earlier deadline and cannot use a substitute.
2. Select **Open faculty demo**. Compare the two requests. The calibration team gets the preferred scope. The audio team gets the Physics mixed-signal scope on the same day with both required capabilities. Approve the audio team’s proposed slot.
3. Return to the student view. The request shows the confirmed unit, date and hours. Open **Utilisation**. Physics now shows 2 of 40 available hours booked (5%). Cancel from the student view to release the slot.
4. Under **Equipment**, open **Find equipment for my project** and try “I need to train a vision model using CUDA with 16 GB of GPU memory.” Inspect the source label and request a suggested unit. Select a weekday in **LAB TIMETABLE** to see which hours are free. With Gemini configured, the explanation comes from a live model.
5. Choose **Group of 2 students**. Select two free hours, such as 10:00 and 14:00, on the same instrument. Continue, enter both names and registration IDs, and submit. Approve the request in the faculty demo, then return to **Requests** as a student and download the calendar reminder.

## Faculty inventory and lab occupancy

Open **Open faculty demo**, then **Equipment → Add equipment**. Use a unique physical asset ID for each bookable unit. Pick an existing lab room or enter a new room. Use **Edit equipment** to change details, put a unit under maintenance, retire it, or return it to service. Campus faculty can manage their own department. The private demo lets one reviewer try both roles.

Both roles can open **Labs & occupancy**, select a date and starting hour in IST, and expand a lab to see each unit. Confirmed bookings count towards occupancy. Date-first requests immediately hold the selected equipment. Pending flexible proposals are tentative. Maintenance and retirement take a unit out of new allocations and advisor suggestions. A change that would invalidate a confirmed booking is rejected. A student looking at another team's allocation sees the occupied unit and hours without the team identity or project.

A campus pass is a signed, time-limited invitation from a lab coordinator. It grants a student or departmental faculty role in the shared campus workspace. The demo requires no pass.

## Lab directory, weekly classes and request filters

Faculty can create a numbered room before assigning any equipment. Open **Labs & occupancy → Add lab** and record the name, number, owning department and known physical access. Each room lists its inventory and unit count. Use the department and access filters for rooms, or the category and status filters for individual units.

Both roles can open **LAB TIMETABLE** and filter weekly classes by weekday, lab, attending department or section. Department faculty maintain recurring classes in IST. A class reserves its room for any equipment slot it overlaps, including part of an hour. Scheduling checks room and section conflicts, confirmed project bookings and concurrent timetable edits. New private demos include an example class. Faculty enter the real schedule in the shared campus workspace.

New project requests require the student's name and registration ID. These details are visible to the requester and authorised reviewers. The faculty queue keeps pending work first and moves decisions below it; the status filters and search narrow the list without changing its order.

## Allocation policy

Campus hours are weekdays 09:00–17:00 IST. A request can span 1–4 consecutive hours within a 14-day horizon. A deadline includes its final date. Earliest date, deadline, daily availability, duration, capability requirements, class of equipment and consent to substitution are hard constraints. Confirmed bookings block both the equipment and the student. Every request has one student owner.

Pending requests are processed in order of (days to deadline minus full calendar days waiting), fewer approved hours within the rolling history, submission timestamp and request ID. For each request, the planner considers the earliest feasible day, closeness to the preferred start, lower daily equipment load and the preferred unit, in that order. Tentative allocations block later proposals in the same planning pass. No feasible slot yields a waitlist entry. This is a deterministic priority heuristic; it does not claim a globally optimal timetable.

A faculty approval recomputes the proposal inside the same transaction that commits it. A changed proposal returns HTTP 409 and requires a fresh review. Approval never evicts a confirmed booking. Student submissions use a client-generated request ID to make retries idempotent. Availability cards report the first hour clear of reservations, holds, lunch and scheduled classes. The utilisation view counts confirmed hours against 5 weekdays × 8 hours per resource.

## Architecture and access

| Component | Implementation |
| --- | --- |
| Browser | Semantic HTML, responsive CSS and JavaScript. Native modal dialogs, labels, keyboard controls, live status and a skip link. |
| Application | Python, FastAPI and Pydantic. One same-origin service handles the UI, validated requests and approval authorisation. |
| Advisor | Google Gen AI SDK using Gemini on Vertex AI. It receives project text and public equipment descriptions. The server validates returned equipment IDs. A timeout or unavailable model switches to an explicitly labelled catalogue match. |
| Storage | SQLite transactions locally. Firestore transactions on Cloud Run. One bounded document per workspace keeps proposal validation and approval atomic across instances. |
| Identity | Signed, expiring sessions in HTTP-only cookies. Cloud Run uses secure cookies. Campus passes come from a trusted operator. Public evaluators can change roles only inside their own demo. Campus faculty can review proposals only for their own equipment department. |
| Hosting | Public Google Cloud Run service with an attached service account and a signing secret stored in Secret Manager. |

In a campus pilot, issue passes privately using `python -m lablink.pass_cli student-2117 student` or `python -m lablink.pass_cli faculty-01 faculty --department Physics` from a trusted terminal with the deployment signing secret available in its environment. A pass is redeemable for one hour and creates an eight-hour session. The private demo is usable without a pass. Reopening without the same cookie creates a separate demo.

The prototype supports 250 retained requests per workspace and 12 pending requests per student. Requests leave the rolling store 30 days after their deadline. Firestore demo records carry an `expiresAt` field. Enable a Firestore TTL policy on that field for the `lablink_spaces` collection group if automatic demo deletion is wanted. The advisor permits 20 calls per workspace per hour and 60 live model calls across the deployment per clock hour. Provider quotas and cloud charges are separate.

## Deploy to Vercel

Import the repository at its root using the FastAPI preset. Vercel loads `app.py`. Connect a private Blob store and set `LABLINK_SECRET` to a randomly generated production secret of at least 32 characters. Each booking change creates a private workspace revision. Concurrent writers must commit to the same next revision, so conflicts trigger a fresh availability check. The Blob store retains revision history.

To enable the Gemini advisor, set `GOOGLE_CLOUD_PROJECT` and `VERTEX_MODEL` and provide a Google identity with Vertex AI User. Vercel can read a dedicated service account from the sensitive production variable `LABLINK_GOOGLE_CREDENTIALS_JSON`. Without a configured model, the advisor labels its catalogue keyword fallback.

After deployment, open a fresh demo and verify the student booking and faculty approval. The competition briefing separately specifies a working Cloud Run deployment for Top 10 eligibility.

## Deploy to Google Cloud Run

Create or select a billing-enabled Google Cloud project. In Google Cloud Shell, sign in under an account authorised to enable services, provision Firestore, create service accounts and IAM bindings, configure Secret Manager, build from source and expose a public Cloud Run service. Use a project where the default database is available for Firestore Native mode. Choose a Gemini model ID that your project can call in the global Vertex AI location.

From the project source directory in Cloud Shell:

```bash
bash scripts/deploy.sh YOUR_PROJECT_ID YOUR_ENABLED_GEMINI_MODEL asia-south1
```

The script provisions the runtime and build identities, creates or reuses the signing secret and default database, deploys the container, then opens a fresh demo on the public URL. The build account receives Cloud Run Builder. The runtime identity receives Datastore User, Vertex AI User and access to the single signing secret. The script preserves the existing secret on subsequent deployments. No GitHub token, Gemini API key or service-account JSON file belongs in the repository.

The script prints the URL only after the live check passes. To verify an existing deployment independently:

```bash
python scripts/live_check.py https://YOUR-SERVICE.run.app
```

If the advisor returns the keyword fallback, confirm Vertex model access, region, runtime IAM and quota, then repeat the live check. A functioning homepage alone does not verify the model or database. A billing-enabled project and public access authorisation are prerequisites for this deployment.

## Tests and evaluation evidence

```bash
python -m unittest discover -s tests -v
node --check web/app.js
```

The included GitHub Actions workflow runs the unit/API tests and a Chromium journey with an axe accessibility scan. For the browser suite locally install Playwright (`python -m pip install playwright`, `python -m playwright install chromium`) and axe-core (`npm install --no-save --package-lock=false axe-core@4.10.3`), then run `python tests/browser_flow.py`.

| Briefing criterion | Evidence to inspect |
| --- | --- |
| Code quality | Separate catalogue, scheduler, persistence, access and advisor modules. Validated request and decision schemas. |
| Security | Student ownership and department scoping, signed sessions, same-origin write header, CSP, separate private demos, secret-managed cloud identity and request caps. |
| Efficiency | Bounded search horizon and queue, indexed occupied slots, local assets, one atomic document per workspace and lower-load allocation tie-break. |
| Testing | Scheduler constraints and fairness, duplicate submissions, stale approvals, concurrent approvals, private data scoping, advisor fallback and model output validation. Browser CI and post-deploy smoke tests exercise the public journey. |
| Accessibility | Search labels, native controls, visible focus, skip link, modal headings, text descriptions of recommendations and responsive cards. Browser suite checks keyboard navigation, narrow width and automated WCAG rules. |
| Problem alignment | Discovery across four departments, genuine GenAI equipment matching, project-based requests, faculty approvals, actionable alternatives, cancellation, waitlisting and measured utilisation. |

## Submission requirements

Sign into the competition platform with the exact registration email. Submit the last verified build during the ongoing challenge. Pages 2–6 and 12–17 of the briefing together require all of the following.

- Public repository URL ending in `.git`: https://github.com/Mohammad-Arshad-24/promptwars.git
- Exactly one remote branch, repository under 10 MB. Check the published repository using `python scripts/repo_check.py`.
- A working, publicly accessible **Cloud Run** application URL. Test it in a signed-out browser and run the live check.
- A public LinkedIn project-post URL explaining what you built and how it solves the challenge.
- A brief project description on the platform.

There are up to two scored submissions. The most recent score counts. One retry for the same attempt is reserved for a technical failure that prevented evaluation. Top-10 eligibility also depends on the working Cloud Run deployment. The briefing publishes six signals without numerical weights or a guaranteed score formula.

**Project description for the submission form**

LabLink lets students find equipment across campus departments and request lab time for a project. A Gemini advisor matches project needs to the equipment catalogue. The scheduler checks capabilities, student availability, deadlines and prior usage to recommend feasible slots. Faculty approve the allocation, while students can track their requests and see how much lab capacity is booked.

**LinkedIn post draft — publish after the live check passes**

I built LabLink to help students find and book equipment outside their own department. The demo starts with two teams asking for the same oscilloscope. One has a tighter deadline and needs that exact instrument. LabLink finds an equivalent scope in Physics for the other team, keeps its two-hour window, and sends both recommendations to faculty for approval.

Students can also describe a project to Gemini, see matching equipment and request a slot. The utilisation view updates as bookings are approved or cancelled.

Try the live demo: [insert verified Cloud Run URL]
Source: https://github.com/Mohammad-Arshad-24/promptwars

