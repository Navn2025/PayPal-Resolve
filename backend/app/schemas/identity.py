"""Contracts and validation types for platform identity."""

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class Input(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True
    )


class AccountInput(Input):
    email: str = Field(
        min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
    )
    password: SecretStr = Field(min_length=12, max_length=256)


class Signup(AccountInput):
    workspace: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)


class OwnerAccount(AccountInput):
    name: str = Field(min_length=1, max_length=100)


class AcceptInvite(AccountInput):
    token: SecretStr
    name: str = Field(min_length=1, max_length=100)


class Invite(Input):
    email: str = Field(max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    role: str = Field(pattern=r"^(manager|finance|agent|viewer)$")


class StaffUpdate(Input):
    role: str = Field(pattern=r"^(owner|manager|finance|agent|viewer)$")
    active: bool
