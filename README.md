# FileManager

![CI](https://github.com/nervhuang/FileManager/actions/workflows/python-app.yml/badge.svg)

## Tests & CI ✅

- Run smoke test locally: `python -m pytest tests/test_smoke.py` (it runs `main.py --test 1` which auto-exits).
- In VS Code, the `.vscode/launch.json` includes a `Python: Run main.py (test)` configuration that starts the app with `--test 3` and auto-quits after 3 seconds.
- A GitHub Actions workflow is added at `.github/workflows/python-app.yml` that runs the smoke test on push or PR to `main`.

### CI monitoring & Slack notifications 🔔

- A workflow (`.github/workflows/ci-notify.yml`) now posts a comment on PRs associated with a completed workflow run. If tests fail, the PR comment includes a short list of failed test names and truncated failure messages for quick debugging.
- You can enable optional Slack notifications by creating an **Incoming Webhook** in Slack, then adding the webhook URL as the repository secret **`SLACK_WEBHOOK_URL`**. When set, the CI will post a brief message to the webhook on workflow completion.
  - To add the secret: GitHub → your repo → Settings → Secrets and variables → Actions → **New repository secret** → Name: `SLACK_WEBHOOK_URL`, Value: your webhook URL.
  - To manually test the webhook via GitHub UI: go to **Actions → Notify test (manual)** workflow → **Run workflow**. If the secret is set, a message will be posted to the configured Slack channel.
- For local monitoring, use the script `scripts/monitor_ci.py`:
  - `python scripts/monitor_ci.py` — list recent workflow runs
  - `SLACK_WEBHOOK_URL=... python scripts/monitor_ci.py --latest --notify` — send the latest run to Slack

---
