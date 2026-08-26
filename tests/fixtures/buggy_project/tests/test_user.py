"""Tests for User model."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.user import User
import pytest


def test_user_creation():
    user = User(name="Alice", email="alice@example.com", age=30)
    assert user.name == "Alice"
    assert user.email == "alice@example.com"
    assert user.age == 30


def test_user_greet():
    user = User(name="Bob", email="bob@example.com", age=25)
    assert user.greet() == "Hello, I'm Bob!"


def test_user_is_adult():
    assert User(name="A", email="a@a.com", age=18).is_adult() is True
    assert User(name="A", email="a@a.com", age=17).is_adult() is False
    assert User(name="A", email="a@a.com", age=0).is_adult() is False


def test_user_to_dict():
    user = User(name="Alice", email="alice@example.com", age=30)
    assert user.to_dict() == {"name": "Alice", "email": "alice@example.com", "age": 30}


def test_user_from_dict():
    data = {"name": "Bob", "email": "bob@example.com", "age": 25}
    user = User.from_dict(data)
    assert user.name == "Bob"
    assert user.email == "bob@example.com"
    assert user.age == 25


def test_user_repr():
    user = User(name="Alice", email="alice@example.com", age=30)
    assert "Alice" in repr(user)


def test_invalid_name():
    with pytest.raises(ValueError):
        User(name="", email="a@a.com", age=30)


def test_invalid_email():
    with pytest.raises(ValueError):
        User(name="A", email="not-an-email", age=30)


def test_invalid_age():
    with pytest.raises(ValueError):
        User(name="A", email="a@a.com", age=-1)
    with pytest.raises(ValueError):
        User(name="A", email="a@a.com", age=151)
