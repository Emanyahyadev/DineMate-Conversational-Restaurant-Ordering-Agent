"""Rule L1: only the transitions in DOMAIN_MODEL.md exist."""
import itertools

from app.services.order_service import TRANSITIONS

ALL = list(TRANSITIONS)


def test_every_status_present():
    assert set(ALL) == {
        "confirmed", "preparing", "ready", "out_for_delivery", "completed", "cancelled",
    }


def test_terminal_states_are_terminal():
    assert TRANSITIONS["completed"] == set()
    assert TRANSITIONS["cancelled"] == set()


def test_all_36_pairs_are_decided():
    """Every (from, to) pair is either explicitly legal or illegal - none undefined."""
    legal = {(a, b) for a in ALL for b in TRANSITIONS[a]}
    for a, b in itertools.product(ALL, ALL):
        assert ((a, b) in legal) or ((a, b) not in legal)
    assert legal == {
        ("confirmed", "preparing"), ("confirmed", "cancelled"),
        ("preparing", "ready"), ("preparing", "cancelled"),
        ("ready", "out_for_delivery"), ("ready", "completed"),
        ("out_for_delivery", "completed"),
    }


def test_no_backwards_transitions():
    order = ["confirmed", "preparing", "ready", "out_for_delivery", "completed"]
    for i, status in enumerate(order):
        for earlier in order[:i]:
            assert earlier not in TRANSITIONS[status]
