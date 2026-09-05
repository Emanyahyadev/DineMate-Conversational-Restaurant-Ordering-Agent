"""Placeholder menu data. Swap for a real datastore when the menu goes live."""

MENU: list[dict] = [
    {"id": "m1", "name": "Margherita Pizza", "category": "Pizza", "price": 9.5, "tags": ["vegetarian"]},
    {"id": "m2", "name": "Pepperoni Pizza", "category": "Pizza", "price": 11.5, "tags": []},
    {"id": "m3", "name": "Chicken Alfredo", "category": "Pasta", "price": 12.0, "tags": []},
    {"id": "m4", "name": "Penne Arrabbiata", "category": "Pasta", "price": 10.0, "tags": ["vegan", "spicy"]},
    {"id": "m5", "name": "Caesar Salad", "category": "Salad", "price": 7.5, "tags": []},
    {"id": "m6", "name": "Garlic Bread", "category": "Sides", "price": 4.0, "tags": ["vegetarian"]},
    {"id": "m7", "name": "Tiramisu", "category": "Dessert", "price": 6.0, "tags": ["vegetarian"]},
    {"id": "m8", "name": "Fresh Lemonade", "category": "Drinks", "price": 3.5, "tags": ["vegan"]},
]

MENU_BY_ID = {item["id"]: item for item in MENU}
MENU_BY_NAME = {item["name"].lower(): item for item in MENU}
