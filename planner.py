from typing import Any, Dict, List

class Planner:
    """Generate simple multi-step plans from user context."""

    def create_plan(self, context: str) -> List[Dict[str, Any]]:
        """Create a list of steps derived from the context string.

        The current implementation simply splits the context by periods and
        returns non-empty segments as sequential steps.
        """
        steps = []
        for idx, part in enumerate(context.split(".")):
            item = part.strip()
            if item:
                steps.append({"step": idx + 1, "action": item})
        if not steps:
            steps.append({"step": 1, "action": context.strip()})
        return steps
