import os
import sys
import subprocess
import platform


def test_main_smoke():
    """Run main.py in test mode and ensure it exits successfully."""
    python = sys.executable
    env = os.environ.copy()

    # Use offscreen platform to avoid requiring a display on Linux/macOS CI
    if platform.system() != "Windows":
        env.setdefault("QT_QPA_PLATFORM", "offscreen")

    proc = subprocess.Popen([python, "main.py", "--test", "1"], env=env)
    proc.wait(timeout=10)
    assert proc.returncode == 0, f"main.py exited with {proc.returncode}"