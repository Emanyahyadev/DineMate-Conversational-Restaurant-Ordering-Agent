"""When a broken stream may be retried, and when it must not be.

The provider drops the stream often enough that a retry is worth having. The
question is whether running the turn again could repeat something the customer
would be charged for - and the answer turns on whether the attempt's writes
were rolled back, not on which tools it happened to call.
"""

from app.agent.orchestrator import _is_retryable


def test_a_rolled_back_attempt_is_retried():
    assert _is_retryable([], rolled_back=True) is True


def test_an_attempt_whose_writes_survived_is_never_retried():
    """Without a rollback the dish is already in the cart; a second run doubles it."""
    assert _is_retryable([], rolled_back=False) is False


def test_a_turn_that_already_showed_text_is_never_retried():
    """Retrying would stitch a second reply onto the half-written first one."""
    assert _is_retryable(["Sure, we "], rolled_back=True) is False
    assert _is_retryable(["Sure, we "], rolled_back=False) is False


def test_a_failure_after_add_to_cart_is_still_retryable():
    """The common case, and the one that was wrongly blocked.

    A multi-dish order spends most of its time part-way through the adds, so
    this is exactly where the provider tends to break. The rollback is what
    makes it safe - see the docstring on `_is_retryable`.
    """
    assert _is_retryable([], rolled_back=True) is True


def test_the_rollback_guarantee_still_holds():
    """The safety argument depends on no service committing on its own.

    If a service ever starts committing, a rolled-back attempt would no longer
    be clean and the retry above would double a customer's order.
    """
    import inspect

    from app.services import cart_service, order_service

    for module in (cart_service, order_service):
        source = inspect.getsource(module)
        assert "session.commit()" not in source, (
            f"{module.__name__} commits on its own; a retried turn could now "
            "repeat a cart change. Revisit _is_retryable before allowing this."
        )
