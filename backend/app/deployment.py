"""Deployment preflight.

Every problem here has the same shape: the app starts perfectly, and then fails
in the browser in a way that looks like something else. A cross-site cookie the
browser silently drops presents as "login does nothing"; a default JWT secret
presents as nothing at all until someone forges a token. Better to say so at
startup, once, in words that name the setting to change.

Called from the lifespan hook. In production an incoherent configuration stops
the app; elsewhere it is a warning, because local development legitimately runs
with the insecure defaults.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from app.config import Settings

INSECURE_JWT_SECRET = "dev-only-insecure-secret-change-me-in-production!"
INSECURE_INTERNAL_SECRET = "dev-internal-secret"


def check_deployment(settings: Settings) -> list[str]:
    """Return the configuration problems worth refusing to start over."""
    problems: list[str] = []

    # --- cookies reaching the browser at all -----------------------------
    if settings.cookie_samesite == "none" and not settings.cookie_secure:
        problems.append(
            "COOKIE_SAMESITE=none requires COOKIE_SECURE=true - browsers reject "
            "SameSite=None cookies sent without Secure, so nobody can sign in."
        )

    api_site = _site(settings.public_api_url)
    cross_site = [
        origin
        for origin in settings.cors_origins
        if _site(origin) and api_site and _site(origin) != api_site
    ]
    if cross_site and settings.cookie_samesite != "none":
        problems.append(
            f"CORS allows {cross_site} but COOKIE_SAMESITE={settings.cookie_samesite!r}. "
            "A frontend on another origin never sends a Lax/Strict cookie, so every "
            "request arrives unauthenticated. Set COOKIE_SAMESITE=none and "
            "COOKIE_SECURE=true, or serve the frontend through the API's own origin."
        )

    if any(o.startswith("http://") and "localhost" not in o for o in settings.cors_origins):
        problems.append(
            "CORS_ORIGINS contains a plaintext http:// origin. Credentialed "
            "requests must be https in production."
        )

    if "*" in settings.cors_origins:
        problems.append(
            "CORS_ORIGINS cannot be '*' while credentials are allowed; name the "
            "frontend origins explicitly."
        )

    # --- secrets ----------------------------------------------------------
    if settings.jwt_secret == INSECURE_JWT_SECRET:
        problems.append("JWT_SECRET is still the development default.")
    if settings.internal_secret == INSECURE_INTERNAL_SECRET:
        problems.append("INTERNAL_SECRET is still the development default.")
    if not settings.cookie_secure:
        problems.append("COOKIE_SECURE=false sends session cookies over plaintext.")

    # --- databases --------------------------------------------------------
    if "neon.tech" in settings.postgres_url and "-pooler" not in settings.postgres_url:
        problems.append(
            "The Neon URL is the direct endpoint. Use the -pooler host: a "
            "serverless or multi-worker deployment opens far more connections "
            "than the direct endpoint allows."
        )
    if settings.mongodb_url.startswith("mongodb://localhost"):
        problems.append("MONGODB_URL still points at localhost.")
    if not settings.deepseek_api_key:
        problems.append("No LLM API key is set; the agent cannot answer anything.")

    return problems


# Suffixes under which each label is its own site. An approximation of the
# public suffix list, holding the hosts a deployment of this app plausibly uses:
# two apps on *.vercel.app are cross-site to each other, whereas api.example.com
# and app.example.com are not. Getting this wrong in the permissive direction
# would advise weakening cookies that did not need weakening, so the list errs
# towards naming the hosts we actually deploy on.
_MULTI_LABEL_SUFFIXES = (
    "vercel.app",
    "netlify.app",
    "pages.dev",
    "github.io",
    "onrender.com",
    "fly.dev",
    "railway.app",
    "azurewebsites.net",
    "herokuapp.com",
    "co.uk",
    "com.pk",
    "org.uk",
)


def _site(url: str) -> str:
    """The registrable domain, which is what SameSite compares.

    Ports are ignored on purpose: localhost:3000 and localhost:8000 are
    different origins but the same site, so a Lax cookie travels between them
    perfectly well and warning about it would be wrong.
    """
    host = urlsplit(url).netloc.lower().rsplit("@", 1)[-1]
    host = host.rsplit(":", 1)[0] if not host.endswith("]") else host
    if not host or host in ("localhost", "127.0.0.1", "::1"):
        return host

    labels = host.split(".")
    if len(labels) <= 2:
        return host
    for suffix in _MULTI_LABEL_SUFFIXES:
        if host.endswith("." + suffix):
            keep = len(suffix.split(".")) + 1
            return ".".join(labels[-keep:])
    return ".".join(labels[-2:])
