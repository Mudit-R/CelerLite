"""Deterministic jobs shared by the embedded and standalone workers."""


def _fail() -> None:
    raise RuntimeError("Intentional failure for the retry and dead-letter demo")


def register_demo_tasks() -> None:
    from celerlite.worker.worker import register_task

    register_task("celerlite.demo.add", lambda a, b: a + b)
    register_task("celerlite.demo.multiply", lambda a, b: a * b)
    register_task(
        "celerlite.demo.heavy_computation",
        lambda n=1000: sum(i * i for i in range(min(max(int(n), 0), 100_000))),
    )
    register_task("celerlite.demo.send_email", lambda to, subject: f"Simulated email to {to}: {subject}")
    register_task("celerlite.demo.failing_task", _fail)
