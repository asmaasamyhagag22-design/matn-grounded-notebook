from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Strict, immutable base for every public contract value."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class VersionedContract(ContractModel):
    schema_version: Literal[1] = 1
