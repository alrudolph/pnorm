from collections.abc import Sequence
from typing import Any, Literal, Optional

from pnorm.pnorm_types import QueryContext


class BaseHook:
    def pre_query(
        self,
        query: str,
        query_params: Optional[dict[str, Any] | Sequence[dict[str, Any]]] = None,
        query_context: Optional[QueryContext] = None,
    ) -> None: ...

    def post_query(
        self,
        result_type: Literal["success", "error"],
        rows_returned: int,
        batch_size: int = 1,
    ) -> None: ...

    def on_exception(self, exception: Exception) -> None: ...
