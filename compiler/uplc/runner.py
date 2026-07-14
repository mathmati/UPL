"""The bundle test runner: executes a bundle's (tests ...) cases
against its own unpacked Python target.

Each case runs against a fresh database. Steps call the generated
action_*/query_* functions directly (no HTTP), so what is tested is
exactly the code that will serve requests — including its compiled
requires/ensures/field-require contracts."""

from __future__ import annotations

import importlib.util
import os
import tempfile

from . import expr as E
from .emit_python import emit_python
from .model import App, StepCheck, StepDo, StepFail


class CaseResult:
    def __init__(self, name: str):
        self.name = name
        self.failures = []  # [str]

    @property
    def ok(self) -> bool:
        return not self.failures


def _load_module(app: App, workdir: str):
    server_dir = os.path.join(workdir, "server")
    os.makedirs(server_dir, exist_ok=True)
    app_path = os.path.join(server_dir, "app.py")
    with open(app_path, "w", encoding="utf-8") as fh:
        fh.write(emit_python(app, "test build — not for deployment"))
    db_path = os.path.join(workdir, "test.db")
    os.environ["UPL_DB"] = db_path
    spec = importlib.util.spec_from_file_location("upl_generated_app", app_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, db_path


def _eval(expr, env: dict, src: str):
    names = {name: f"env[{name!r}]" for name in env}
    code = E.to_python(expr, names)
    try:
        return eval(code, {"__builtins__": {}, "len": len}, {"env": env})
    except Exception as err:  # surface as a test failure, not a crash
        raise _EvalError(f"error evaluating {src}: {err}")


class _EvalError(Exception):
    pass


def run_tests(app: App):
    """Run all cases; returns [CaseResult]."""
    results = []
    with tempfile.TemporaryDirectory(prefix="uplc-test-") as workdir:
        module, db_path = _load_module(app, workdir)
        for case in app.tests:
            result = CaseResult(case.name)
            results.append(result)
            if os.path.exists(db_path):
                os.remove(db_path)
            module.init_db()
            env = {}
            for i, step in enumerate(case.steps, 1):
                try:
                    _run_step(module, step, env, result, i)
                except _EvalError as err:
                    result.failures.append(f"step {i}: {err}")
                if result.failures:
                    break  # later steps depend on earlier state; stop the case
    return results


def _step_args(step, env):
    return {name: _eval(value_expr, env, src) for name, value_expr, src in step.args}


def _run_step(module, step, env, result: CaseResult, i: int):
    if isinstance(step, StepDo):
        fn = getattr(module, f"action_{step.action}")
        try:
            row = fn(_step_args(step, env))
        except module.ContractViolation as err:
            result.failures.append(f"step {i}: (do {step.action} ...) was rejected by a contract: {err}")
            return
        except module.EnsuresViolation as err:
            result.failures.append(f"step {i}: (do {step.action} ...) violated an ensures contract (generated code bug): {err}")
            return
        check_env = dict(env, result=row)
        for expr, src in step.expects:
            if not _eval(expr, check_env, src):
                result.failures.append(f"step {i}: expect failed: {src} (result = {row!r})")
        if step.bind:
            env[step.bind] = row
    elif isinstance(step, StepFail):
        fn = getattr(module, f"action_{step.action}")
        try:
            fn(_step_args(step, env))
        except module.ContractViolation:
            return  # expected
        except module.EnsuresViolation as err:
            result.failures.append(f"step {i}: (fail {step.action} ...) hit an ensures violation instead of a requires rejection: {err}")
            return
        result.failures.append(f"step {i}: (fail {step.action} ...) expected a contract rejection but the action succeeded")
    elif isinstance(step, StepCheck):
        fn = getattr(module, f"query_{step.query}")
        rows = fn()
        check_env = dict(env, result=rows)
        for part in step.parts:
            if part[0] == "expect":
                _, expr, src = part
                if not _eval(expr, check_env, src):
                    result.failures.append(f"step {i}: expect failed: {src} (result = {len(rows)} rows)")
            else:  # ("row", index, bind_name)
                _, index, bind_name = part
                if index >= len(rows):
                    result.failures.append(f"step {i}: (row {index} ...) out of range: query returned {len(rows)} rows")
                    return
                env[bind_name] = rows[index]
                check_env[bind_name] = rows[index]
    else:
        raise AssertionError(step)
