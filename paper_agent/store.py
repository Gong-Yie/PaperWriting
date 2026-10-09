"""Local, atomic persistence of complete topic archives."""

from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from .models import TopicSession


class TopicNotFoundError(LookupError):
    """The requested local topic does not exist."""


class TopicStateError(ValueError):
    """The requested operation is incompatible with the topic's state."""


class TopicStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def save(self, session: TopicSession) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self.directory / f"{session.id}.json"
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.directory, delete=False
            ) as stream:
                temporary_path = Path(stream.name)
                stream.write(session.model_dump_json(indent=2))
            temporary_path.replace(destination)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def get(self, topic_id: UUID) -> TopicSession:
        path = self.directory / f"{topic_id}.json"
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise TopicNotFoundError("没有找到该选题，请返回选题列表。") from exc
        return TopicSession.model_validate_json(content)

    def list_topics(self) -> list[TopicSession]:
        sessions = [
            TopicSession.model_validate_json(path.read_text(encoding="utf-8"))
            for path in self.directory.glob("*.json")
        ]
        return sorted(sessions, key=lambda item: item.created_at, reverse=True)
