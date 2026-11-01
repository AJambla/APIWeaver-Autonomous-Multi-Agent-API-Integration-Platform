import inspect
from app.services.sandbox_runners.runner import _bind_arguments


def test_bind_arguments_with_order_data():
    def place_order(order_data: dict, confirm: bool = False):
        pass

    params = {}
    body = {"petId": 123, "quantity": 1}

    kwargs, missing = _bind_arguments(place_order, params, body)
    assert not missing
    assert kwargs.get("order_data") == body


def test_bind_arguments_with_user_input():
    def create_user(user_input: dict):
        pass

    kwargs, missing = _bind_arguments(create_user, {}, {"username": "alice"})
    assert not missing
    assert kwargs.get("user_input") == {"username": "alice"}


def test_bind_arguments_with_path_and_body():
    def update_pet(pet_id: int, pet_payload: dict):
        pass

    kwargs, missing = _bind_arguments(update_pet, {"pet_id": 42}, {"name": "fido"})
    assert not missing
    assert kwargs.get("pet_id") == 42
    assert kwargs.get("pet_payload") == {"name": "fido"}
