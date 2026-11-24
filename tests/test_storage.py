import tempfile
import unittest
from pathlib import Path

from storage import Database


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "test.sqlite3")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_project_has_start_page_and_is_private_to_owner(self) -> None:
        project_id, page_id = self.database.create_project(10, "Мой сценарий")

        self.assertEqual(len(self.database.list_pages(project_id)), 1)
        self.assertIsNotNone(self.database.get_project(project_id, 10))
        self.assertIsNone(self.database.get_project(project_id, 20))
        self.assertEqual(self.database.get_project_start_page(project_id)["id"], page_id)

    def test_owner_can_rename_project_and_pages(self) -> None:
        project_id, start_page = self.database.create_project(10, "Старое название")
        target_page = self.database.add_page(project_id, "Старая страница")
        self.database.add_button(project_id, start_page, target_page, "Открыть")
        button_id = self.database.list_buttons(start_page)[0]["id"]

        self.assertFalse(self.database.set_project_title(project_id, 20, "Чужое имя"))
        self.assertTrue(self.database.set_project_title(project_id, 10, "Новое название"))
        self.assertFalse(self.database.set_page_title(project_id, target_page + 100, "Не найдена"))
        self.assertTrue(self.database.set_page_title(project_id, target_page, "Новая страница"))

        self.assertEqual(self.database.get_project(project_id)["title"], "Новое название")
        self.assertEqual(self.database.get_page(project_id, target_page)["title"], "Новая страница")
        self.assertEqual(self.database.get_button(project_id, start_page, button_id)["target_page_title"], "Новая страница")

    def test_public_flow_requires_published_project_and_valid_page(self) -> None:
        project_id, page_id = self.database.create_project(10, "Сценарий")

        self.assertIsNone(self.database.get_page_for_public_flow(project_id, page_id))
        self.assertTrue(self.database.set_published(project_id, 10, True))
        self.assertIsNotNone(self.database.get_page_for_public_flow(project_id, page_id))
        self.assertIsNone(self.database.get_page_for_public_flow(project_id, page_id + 100))

    def test_button_cannot_link_pages_from_another_project(self) -> None:
        first_project, first_page = self.database.create_project(10, "Первый")
        second_project, second_page = self.database.create_project(10, "Второй")

        self.assertFalse(
            self.database.add_button(first_project, first_page, second_page, "Перейти")
        )
        self.assertTrue(
            self.database.add_button(first_project, first_page, first_page, "Повторить")
        )

    def test_multiple_pages_and_buttons_keep_their_own_destinations(self) -> None:
        project_id, start_page = self.database.create_project(10, "Многостраничный сценарий")
        page_ids = [
            self.database.add_page(project_id, title)
            for title in ("Каталог", "Помощь", "Контакты")
        ]

        self.assertTrue(self.database.add_button(project_id, start_page, page_ids[0], "Каталог"))
        self.assertTrue(self.database.add_button(project_id, start_page, page_ids[1], "Поддержка"))
        self.assertTrue(self.database.add_button(project_id, start_page, page_ids[2], "Написать"))

        self.assertEqual(len(self.database.list_pages(project_id)), 4)
        buttons = self.database.list_buttons(start_page)
        self.assertEqual(
            [(button["label"], button["target_page_title"]) for button in buttons],
            [("Каталог", "Каталог"), ("Поддержка", "Помощь"), ("Написать", "Контакты")],
        )

    def test_create_page_as_button_target(self) -> None:
        project_id, source_page = self.database.create_project(10, "Сценарий")

        target_page = self.database.add_page_with_button(
            project_id, source_page, "Новая страница", "Перейти"
        )

        self.assertIsNotNone(target_page)
        self.assertEqual(
            [(button["label"], button["target_page_title"]) for button in self.database.list_buttons(source_page)],
            [("Перейти", "Новая страница")],
        )

    def test_create_button_target_page_rejects_source_from_another_project(self) -> None:
        project_id, _ = self.database.create_project(10, "Сценарий")
        other_project, other_page = self.database.create_project(10, "Другой")

        self.assertIsNone(
            self.database.add_page_with_button(project_id, other_page, "Не создавать", "Переход")
        )
        self.assertEqual(len(self.database.list_pages(project_id)), 1)

    def test_deleting_page_removes_incoming_and_outgoing_buttons_but_keeps_start_page(self) -> None:
        project_id, start_page = self.database.create_project(10, "Сценарий")
        page_to_delete = self.database.add_page(project_id, "Удалить")
        remaining_page = self.database.add_page(project_id, "Оставить")
        self.database.add_button(project_id, start_page, page_to_delete, "В удаляемую")
        self.database.add_button(project_id, page_to_delete, remaining_page, "Из удаляемой")
        self.database.add_button(project_id, start_page, remaining_page, "Сохранить")

        self.assertFalse(self.database.delete_page(project_id, start_page))
        self.assertTrue(self.database.delete_page(project_id, page_to_delete))
        self.assertIsNone(self.database.get_page(project_id, page_to_delete))
        self.assertEqual(
            [(button["label"], button["target_page_title"]) for button in self.database.list_buttons(start_page)],
            [("Сохранить", "Оставить")],
        )

    def test_delete_button_is_scoped_to_its_project_and_page(self) -> None:
        project_id, source_page = self.database.create_project(10, "Сценарий")
        target_page = self.database.add_page(project_id, "Цель")
        other_project, other_page = self.database.create_project(10, "Другой")
        self.database.add_button(project_id, source_page, target_page, "Удалить")
        button_id = self.database.list_buttons(source_page)[0]["id"]

        self.assertFalse(self.database.delete_button(other_project, other_page, button_id))
        self.assertEqual(len(self.database.list_buttons(source_page)), 1)
        self.assertTrue(self.database.delete_button(project_id, source_page, button_id))
        self.assertEqual(self.database.list_buttons(source_page), [])

    def test_delete_project_removes_its_pages_and_buttons_only_for_owner(self) -> None:
        project_id, start_page = self.database.create_project(10, "Удалить")
        target_page = self.database.add_page(project_id, "Страница")
        self.database.add_button(project_id, start_page, target_page, "Переход")
        other_project, other_page = self.database.create_project(10, "Оставить")

        self.assertFalse(self.database.delete_project(project_id, 20))
        self.assertIsNotNone(self.database.get_project(project_id))
        self.assertTrue(self.database.delete_project(project_id, 10))
        self.assertIsNone(self.database.get_project(project_id))
        self.assertIsNone(self.database.get_page(project_id, start_page))
        self.assertEqual(len(self.database.list_pages(other_project)), 1)
        self.assertEqual(self.database.list_buttons(other_page), [])


if __name__ == "__main__":
    unittest.main()
