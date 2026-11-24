import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    is_published INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS buttons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
                    target_page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
                    label TEXT NOT NULL
                );
                """
            )

    def create_project(self, owner_id: int, title: str) -> tuple[int, int]:
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO projects (owner_id, title) VALUES (?, ?)",
                (owner_id, title),
            )
            project_id = int(cursor.lastrowid)
            page_cursor = connection.execute(
                "INSERT INTO pages (project_id, title) VALUES (?, ?)",
                (project_id, "Страница 1"),
            )
            return project_id, int(page_cursor.lastrowid)

    def list_projects(self, owner_id: int) -> list[sqlite3.Row]:
        with self._connection() as connection:
            return connection.execute(
                "SELECT * FROM projects WHERE owner_id = ? ORDER BY id DESC",
                (owner_id,),
            ).fetchall()

    def get_project(self, project_id: int, owner_id: int | None = None) -> sqlite3.Row | None:
        with self._connection() as connection:
            if owner_id is None:
                return connection.execute(
                    "SELECT * FROM projects WHERE id = ?", (project_id,)
                ).fetchone()
            return connection.execute(
                "SELECT * FROM projects WHERE id = ? AND owner_id = ?",
                (project_id, owner_id),
            ).fetchone()

    def set_project_title(self, project_id: int, owner_id: int, title: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE projects SET title = ? WHERE id = ? AND owner_id = ?",
                (title, project_id, owner_id),
            )
            return cursor.rowcount == 1

    def set_published(self, project_id: int, owner_id: int, is_published: bool) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE projects SET is_published = ? WHERE id = ? AND owner_id = ?",
                (int(is_published), project_id, owner_id),
            )
            return cursor.rowcount == 1

    def delete_project(self, project_id: int, owner_id: int) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM projects WHERE id = ? AND owner_id = ?",
                (project_id, owner_id),
            )
            return cursor.rowcount == 1

    def list_pages(self, project_id: int) -> list[sqlite3.Row]:
        with self._connection() as connection:
            return connection.execute(
                "SELECT * FROM pages WHERE project_id = ? ORDER BY id",
                (project_id,),
            ).fetchall()

    def get_page(self, project_id: int, page_id: int) -> sqlite3.Row | None:
        with self._connection() as connection:
            return connection.execute(
                "SELECT * FROM pages WHERE id = ? AND project_id = ?",
                (page_id, project_id),
            ).fetchone()

    def add_page(self, project_id: int, title: str) -> int:
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO pages (project_id, title) VALUES (?, ?)",
                (project_id, title),
            )
            return int(cursor.lastrowid)

    def add_page_with_button(
        self, project_id: int, source_page_id: int, title: str, label: str
    ) -> int | None:
        with self._connection() as connection:
            source_page = connection.execute(
                "SELECT id FROM pages WHERE id = ? AND project_id = ?",
                (source_page_id, project_id),
            ).fetchone()
            if source_page is None:
                return None
            cursor = connection.execute(
                "INSERT INTO pages (project_id, title) VALUES (?, ?)",
                (project_id, title),
            )
            target_page_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO buttons (source_page_id, target_page_id, label)
                VALUES (?, ?, ?)
                """,
                (source_page_id, target_page_id, label),
            )
            return target_page_id

    def delete_page(self, project_id: int, page_id: int) -> bool:
        with self._connection() as connection:
            start_page = connection.execute(
                "SELECT id FROM pages WHERE project_id = ? ORDER BY id LIMIT 1",
                (project_id,),
            ).fetchone()
            if start_page is None or start_page["id"] == page_id:
                return False
            cursor = connection.execute(
                "DELETE FROM pages WHERE id = ? AND project_id = ?",
                (page_id, project_id),
            )
            return cursor.rowcount == 1

    def set_page_body(self, project_id: int, page_id: int, body: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE pages SET body = ? WHERE id = ? AND project_id = ?",
                (body, page_id, project_id),
            )
            return cursor.rowcount == 1

    def set_page_title(self, project_id: int, page_id: int, title: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE pages SET title = ? WHERE id = ? AND project_id = ?",
                (title, page_id, project_id),
            )
            return cursor.rowcount == 1

    def add_button(
        self, project_id: int, source_page_id: int, target_page_id: int, label: str
    ) -> bool:
        with self._connection() as connection:
            pages = connection.execute(
                """
                SELECT id FROM pages
                WHERE project_id = ? AND id IN (?, ?)
                """,
                (project_id, source_page_id, target_page_id),
            ).fetchall()
            if {row["id"] for row in pages} != {source_page_id, target_page_id}:
                return False
            connection.execute(
                """
                INSERT INTO buttons (source_page_id, target_page_id, label)
                VALUES (?, ?, ?)
                """,
                (source_page_id, target_page_id, label),
            )
            return True

    def list_buttons(self, page_id: int) -> list[sqlite3.Row]:
        with self._connection() as connection:
            return connection.execute(
                """
                SELECT buttons.*, pages.title AS target_page_title
                FROM buttons
                JOIN pages ON pages.id = buttons.target_page_id
                WHERE buttons.source_page_id = ?
                ORDER BY buttons.id
                """,
                (page_id,),
            ).fetchall()

    def get_button(
        self, project_id: int, source_page_id: int, button_id: int
    ) -> sqlite3.Row | None:
        with self._connection() as connection:
            return connection.execute(
                """
                SELECT buttons.*, pages.title AS target_page_title
                FROM buttons
                JOIN pages AS source_pages ON source_pages.id = buttons.source_page_id
                JOIN pages ON pages.id = buttons.target_page_id
                WHERE buttons.id = ?
                    AND buttons.source_page_id = ?
                    AND source_pages.project_id = ?
                """,
                (button_id, source_page_id, project_id),
            ).fetchone()

    def delete_button(self, project_id: int, source_page_id: int, button_id: int) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM buttons
                WHERE id = ?
                    AND source_page_id = ?
                    AND EXISTS (
                        SELECT 1 FROM pages
                        WHERE pages.id = buttons.source_page_id
                            AND pages.project_id = ?
                    )
                """,
                (button_id, source_page_id, project_id),
            )
            return cursor.rowcount == 1

    def get_page_for_public_flow(
        self, project_id: int, page_id: int
    ) -> tuple[sqlite3.Row, sqlite3.Row] | None:
        with self._connection() as connection:
            project = connection.execute(
                "SELECT * FROM projects WHERE id = ? AND is_published = 1",
                (project_id,),
            ).fetchone()
            page = connection.execute(
                "SELECT * FROM pages WHERE id = ? AND project_id = ?",
                (page_id, project_id),
            ).fetchone()
            if project is None or page is None:
                return None
            return project, page

    def get_project_start_page(self, project_id: int) -> sqlite3.Row | None:
        with self._connection() as connection:
            return connection.execute(
                "SELECT * FROM pages WHERE project_id = ? ORDER BY id LIMIT 1",
                (project_id,),
            ).fetchone()
