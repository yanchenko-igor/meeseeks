"""User model with manual validation — target for refactoring to pydantic."""


class User:
    def __init__(self, name: str, email: str, age: int):
        if not name or not isinstance(name, str):
            raise ValueError("Name must be a non-empty string")
        if not email or "@" not in email:
            raise ValueError("Invalid email address")
        if not isinstance(age, int) or age < 0 or age > 150:
            raise ValueError("Age must be an integer between 0 and 150")

        self.name = name
        self.email = email
        self.age = age

    def greet(self) -> str:
        return f"Hello, I'm {self.name}!"

    def is_adult(self) -> bool:
        return self.age >= 18

    def to_dict(self) -> dict:
        return {"name": self.name, "email": self.email, "age": self.age}

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        return cls(name=data["name"], email=data["email"], age=data["age"])

    def __repr__(self) -> str:
        return f"User(name={self.name!r}, email={self.email!r}, age={self.age})"
