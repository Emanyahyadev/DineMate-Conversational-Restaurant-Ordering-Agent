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
