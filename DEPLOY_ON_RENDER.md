# Deploy this University of Benin project to Render

This ZIP contains a **Render-ready source tree**, not an already hosted website.

1. Connect Render and a GitHub repository containing the contents of this folder (top-level `render.yaml` and `server.py`).
2. In Render, create a Blueprint service from the repository, or create a Python Web Service with build command `python -m compileall -q server.py` and start command `python server.py`.
3. Use the Free plan; configure `CRIS_PUBLIC_DEMO=1` and `CRIS_HOST=0.0.0.0`. Render supplies the `PORT` environment variable automatically.
4. Privately enter DIFFERENT strong passwords (12+ characters) for `CRIS_ADMIN_PASSWORD`, `CRIS_OFFICER_PASSWORD`, and `CRIS_ANALYST_PASSWORD`. Do not commit credentials to GitHub or post them publicly.
5. Test `https://YOUR-NAME.onrender.com/api/health` for a JSON response, then sign in at the root URL.

**Data warning:** Render free services have ephemeral filesystems. This project uses SQLite, so records may be reset on instance replacement/redeploy/restart. All seeded records are fictional; do not enter real personal data. A persistent hosted database would require additional engineering, security testing, and a compatible hosting/persistence solution.

**Local testing:** Run `python -m unittest discover -s tests -v` and `python server.py`, then browse `http://127.0.0.1:8080`. Local accounts still use the original demo credentials to keep the existing tests functional.
