"""Rules N1-N3: what may and may not be remembered."""
from app.services.memory_service import is_denied


def test_payment_details_denied():
    assert is_denied("Card number 4111 1111 1111 1111")
    assert is_denied("Their CVV is 123")
    assert is_denied("Prefers to pay by credit card ending 4242")


def test_identity_documents_denied():
    assert is_denied("Passport number X1234567")
    assert is_denied("SSN on file")


def test_precise_location_denied():
    assert is_denied("Lives at 42 Elm Street")


def test_health_data_denied_but_allergies_kept():
    assert is_denied("Takes medication for blood pressure")
    # Rule N3: food allergies are exactly the health-adjacent thing we do keep
    assert not is_denied("Allergic to peanuts")
    assert not is_denied("Has a severe shellfish allergy")


def test_ordinary_preferences_allowed():
    assert not is_denied("Vegetarian")
    assert not is_denied("Likes very spicy food")
    assert not is_denied("Usually orders the Margherita")


# --------------------------------------------------------- rule extraction
from app.services.memory_extract import extract  # noqa: E402


def _facts(message):
    return {(f["text"], f["kind"]) for f in extract(message)["facts"]}


def _prefs(message):
    return {p["text"] for p in extract(message)["preferences"]}


def test_name_is_captured_regardless_of_capitalisation():
    assert ("Prefers to be called Bilal", "name") in _facts("My name is Bilal")
    assert ("Prefers to be called Sana", "name") in _facts("call me Sana")


def test_allergy_stops_at_a_clause_boundary():
    """'allergic to peanuts and I am vegetarian' must not store the second
    clause as an allergen - a wrong memory shapes every later suggestion."""
    facts = _facts("I am allergic to peanuts and I am vegetarian.")
    assert ("Allergic to peanuts", "allergy") in facts
    assert not any("vegetarian" in text.lower() for text, _ in facts)


def test_a_list_of_allergens_becomes_separate_facts():
    facts = _facts("I am allergic to peanuts and shellfish")
    assert ("Allergic to peanuts", "allergy") in facts
    assert ("Allergic to shellfish", "allergy") in facts


def test_diet_and_allergy_are_both_read_from_one_sentence():
    message = "Hi, my name is Bilal. I am allergic to peanuts and I am vegetarian."
    assert ("Allergic to peanuts", "allergy") in _facts(message)
    assert ("Prefers to be called Bilal", "name") in _facts(message)
    assert "Vegetarian" in _prefs(message)


def test_a_one_off_is_not_durable():
    """US-23: today's order is not a standing preference."""
    assert _facts("I'll get a Coke for my friend today") == set()
    assert _prefs("I'll get a Coke for my friend today") == set()


def test_a_plain_question_stores_nothing():
    assert _facts("what biryani do you have?") == set()
    assert _prefs("what biryani do you have?") == set()


# ------------------------------------------------------------- dedupe keys
from app.services.memory_service import _dedupe_key  # noqa: E402


def test_two_phrasings_of_one_fact_share_a_key():
    """The rule pass and the model pass describe the same thing differently.
    Keyed on raw text the customer would see every fact twice."""
    assert _dedupe_key("Prefers to be called Amir", "name") == _dedupe_key(
        "The customer's name is Amir.", "name"
    )
    assert _dedupe_key("Vegetarian") == _dedupe_key(
        "The customer follows a vegetarian diet.", "dietary"
    )
    assert _dedupe_key("Allergic to peanuts", "allergy") == _dedupe_key(
        "Amir is allergic to peanuts.", "allergy"
    )


def test_peanut_does_not_collapse_into_nut():
    """Longest match wins, so a peanut allergy is not filed under 'nut'."""
    assert _dedupe_key("Allergic to peanuts", "allergy") == "allergy:peanut"
    assert _dedupe_key("Allergic to tree nuts", "allergy") == "allergy:tree nut"


def test_genuinely_different_facts_keep_different_keys():
    assert _dedupe_key("Likes spicy food") != _dedupe_key("Dislikes coriander")
    assert _dedupe_key("Allergic to dairy", "allergy") != _dedupe_key(
        "Allergic to shellfish", "allergy"
    )
