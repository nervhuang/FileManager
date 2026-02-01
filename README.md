# FileManager

![CI](https://github.com/nervhuang/FileManager/actions/workflows/python-app.yml/badge.svg)

## Tests & CI ✅

- Run smoke test locally: `python -m pytest tests/test_smoke.py` (it runs `main.py --test 1` which auto-exits).
- In VS Code, the `.vscode/launch.json` includes a `Python: Run main.py (test)` configuration that starts the app with `--test 3` and auto-quits after 3 seconds.
- A GitHub Actions workflow is added at `.github/workflows/python-app.yml` that runs the smoke test on push or PR to `main`.

### CI monitoring & Slack notifications 🔔

- A workflow (`.github/workflows/ci-notify.yml`) now posts a comment on PRs associated with a completed workflow run.
- You can enable optional Slack notifications by creating an **Incoming Webhook** in Slack, then adding the webhook URL as the repository secret **`SLACK_WEBHOOK_URL`**. When set, the CI will post a brief message to the webhook on workflow completion.
- For local monitoring, use the script `scripts/monitor_ci.py`:
  - `python scripts/monitor_ci.py` — list recent workflow runs
  - `SLACK_WEBHOOK_URL=... python scripts/monitor_ci.py --latest --notify` — send the latest run to Slack

---
