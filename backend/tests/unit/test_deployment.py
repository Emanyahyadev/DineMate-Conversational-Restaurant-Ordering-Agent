"""The deployment preflight.

Each of these is a real way the app can start cleanly and then be broken in the
browser, so they are asserted rather than written down in a runbook.
"""

import pytest

from app.config import Settings
from app.deployment import check_deployment


def prod(**overrides) -> Settings:
    """A production-shaped configuration with nothing wrong with it."""
    base = dict(
        environment="production",
        jwt_secret="a-real-secret-value-from-the-environment",
        internal_secret="another-real-secret",
        cookie_secure=True,
        cookie_samesite="none",
        cors_origins=["https://dinemate.vercel.app"],
        public_api_url="https://api.dinemate.app",
        postgres_url="postgresql+asyncpg://u:p@ep-x-pooler.neon.tech/db",
        mongodb_url="mongodb+srv://u:p@cluster0.mongodb.net/",
        deepseek_api_key="key",
    )
    return Settings(**{**base, **overrides})


def test_a_correct_production_configuration_has_nothing_to_say():
    assert check_deployment(prod()) == []


def test_a_vercel_frontend_on_another_origin_needs_samesite_none():
    """The Vercel case exactly: Lax cookies are never sent, so nobody stays
    signed in - and it looks like a login bug, not a config one."""
    problems = check_deployment(prod(cookie_samesite="lax"))
    assert any("COOKIE_SAMESITE" in p for p in problems)


def test_samesite_none_without_secure_is_rejected():
    problems = check_deployment(prod(cookie_samesite="none", cookie_secure=False))
    assert any("requires COOKIE_SECURE" in p for p in problems)


def test_a_same_origin_deployment_may_keep_lax():
    problems = check_deployment(
        prod(
            cookie_samesite="lax",
            cors_origins=["https://dinemate.app"],
            public_api_url="https://dinemate.app",
        )
    )
    assert problems == []


@pytest.mark.parametrize(
    "override, expected",
    [
        ({"jwt_secret": "dev-only-insecure-secret-change-me-in-production!"}, "JWT_SECRET"),
        ({"internal_secret": "dev-internal-secret"}, "INTERNAL_SECRET"),
        ({"cookie_secure": False, "cookie_samesite": "lax",
          "cors_origins": ["https://dinemate.app"],
          "public_api_url": "https://dinemate.app"}, "COOKIE_SECURE"),
        ({"mongodb_url": "mongodb://localhost:27018"}, "MONGODB_URL"),
        ({"deepseek_api_key": ""}, "LLM API key"),
        ({"cors_origins": ["*"], "public_api_url": ""}, "cannot be '*'"),
    ],
)
def test_each_unsafe_default_is_named(override, expected):
    problems = check_deployment(prod(**override))
    assert any(expected in p for p in problems), problems


def test_the_direct_neon_endpoint_is_flagged():
    """The pooled host is what survives more than one worker."""
    problems = check_deployment(
        prod(postgres_url="postgresql+asyncpg://u:p@ep-calm-pond.neon.tech/db")
    )
    assert any("-pooler" in p for p in problems)


def test_development_defaults_are_reported_but_do_not_stop_anything():
    """Local work legitimately runs insecure; the check only refuses in prod."""
    problems = check_deployment(Settings(environment="development"))
    assert problems, "the defaults are genuinely unsafe and should still be named"


@pytest.mark.parametrize(
    "api, frontend, cross",
    [
        # Same registrable domain: a Lax cookie travels fine.
        ("https://api.dinemate.com", "https://app.dinemate.com", False),
        ("http://localhost:8000", "http://localhost:3000", False),
        ("http://127.0.0.1:8000", "http://127.0.0.1:3001", False),
        # Genuinely different sites.
        ("https://api.dinemate.app", "https://dinemate.vercel.app", True),
        # ...including two apps under the same platform suffix.
        ("https://api-dinemate.vercel.app", "https://dinemate.vercel.app", True),
        ("https://api.dinemate.co.uk", "https://shop.dinemate.co.uk", False),
    ],
)
def test_same_site_is_judged_by_registrable_domain(api, frontend, cross):
    problems = check_deployment(
        prod(cookie_samesite="lax", public_api_url=api, cors_origins=[frontend])
    )
    flagged = any("COOKIE_SAMESITE" in p for p in problems)
    assert flagged is cross, problems
