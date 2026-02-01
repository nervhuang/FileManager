# FileManager

## Tests & CI ✅

- Run smoke test locally: `python -m pytest tests/test_smoke.py` (it runs `main.py --test 1` which auto-exits).
- In VS Code, the `.vscode/launch.json` includes a `Python: Run main.py (test)` configuration that starts the app with `--test 3` and auto-quits after 3 seconds.
- A GitHub Actions workflow is added at `.github/workflows/python-app.yml` that runs the smoke test on push or PR to `main`.

---
