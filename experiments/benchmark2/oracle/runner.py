"""Grade one (task, arm) pair: run the permission-matrix oracle on a
fresh v1 server, then the migration oracle (seed v1 -> migrate -> verify
on v2). Arm-agnostic; the arm adapter knows how to produce runnable v1/v2
servers and how to migrate the db.

Usage: python3 runner.py <task> <miura|direct>
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from lib import Server, Checks  # noqa: E402
import oracle  # noqa: E402


def _unpack(miura_file, out_dir):
    subprocess.run(["miurac", "unpack", miura_file, "-o", out_dir],
                   check=True, capture_output=True, text=True)
    return os.path.join(out_dir, "server", "app.py")


class MiuraArm:
    def __init__(self, task, tmp):
        self.v1 = os.path.join(BENCH, "miura", task, "v1.miura")
        self.v2 = os.path.join(BENCH, "miura", task, "v2.miura")
        self.tmp = tmp

    def v1_entry(self, tag):
        return _unpack(self.v1, os.path.join(self.tmp, f"m1_{tag}"))

    def v2_entry(self):
        return _unpack(self.v2, os.path.join(self.tmp, "m2"))

    def migrate(self, db):
        r = subprocess.run(["miurac", "migrate", self.v1, self.v2, "--apply", db],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"miurac migrate failed: {r.stderr or r.stdout}")


class DirectArm:
    def __init__(self, task, tmp):
        self.base = os.path.join(BENCH, "direct", task)
        self.tmp = tmp

    def v1_entry(self, tag):
        return os.path.join(self.base, "v1", "app.py")

    def v2_entry(self):
        return os.path.join(self.base, "v2", "app.py")

    def migrate(self, db):
        script = os.path.join(self.base, "v2", "migrate.py")
        r = subprocess.run([sys.executable, os.path.basename(script)],
                           cwd=os.path.dirname(script), capture_output=True, text=True,
                           env=dict(os.environ, DB_PATH=db, MIURA_DB=db))
        if r.returncode != 0:
            raise RuntimeError(f"migrate.py failed: {r.stderr or r.stdout}")


def main():
    task, arm_name = sys.argv[1], sys.argv[2]
    result = {"task": task, "arm": arm_name}
    with tempfile.TemporaryDirectory(prefix="bench2-") as tmp:
        arm = (MiuraArm if arm_name == "miura" else DirectArm)(task, tmp)

        # --- permission matrix on a fresh v1 ---
        perm = Checks()
        db1 = os.path.join(tmp, "perm.db")
        try:
            entry = arm.v1_entry("perm")
            srv = Server(entry, db1)
            try:
                oracle.run_permissions(task, srv, perm)
            finally:
                srv.stop()
        except Exception as err:
            perm.check("v1 server ran", False, repr(err))
        result["permissions"] = perm.summary()

        # --- migration: seed v1 -> migrate -> verify v2 ---
        mig = Checks()
        db2 = os.path.join(tmp, "mig.db")
        try:
            entry1 = arm.v1_entry("mig")
            srv1 = Server(entry1, db2)
            try:
                seed = oracle.seed_for_migration(task, srv1)
            finally:
                srv1.stop()
            arm.migrate(db2)
            entry2 = arm.v2_entry()
            srv2 = Server(entry2, db2)
            try:
                oracle.verify_migrated(task, srv2, mig, seed)
            finally:
                srv2.stop()
        except Exception as err:
            mig.check("migration ran end to end", False, repr(err))
        result["migration"] = mig.summary()

    print(json.dumps(result))


if __name__ == "__main__":
    main()
