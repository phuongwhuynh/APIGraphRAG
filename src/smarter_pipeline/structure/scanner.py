from pathlib import Path


class Scanner:
    """Scans a directory for Python files."""

    def __init__(self, root):
        self.root = Path(root)

    def files(self):
        return list(self.root.rglob("*.py"))
