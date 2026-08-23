"""AST-based "does this module's actual code do X" checks — shared by the
A3/A3b "never infers" source-inspection tests.

Deliberately AST-based rather than a naive substring search over
`inspect.getsource(module)`: these modules' own docstrings *legitimately*
discuss `Derivation.INFERRED` and "implication" at length (explaining
*why* the rule holds), so a plain `"Derivation.INFERRED" not in source`
check would false-positive on prose that is describing the rule, not
violating it. Walking the parsed AST for real `Derivation.INFERRED`
attribute-access expressions and real `import ...implication...`
statements checks the code, not the comments about the code.
"""

from __future__ import annotations

import ast
import inspect
from types import ModuleType


def references_derivation_inferred(module: ModuleType) -> bool:
    """True if `module`'s actual code (not its docstrings/comments)
    contains a `Derivation.INFERRED` attribute-access expression
    anywhere."""
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "INFERRED"
            and isinstance(node.value, ast.Name)
            and node.value.id == "Derivation"
        ):
            return True
    return False


def imports_any_module_named(module: ModuleType, *, substring: str) -> bool:
    """True if `module`'s actual `import`/`from ... import` statements
    (not its docstrings/comments) name a module containing `substring`."""
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(substring in alias.name.lower() for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            if substring in node.module.lower():
                return True
    return False


__all__ = ["imports_any_module_named", "references_derivation_inferred"]
