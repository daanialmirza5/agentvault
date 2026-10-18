from __future__ import annotations

import threading
import time

from sqlalchemy import Engine, text

from app.core import db


def test_write_transaction_takes_the_lock_up_front(engine: Engine) -> None:
    """A second write_transaction must wait for the first to commit (BEGIN IMMEDIATE)."""
    first = db.session_factory()()
    second = db.session_factory()()
    order: list[str] = []
    try:
        with db.write_transaction(first):
            first.execute(text("SELECT 1"))

            def contender() -> None:
                with db.write_transaction(second):
                    order.append("second-acquired")

            t = threading.Thread(target=contender)
            t.start()
            time.sleep(0.3)
            order.append("first-releasing")
        t.join(timeout=10)
    finally:
        first.close()
        second.close()
    assert order == ["first-releasing", "second-acquired"]
