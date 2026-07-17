"""Agent-neutral knowledge access for SU Media AI Office."""

from dataclasses import dataclass
from pathlib import Path


KNOWLEDGE_CATEGORIES = (
    "company",
    "seo",
    "wordpress",
    "affiliate",
    "development",
)


@dataclass(frozen=True)
class KnowledgeDocument:
    """One indexed Markdown knowledge document."""

    title: str
    category: str
    path: Path
    content: str


class KnowledgeEngine:
    """Load, categorize, and search shared Markdown knowledge.

    The engine only provides knowledge. It has no awareness of individual
    agents, their prompts, responsibilities, or decisions.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._documents: list[KnowledgeDocument] = []

    def initialize(self) -> int:
        """Ensure category folders exist and index all Markdown documents."""
        self.root.mkdir(parents=True, exist_ok=True)
        for category in KNOWLEDGE_CATEGORIES:
            (self.root / category).mkdir(parents=True, exist_ok=True)

        documents: list[KnowledgeDocument] = []
        for path in sorted(self.root.rglob("*.md")):
            relative = path.relative_to(self.root)
            category = relative.parts[0] if len(relative.parts) > 1 else "general"
            content = path.read_text(encoding="utf-8")
            title = self._extract_title(content, path.stem)
            documents.append(
                KnowledgeDocument(
                    title=title,
                    category=category,
                    path=path,
                    content=content,
                )
            )
        self._documents = documents
        return len(documents)

    def get_documents(self) -> list[KnowledgeDocument]:
        """Return every indexed document."""
        return list(self._documents)

    def get_documents_by_category(
        self, category: str
    ) -> list[KnowledgeDocument]:
        """Return documents in one case-insensitive category."""
        normalized = category.strip().lower()
        return [
            document
            for document in self._documents
            if document.category.lower() == normalized
        ]

    def search(self, keyword: str) -> list[KnowledgeDocument]:
        """Return documents whose title or content contains a keyword."""
        normalized = keyword.strip().casefold()
        if not normalized:
            return []
        return [
            document
            for document in self._documents
            if normalized in document.title.casefold()
            or normalized in document.content.casefold()
        ]

    def get_company_rules(self) -> str:
        """Return all company knowledge as one readable rules document."""
        return "\n\n".join(
            document.content.strip()
            for document in self.get_documents_by_category("company")
        )

    @staticmethod
    def _extract_title(content: str, fallback: str) -> str:
        for line in content.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return fallback.replace("_", " ").replace("-", " ").title()
