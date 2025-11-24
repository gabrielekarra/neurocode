__version__ = "0.2.0"

from .api import (
    BuildIRResult,
    CheckResult,
    EmbeddingsNotFoundError,
    ExplainResult,
    IRNotFoundError,
    NeurocodeError,
    NeurocodeProject,
    PatchApplyResult,
    PatchPlan,
    SearchResult,
    StatusResult,
    SymbolNotFoundError,
    open_project,
)

__all__ = [
    "__version__",
    "NeurocodeError",
    "IRNotFoundError",
    "EmbeddingsNotFoundError",
    "SymbolNotFoundError",
    "CheckResult",
    "ExplainResult",
    "BuildIRResult",
    "StatusResult",
    "SearchResult",
    "PatchPlan",
    "PatchApplyResult",
    "open_project",
    "NeurocodeProject",
]
