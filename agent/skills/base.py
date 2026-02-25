"""Base abstractions for all skills.

Defines:
- parameter schema
- runtime parameter validation
- execution callback mechanism
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


class SkillValidationError(ValueError):
    pass


@dataclass
class SkillParameter:
    name: str
    param_type: type
    required: bool = True
    default: Any = None
    description: str = ""


class BaseSkill(ABC):
    """Abstract base class every skill implementation must extend."""

    name: str = "base"
    description: str = ""
    parameters: List[SkillParameter] = []

    def __init__(self) -> None:
        self._callbacks: List[Callable[[str, Dict[str, Any]], None]] = []

    def add_result_callback(self, callback: Callable[[str, Dict[str, Any]], None]) -> None:
        self._callbacks.append(callback)

    def validate_parameters(self, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Validate params against declarative `parameters` schema."""
        params = params or {}
        normalized: Dict[str, Any] = {}

        allowed_keys = {param.name for param in self.parameters}
        unknown = set(params.keys()) - allowed_keys
        if unknown:
            raise SkillValidationError(f"Skill '{self.name}' received unknown parameters: {sorted(unknown)}")

        for param in self.parameters:
            if param.name not in params:
                if param.required and param.default is None:
                    raise SkillValidationError(
                        f"Skill '{self.name}' missing required parameter '{param.name}'"
                    )
                normalized[param.name] = param.default
                continue

            value = params[param.name]
            if value is not None and not isinstance(value, param.param_type):
                raise SkillValidationError(
                    f"Skill '{self.name}' parameter '{param.name}' expects {param.param_type.__name__}, "
                    f"got {type(value).__name__}"
                )
            normalized[param.name] = value

        return normalized

    async def run(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Validate then execute skill, then trigger result callbacks."""
        normalized = self.validate_parameters(params)
        result = await self.execute(normalized)
        for callback in self._callbacks:
            callback(self.name, result)
        return result

    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError
