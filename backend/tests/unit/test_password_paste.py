"""A pasted password with a stray space must still sign you in.

The live failure: the credentials were correct to the eye, but copying them out
of a message brought a trailing space along and the login returned 401 with no
way to see why. Whitespace at either end is a paste artefact, never intent.
"""

import pytest

from app.services.auth_service import normalise_password, validate_password
from app.services.errors import ValidationError

GOOD = "DineMate2026!Demo"


@pytest.mark.parametrize(
    "pasted",
    [
        GOOD,
        GOOD + " ",
        " " + GOOD,
        "  " + GOOD + "  ",
        GOOD + "\n",
        GOOD + "\r\n",
        "\t" + GOOD,
    ],
)
def test_surrounding_whitespace_is_ignored(pasted):
    assert normalise_password(pasted) == GOOD


def test_spaces_inside_a_passphrase_are_kept():
    """Length beats punctuation, so a passphrase must survive intact."""
    phrase = "correct horse battery staple"
    assert normalise_password(f"  {phrase}  ") == phrase


def test_a_password_of_only_whitespace_is_still_rejected():
    with pytest.raises(ValidationError):
        validate_password(normalise_password("              "))


def test_normalising_does_not_weaken_the_length_rule():
    """11 characters plus padding is still 11 characters."""
    with pytest.raises(ValidationError):
        validate_password(normalise_password("  short-pass  "))
