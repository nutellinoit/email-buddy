"""
Pydantic response schemas for structured LLM output.
Used by Instructor to enforce validated responses from LLM calls.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .config import config


def _build_category_enum() -> type[Enum]:
    """Build a dynamic Enum from configured category names.

    Instructor serializes Enum fields as {"enum": ["spam", "newsletter", ...]}
    in the JSON schema, which constrains the LLM output to valid categories.
    """
    members = {name.upper(): name for name in config.category_names}
    return Enum("CategoryEnum", members, type=str)


CategoryEnum = _build_category_enum()


class EmailClassification(BaseModel):
    """Structured response for email classification."""

    model_config = ConfigDict(use_enum_values=True)

    category: CategoryEnum
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class LearningSummary(BaseModel):
    """Structured response for learning summary generation."""

    summary: str
