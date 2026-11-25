from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class Skill:
    """A stored capability handed to a center or a petal.

    A skill is data, not code the user subclasses: a name, when to use it, and the
    instructions themselves. Users keep skills wherever they want (files, a database, a
    package...) and pass them to a center or petal by parameter or setter. FOAA imposes no
    storage location or registry (Constitution, Principle I).
    """

    name: str
    instructions: str
    description: str = ""
    source: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a skill needs a name")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @classmethod
    def from_text(cls, name: str, instructions: str, description: str = "") -> Skill:
        return cls(name=name, instructions=instructions.strip(), description=description)

    @classmethod
    def from_markdown(cls, path: str | Path) -> Skill:
        """Load a skill from a Markdown file, e.g. a ``SKILL.md``.

        Optional front matter (``---`` delimited, simple ``key: value`` lines) provides
        ``name`` and ``description``; everything else becomes metadata. Without a ``name``,
        the file's parent folder name (for ``SKILL.md``) or file stem is used.
        """
        file = Path(path)
        text = file.read_text(encoding="utf-8")
        front, body = _split_front_matter(text)
        default_name = file.parent.name if file.stem.upper() == "SKILL" else file.stem
        name = front.pop("name", default_name)
        description = front.pop("description", "")
        return cls(
            name=name,
            instructions=body.strip(),
            description=description,
            source=str(file),
            metadata=front,
        )

    def render(self) -> str:
        """How the skill is presented to the model inside the system prompt."""
        header = f"## Skill: {self.name}"
        if self.description:
            header += f"\nUse when: {self.description}"
        return f"{header}\n\n{self.instructions}"


def _split_front_matter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            front: dict[str, str] = {}
            for line in lines[1:index]:
                key, sep, value = line.partition(":")
                if sep and key.strip():
                    front[key.strip()] = value.strip().strip("\"'")
            return front, "\n".join(lines[index + 1 :])
    return {}, text
