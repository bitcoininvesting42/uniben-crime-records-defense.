# CRIS — Crime Records & Information System

### Design and Implementation of a Web-based Crime Record and Information System

**University:** University of Benin  
**Researcher:** Eguasa Omorogbe  
**Matriculation number:** PSC1911608  
**Supervisor:** Prof. F. I. Amadin  
**Head of Department:** Mrs. R. O. Usiobaifo  
**Project period:** October 2026

This is a **working, locally runnable academic demonstration website**, not merely a slide or static design. It runs with the Python standard library and SQLite; no paid subscription, internet connection or `pip install` step is needed.

> **Academic prototype only:** All included events and names are fictional. The application is not connected to any police organisation or the earlier `crimerecords.page.gd` website, and it has not been cleared for real-world law-enforcement use. Do not enter real personal or sensitive crime data.

## 1. Run the website on a laptop

### Windows

1. Unzip the downloaded project folder.
2. Ensure **Python 3.10 or newer** is installed from https://www.python.org/downloads/ (during installation, enable *Add Python to PATH*).
3. Double-click `START_WINDOWS.bat` or open Command Prompt in the project folder and run:

   ```bat
   py server.py
   ```

   If `py` does not work, try `python server.py`.
4. In Chrome, Edge, Safari or Firefox, open **http://127.0.0.1:8080**.
5. On the sign-in screen, click one of the demo roles to auto-fill its credentials, then click **Sign in to dashboard**.

### macOS or Linux

1. Unzip the downloaded folder.
2. Open Terminal inside the project folder.
3. Run:

   ```bash
   python3 server.py
   ```

   Or run `bash START_MAC_LINUX.sh`.
4. Open **http://127.0.0.1:8080** in a browser.

The terminal window **must remain open while using the site**. Press `Ctrl+C` to stop the local server.

If port 8080 is occupied, use a different port:

- macOS / Linux: `CRIS_PORT=8090 python3 server.py`
- Windows PowerShell: `$env:CRIS_PORT="8090"; py server.py`

Then open `http://127.0.0.1:8090`.

## 2. Demo accounts

| Role | Username | Password | Capabilities |
| --- | --- | --- | --- |
| Administrator | `admin` | `Admin@2026` | All modules, case summary export, system activity log |
| Records Officer | `officer` | `Officer@2026` | Register incidents and cases; add persons and evidence; change case status |
| Reports Analyst | `analyst` | `Analyst@2026` | View case records without linked personal information, see analytical reports and export case summaries |

The application shows a **Quick Demo Access** button for each role so you do not need to memorise these details.

> These are intentionally public test credentials, **not** suitable for public hosting or processing real information.

## 3. Working modules

| Module | Implementation |
| --- | --- |
| Authentication | Hashed demo-account passwords, server-side sessions, HTTP-only SameSite cookies, anti-CSRF tokens |
| Dashboard | Database-derived case totals, case workflow chart, monthly case trend, activity list |
| Incident Reports | New incidents, generated `INC-2026-0001`-style IDs, search |
| Case Files | New case linked to incident, `CASE-2026-0001`-style IDs, search/filter, assigned officer, priority and status updates |
| People Registry | Role-neutral fictional persons; can link to a case as complainant, witness, victim or subject of allegation |
| Evidence Register | Evidence metadata, case link, custody/storage label and collected date |
| Case Status History | Tracks transitions, actor, date and change reason |
| Insights & Reports | Live counts grouped by category, location, workflow status and month; CSV export for permitted roles |
| Audit Log | Registration, updates, sign-in, denied access and export events; visible only to administrator |
| Project & Guide | Researcher details, a suggested defense walkthrough, architecture and relational schema diagrams |

### Technologies

- **Frontend:** Semantic HTML, responsive CSS, modern vanilla JavaScript, inline SVG icons and charts.
- **Backend:** Python `http.server` with JSON API endpoints, request validation and role-based authorization.
- **Database:** SQLite relational database with foreign keys and indexed common search fields.
- **Security measures included for the prototype:** Password hashing with PBKDF2-HMAC-SHA256, 8-hour server sessions with HttpOnly + SameSite=Strict cookies, anti-CSRF token checks, parameterized SQL queries, HTML escaping and per-route authorization.

## 4. Five-minute project defense demonstration

1. **Sign in as Officer.** Explain who is allowed to view or edit records.
2. **Dashboard:** Point to total case files, active cases, resolved cases and reporting charts. Explain that metrics are calculated from the database.
3. **Register a fictional incident.** Show the automatically generated incident ID. Use a recent occurrence and reporting date.
4. **Create a new case.** Choose the incident from the dropdown; assign it to the Records Officer.
5. **Open the case.** Change `Open` to `Under Investigation`, enter a reason and show its status history.
6. **People Registry and Evidence Vault:** Add an entirely fictional person or evidence item; use **Link Person** within the case detail window to indicate their role.
7. **Insights & Reports:** Show how the registered data changes the case counts and charts.
8. **Administrator view:** Sign out, sign in as Admin and display the audit log.
9. **Analyst view:** Sign out and sign in as Analyst to show that person details, evidence, mutation controls and the administrative log are unavailable.

## 5. Database and resetting the demonstration

On first run, the app creates `crime_records_demo.db` in the project directory and populates it with fictional case, incident, person and evidence records.

New or updated records persist when the server is stopped and restarted.

To start again with the **original sample records**, stop the server, back up anything you need, then delete the `crime_records_demo.db` file and restart the server. **Deleting this file permanently deletes any entries you created.**

## 6. Test the project

Run this from the project directory:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

On Windows use `py -m unittest discover -s tests -p "test_*.py" -v`.

The test suite uses an isolated temporary database. It checks login and access protection, dashboard counts, incident/case registration, status history, person and evidence links, CSRF validation, analyst restrictions, export controls, audit events, and static assets.

## 7. Scope and deployment limitations

This website is ready for demonstration **on a laptop**. It is not automatically hosted on the internet, and opening `static/index.html` directly will not work: the Python server must be running to serve the API and database. The provided startup scripts run only on the local computer for safety.

For real institutional deployment, additional work would be necessary, including HTTPS and secure cookie configuration, independently audited authentication and authorization, a dedicated production server, logging/monitoring, database backups and disaster recovery, record-retention procedures, lawful handling of personal data, and professional security assessment. The project is not an official crime database or a substitute for one.

## 8. Project structure

```text
UNIBEN_Crime_Records_Defense_Website/
├── server.py                # Python JSON API, data model, sample data
├── static/
│   ├── index.html           # Login / application shell
│   ├── styles.css           # Responsive visual design
│   ├── app.js               # Interface logic and dashboards
│   ├── favicon.svg
│   ├── architecture.svg
│   └── database-model.svg
├── tests/
│   └── test_end_to_end.py   # Automated API integration tests
├── previews/
│   ├── login.png
│   ├── dashboard.png
│   ├── mobile.png
│   └── project-guide.png
├── START_WINDOWS.bat
├── START_MAC_LINUX.sh
└── README.md
```

**Prepared for academic project defense, October 2026.**
