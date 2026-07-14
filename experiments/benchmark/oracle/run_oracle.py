"""Run one task's oracle against one app directory.

Usage: python3 run_oracle.py <task> <app_dir>
Prints a JSON summary; exit 0 iff every check passed.
"""

import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import App, Checks  # noqa: E402


def main():
    task, app_dir = sys.argv[1], sys.argv[2]
    checks = Checks()
    try:
        app = App(app_dir)
    except Exception as err:
        print(json.dumps({"task": task, "app_dir": app_dir, "passed": 0, "total": 1, "boot_error": str(err)[:500]}))
        return 1
    try:
        module = importlib.import_module(task)
        module.run(app, checks)
    except Exception as err:
        checks.check("oracle aborted mid-run", False, repr(err))
    finally:
        app.stop()
    summary = checks.summary()
    summary.update({"task": task, "app_dir": app_dir})
    print(json.dumps(summary))
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
