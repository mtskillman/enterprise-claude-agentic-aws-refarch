"""Base tool definition for Claude Agentic tool-use on Amazon Bedrock."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseTool(ABC):
    """Abstract base class for all agent tools."""

    name: str
    description: str
    input_schema: Dict[str, Any]

    def to_bedrock_spec(self) -> Dict[str, Any]:
        """Convert tool schema to Bedrock Converse API toolSpec format."""
        return {
            "toolSpec": {
                "name": self.name,
                "description": self.description,
                "inputSchema": {
                    "json": self.input_schema
                }
            }
        }

    @abstractmethod
    def execute(self, arguments: Dict[str, Any], tenant_id: str = "default") -> Dict[str, Any]:
        """Execute the tool with provided arguments and tenant isolation."""
        pass
