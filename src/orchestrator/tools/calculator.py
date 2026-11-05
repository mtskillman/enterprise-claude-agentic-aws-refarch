"""Deterministic Math and Cloud Cost Calculator Tool."""

from __future__ import annotations

import ast
import operator
from typing import Any, Dict

from .base import BaseTool


class SafeCalculatorTool(BaseTool):
    """Safely evaluates deterministic arithmetic expressions without eval()."""

    name = "calculate_expression"
    description = (
        "Perform precise arithmetic calculations and financial/cost estimations. "
        "Supports addition (+), subtraction (-), multiplication (*), division (/), and powers (**)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The mathematical expression to evaluate (e.g. '1500 * 0.003 + 250').",
            }
        },
        "required": ["expression"],
    }

    _OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
    }

    def _eval(self, node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        elif isinstance(node, ast.BinOp):
            left = self._eval(node.left)
            right = self._eval(node.right)
            op_func = self._OPERATORS.get(type(node.op))
            if not op_func:
                raise ValueError(f"Unsupported operator: {type(node.op)}")
            return float(op_func(left, right))
        elif isinstance(node, ast.UnaryOp):
            operand = self._eval(node.operand)
            op_func = self._OPERATORS.get(type(node.op))
            if not op_func:
                raise ValueError(f"Unsupported operator: {type(node.op)}")
            return float(op_func(operand))
        else:
            raise ValueError(f"Unsupported AST node: {type(node)}")

    def execute(self, arguments: Dict[str, Any], tenant_id: str = "default") -> Dict[str, Any]:
        expr = arguments["expression"]
        try:
            tree = ast.parse(expr, mode="eval")
            result = self._eval(tree.body)
            return {"status": "success", "expression": expr, "result": result}
        except Exception as exc:
            return {"status": "error", "expression": expr, "error": str(exc)}
