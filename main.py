import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv

from storage import Database

load_dotenv()
logging.basicConfig(level=logging.INFO)

router = Router()
database = Database(os.getenv("BOT_DB_PATH", "data/bot.sqlite3"))


class CreateProject(StatesGroup):
    title = State()


class EditPage(StatesGroup):
    title = State()
    body = State()


class EditProject(StatesGroup):
    title = State()


class AddPage(StatesGroup):
    title = State()


class AddButton(StatesGroup):
    label = State()
    target = State()


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать сценарий", callback_data="create")],
            [InlineKeyboardButton(text="📂 Мои сценарии", callback_data="projects")],
        ]
    )


def project_menu(project_id: int, is_published: bool) -> InlineKeyboardMarkup:
    publish_text = "⏸ Снять с публикации" if is_published else "🚀 Опубликовать"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📄 Страницы", callback_data=f"pages:{project_id}")],
            [InlineKeyboardButton(text="➕ Добавить страницу", callback_data=f"addpage:{project_id}")],
            [InlineKeyboardButton(text="✏️ Изменить название сценария", callback_data=f"editprojecttitle:{project_id}")],
            [InlineKeyboardButton(text=publish_text, callback_data=f"publish:{project_id}")],
            [InlineKeyboardButton(text="🔗 Получить ссылку", callback_data=f"link:{project_id}")],
            [InlineKeyboardButton(text="🗑 Удалить сценарий", callback_data=f"deleteproject:{project_id}")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="home")],
        ]
    )


def page_menu(
    project_id: int, page_id: int, buttons: list, is_start_page: bool
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"🗑 Удалить кнопку {index}",
                callback_data=f"deletebtn:{project_id}:{page_id}:{button['id']}",
            )
        ]
        for index, button in enumerate(buttons, start=1)
    ]
    rows.extend(
        [
            [InlineKeyboardButton(text="✏️ Изменить текст", callback_data=f"edit:{project_id}:{page_id}")],
            [InlineKeyboardButton(text="✏️ Изменить название страницы", callback_data=f"editpagetitle:{project_id}:{page_id}")],
            [InlineKeyboardButton(text="🔘 Добавить кнопку перехода", callback_data=f"addbtn:{project_id}:{page_id}")],
        ]
    )
    if not is_start_page:
        rows.append(
            [InlineKeyboardButton(text="🗑 Удалить страницу", callback_data=f"deletepage:{project_id}:{page_id}")]
        )
    rows.append([InlineKeyboardButton(text="⬅️ К страницам", callback_data=f"pages:{project_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def owned_project(user_id: int, project_id: int):
    return database.get_project(project_id, user_id)


async def show_project(message: Message, project_id: int, user_id: int) -> None:
    project = owned_project(user_id, project_id)
    if project is None:
        await message.answer("Сценарий не найден.")
        return
    status = "опубликован" if project["is_published"] else "не опубликован"
    await message.answer(
        f"Сценарий: {project['title']}\nСтатус: {status}",
        reply_markup=project_menu(project_id, bool(project["is_published"])),
    )


async def show_page(message: Message, project_id: int, page_id: int) -> None:
    page = database.get_page(project_id, page_id)
    if page is None:
        await message.answer("Страница не найдена.")
        return
    body = page["body"] or "(Текст пока не задан)"
    buttons = database.list_buttons(page_id)
    start_page = database.get_project_start_page(project_id)
    is_start_page = start_page is not None and int(start_page["id"]) == page_id
    button_list = "\n".join(
        f"{index}. {button['label']} → {button['target_page_title']}"
        for index, button in enumerate(buttons, start=1)
    ) or "нет"
    await message.answer(
        f"Страница: {page['title']}\n\n{body[:500]}\n\nКнопки перехода: {button_list}",
        reply_markup=page_menu(project_id, page_id, buttons, is_start_page),
    )


def pages_keyboard(project_id: int, pages: list) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=page["title"], callback_data=f"page:{project_id}:{page['id']}")]
        for page in pages
    ]
    rows.append([InlineKeyboardButton(text="⬅️ К сценарию", callback_data=f"project:{project_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_public_page(
    message: Message, project_id: int, page_id: int, *, edit: bool = False
) -> None:
    result = database.get_page_for_public_flow(project_id, page_id)
    if result is None:
        text = "Этот сценарий недоступен."
        if edit:
            await message.edit_text(text)
        else:
            await message.answer(text)
        return

    _, page = result
    buttons = database.list_buttons(page_id)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=button["label"],
                    callback_data=f"go:{project_id}:{button['target_page_id']}",
                )
            ]
            for button in buttons
        ]
    ) if buttons else None
    text = page["body"] or page["title"]
    if edit:
        try:
            await message.edit_text(text, reply_markup=keyboard)
        except TelegramBadRequest as error:
            if "message is not modified" not in error.message:
                raise
    else:
        await message.answer(text, reply_markup=keyboard)


@router.message(CommandStart())
async def start(message: Message, command: CommandObject) -> None:
    args = command.args or ""
    if args.startswith("flow_"):
        try:
            project_id = int(args[5:])
        except ValueError:
            await message.answer("Ссылка на сценарий некорректна.")
            return
        project = database.get_project(project_id)
        page = database.get_project_start_page(project_id)
        if project is None or not project["is_published"] or page is None:
            await message.answer("Сценарий не найден или ещё не опубликован.")
            return
        await render_public_page(message, project_id, int(page["id"]))
        return
    await message.answer(
        "Привет! Здесь можно собрать простой сценарий бота из страниц и кнопок.",
        reply_markup=main_menu(),
    )


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_menu())


@router.callback_query(F.data == "home")
async def home(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text("Главное меню:", reply_markup=main_menu())


@router.callback_query(F.data == "create")
async def create_project(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CreateProject.title)
    await callback.answer()
    await callback.message.answer("Введите название сценария. Для отмены отправьте /cancel.")


@router.message(CreateProject.title)
async def receive_project_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title or len(title) > 60:
        await message.answer("Название должно содержать от 1 до 60 символов.")
        return
    project_id, page_id = database.create_project(message.from_user.id, title)
    await state.set_state(EditPage.body)
    await state.update_data(project_id=project_id, page_id=page_id)
    await message.answer("Сценарий создан. Теперь отправьте текст его первой страницы.")


@router.callback_query(F.data == "projects")
async def list_projects(callback: CallbackQuery) -> None:
    projects = database.list_projects(callback.from_user.id)
    await callback.answer()
    if not projects:
        await callback.message.answer("У вас пока нет сценариев.", reply_markup=main_menu())
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=project["title"], callback_data=f"project:{project['id']}")]
            for project in projects
        ] + [[InlineKeyboardButton(text="🏠 В меню", callback_data="home")]]
    )
    await callback.message.answer("Ваши сценарии:", reply_markup=keyboard)


@router.callback_query(F.data.startswith("project:"))
async def open_project(callback: CallbackQuery) -> None:
    project_id = int(callback.data.split(":")[1])
    project = owned_project(callback.from_user.id, project_id)
    await callback.answer()
    if project is None:
        await callback.message.answer("Сценарий не найден.")
        return
    status = "опубликован" if project["is_published"] else "не опубликован"
    await callback.message.answer(
        f"Сценарий: {project['title']}\nСтатус: {status}",
        reply_markup=project_menu(project_id, bool(project["is_published"])),
    )


@router.callback_query(F.data.startswith("editprojecttitle:"))
async def edit_project_title(callback: CallbackQuery, state: FSMContext) -> None:
    project_id = int(callback.data.split(":")[1])
    if owned_project(callback.from_user.id, project_id) is None:
        await callback.answer("Сценарий не найден.", show_alert=True)
        return
    await state.set_state(EditProject.title)
    await state.update_data(project_id=project_id)
    await callback.answer()
    await callback.message.answer(
        "Введите новое название сценария, не длиннее 60 символов. Для отмены отправьте /cancel."
    )


@router.message(EditProject.title)
async def receive_project_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title or len(title) > 60:
        await message.answer("Название должно содержать от 1 до 60 символов.")
        return
    project_id = int((await state.get_data())["project_id"])
    if not database.set_project_title(project_id, message.from_user.id, title):
        await state.clear()
        await message.answer("Сценарий не найден.")
        return
    await state.clear()
    await message.answer("Название сценария изменено.")
    await show_project(message, project_id, message.from_user.id)


@router.callback_query(F.data.startswith("deleteproject:"))
async def confirm_delete_project(callback: CallbackQuery) -> None:
    project_id = int(callback.data.split(":")[1])
    project = owned_project(callback.from_user.id, project_id)
    if project is None:
        await callback.answer("Сценарий не найден.", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, удалить навсегда", callback_data=f"confirmdelproject:{project_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"canceldeleteproject:{project_id}")],
        ]
    )
    await callback.answer()
    await callback.message.answer(
        f"Удалить сценарий «{project['title']}» вместе со всеми страницами и кнопками? "
        "Опубликованная ссылка перестанет работать.",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("confirmdelproject:"))
async def delete_project(callback: CallbackQuery) -> None:
    project_id = int(callback.data.split(":")[1])
    if not database.delete_project(project_id, callback.from_user.id):
        await callback.answer("Сценарий не найден.", show_alert=True)
        return
    await callback.answer("Сценарий удалён.")
    await callback.message.answer("Сценарий удалён.", reply_markup=main_menu())


@router.callback_query(F.data.startswith("canceldeleteproject:"))
async def cancel_delete_project(callback: CallbackQuery) -> None:
    project_id = int(callback.data.split(":")[1])
    if owned_project(callback.from_user.id, project_id) is None:
        await callback.answer("Сценарий не найден.", show_alert=True)
        return
    await callback.answer("Удаление отменено.")
    await show_project(callback.message, project_id, callback.from_user.id)


@router.callback_query(F.data.startswith("pages:"))
async def list_pages(callback: CallbackQuery) -> None:
    project_id = int(callback.data.split(":")[1])
    if owned_project(callback.from_user.id, project_id) is None:
        await callback.answer("Сценарий не найден.", show_alert=True)
        return
    pages = database.list_pages(project_id)
    await callback.answer()
    await callback.message.answer(
        "Выберите страницу:",
        reply_markup=pages_keyboard(project_id, pages),
    )


@router.callback_query(F.data.startswith("page:"))
async def open_page(callback: CallbackQuery) -> None:
    _, project_id_text, page_id_text = callback.data.split(":")
    project_id, page_id = int(project_id_text), int(page_id_text)
    if owned_project(callback.from_user.id, project_id) is None:
        await callback.answer("Сценарий не найден.", show_alert=True)
        return
    await callback.answer()
    await show_page(callback.message, project_id, page_id)


@router.callback_query(F.data.startswith("edit:"))
async def edit_page(callback: CallbackQuery, state: FSMContext) -> None:
    _, project_id_text, page_id_text = callback.data.split(":")
    project_id, page_id = int(project_id_text), int(page_id_text)
    if owned_project(callback.from_user.id, project_id) is None or database.get_page(project_id, page_id) is None:
        await callback.answer("Страница не найдена.", show_alert=True)
        return
    await state.set_state(EditPage.body)
    await state.update_data(project_id=project_id, page_id=page_id)
    await callback.answer()
    await callback.message.answer("Отправьте новый текст страницы. Для отмены отправьте /cancel.")


@router.callback_query(F.data.startswith("editpagetitle:"))
async def edit_page_title(callback: CallbackQuery, state: FSMContext) -> None:
    _, project_text, page_text = callback.data.split(":")
    project_id, page_id = int(project_text), int(page_text)
    if owned_project(callback.from_user.id, project_id) is None or database.get_page(project_id, page_id) is None:
        await callback.answer("Страница не найдена.", show_alert=True)
        return
    await state.set_state(EditPage.title)
    await state.update_data(project_id=project_id, page_id=page_id)
    await callback.answer()
    await callback.message.answer(
        "Введите новое название страницы, не длиннее 60 символов. Для отмены отправьте /cancel."
    )


@router.message(EditPage.title)
async def receive_page_title_edit(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title or len(title) > 60:
        await message.answer("Название должно содержать от 1 до 60 символов.")
        return
    data = await state.get_data()
    project_id, page_id = int(data["project_id"]), int(data["page_id"])
    if owned_project(message.from_user.id, project_id) is None:
        await state.clear()
        await message.answer("Сценарий не найден.")
        return
    if not database.set_page_title(project_id, page_id, title):
        await state.clear()
        await message.answer("Страница не найдена.")
        return
    await state.clear()
    await message.answer("Название страницы изменено.")
    await show_page(message, project_id, page_id)


@router.message(EditPage.body)
async def receive_page_body(message: Message, state: FSMContext) -> None:
    body = (message.text or "").strip()
    if not body or len(body) > 4000:
        await message.answer("Текст страницы должен содержать от 1 до 4000 символов.")
        return
    data = await state.get_data()
    project_id, page_id = int(data["project_id"]), int(data["page_id"])
    if not database.set_page_body(project_id, page_id, body):
        await state.clear()
        await message.answer("Страница не найдена.")
        return
    await state.clear()
    await message.answer("Текст сохранён.")
    await show_page(message, project_id, page_id)


@router.callback_query(F.data.startswith("addpage:"))
async def add_page(callback: CallbackQuery, state: FSMContext) -> None:
    project_id = int(callback.data.split(":")[1])
    if owned_project(callback.from_user.id, project_id) is None:
        await callback.answer("Сценарий не найден.", show_alert=True)
        return
    await state.set_state(AddPage.title)
    await state.set_data({"project_id": project_id})
    await callback.answer()
    await callback.message.answer("Введите название новой страницы. Для отмены отправьте /cancel.")


@router.message(AddPage.title)
async def receive_page_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title or len(title) > 60:
        await message.answer("Название должно содержать от 1 до 60 символов.")
        return
    data = await state.get_data()
    project_id = int(data["project_id"])
    pending_button_label = data.get("pending_button_label")
    if pending_button_label is not None:
        page_id = database.add_page_with_button(
            project_id,
            int(data["source_page_id"]),
            title,
            str(pending_button_label),
        )
        if page_id is None:
            await state.clear()
            await message.answer("Не удалось создать страницу и кнопку перехода.")
            return
        prompt = "Страница создана, кнопка ведёт на неё. Теперь отправьте текст страницы."
    else:
        page_id = database.add_page(project_id, title)
        prompt = "Страница создана. Теперь отправьте её текст."
    await state.set_state(EditPage.body)
    await state.set_data({"project_id": project_id, "page_id": page_id})
    await message.answer(prompt)


@router.callback_query(F.data.startswith("targetnew:"))
async def add_button_target_page(callback: CallbackQuery, state: FSMContext) -> None:
    _, project_text, source_text = callback.data.split(":")
    project_id, source_page_id = int(project_text), int(source_text)
    data = await state.get_data()
    if (
        owned_project(callback.from_user.id, project_id) is None
        or await state.get_state() != AddButton.target.state
        or int(data.get("project_id", -1)) != project_id
        or int(data.get("source_page_id", -1)) != source_page_id
    ):
        await callback.answer("Начните создание кнопки заново.", show_alert=True)
        return
    await state.set_data(
        {
            "project_id": project_id,
            "source_page_id": source_page_id,
            "pending_button_label": str(data["label"]),
        }
    )
    await state.set_state(AddPage.title)
    await callback.answer()
    await callback.message.answer(
        "Введите название новой страницы. Кнопка сразу будет вести на неё. "
        "Для отмены отправьте /cancel."
    )


@router.callback_query(F.data.startswith("deletepage:"))
async def confirm_delete_page(callback: CallbackQuery) -> None:
    _, project_text, page_text = callback.data.split(":")
    project_id, page_id = int(project_text), int(page_text)
    page = database.get_page(project_id, page_id)
    start_page = database.get_project_start_page(project_id)
    if owned_project(callback.from_user.id, project_id) is None or page is None:
        await callback.answer("Страница не найдена.", show_alert=True)
        return
    if start_page is not None and int(start_page["id"]) == page_id:
        await callback.answer("Стартовую страницу удалить нельзя.", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, удалить", callback_data=f"confirmdelpage:{project_id}:{page_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"canceldeletepage:{project_id}:{page_id}")],
        ]
    )
    await callback.answer()
    await callback.message.answer(
        f"Удалить страницу «{page['title']}»? Все кнопки с неё и на неё тоже будут удалены.",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("confirmdelpage:"))
async def delete_page(callback: CallbackQuery) -> None:
    _, project_text, page_text = callback.data.split(":")
    project_id, page_id = int(project_text), int(page_text)
    if owned_project(callback.from_user.id, project_id) is None:
        await callback.answer("Сценарий не найден.", show_alert=True)
        return
    if not database.delete_page(project_id, page_id):
        await callback.answer("Не удалось удалить страницу.", show_alert=True)
        return
    await callback.answer("Страница удалена.")
    pages = database.list_pages(project_id)
    await callback.message.answer(
        "Страница и связанные с ней кнопки удалены. Остальные страницы:",
        reply_markup=pages_keyboard(project_id, pages),
    )


@router.callback_query(F.data.startswith("canceldeletepage:"))
async def cancel_delete_page(callback: CallbackQuery) -> None:
    _, project_text, page_text = callback.data.split(":")
    project_id, page_id = int(project_text), int(page_text)
    if owned_project(callback.from_user.id, project_id) is None:
        await callback.answer("Сценарий не найден.", show_alert=True)
        return
    await callback.answer("Удаление отменено.")
    await show_page(callback.message, project_id, page_id)


@router.callback_query(F.data.startswith("addbtn:"))
async def add_button(callback: CallbackQuery, state: FSMContext) -> None:
    _, project_id_text, page_id_text = callback.data.split(":")
    project_id, page_id = int(project_id_text), int(page_id_text)
    if owned_project(callback.from_user.id, project_id) is None or database.get_page(project_id, page_id) is None:
        await callback.answer("Страница не найдена.", show_alert=True)
        return
    pages = database.list_pages(project_id)
    if not pages:
        await callback.answer("Сначала создайте страницу.", show_alert=True)
        return
    await state.set_state(AddButton.label)
    await state.update_data(project_id=project_id, source_page_id=page_id)
    await callback.answer()
    await callback.message.answer("Введите подпись кнопки перехода.")


@router.message(AddButton.label)
async def receive_button_label(message: Message, state: FSMContext) -> None:
    label = (message.text or "").strip()
    if not label or len(label) > 48:
        await message.answer("Подпись должна содержать от 1 до 48 символов.")
        return
    await state.update_data(label=label)
    data = await state.get_data()
    project_id = int(data["project_id"])
    source_page_id = int(data["source_page_id"])
    pages = database.list_pages(project_id)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=page["title"],
                    callback_data=f"target:{project_id}:{source_page_id}:{page['id']}",
                )
            ]
            for page in pages
        ] + [
            [
                InlineKeyboardButton(
                    text="➕ Создать страницу",
                    callback_data=f"targetnew:{project_id}:{source_page_id}",
                )
            ]
        ]
    )
    await state.set_state(AddButton.target)
    await message.answer("Куда должна вести кнопка?", reply_markup=keyboard)


@router.callback_query(F.data.startswith("target:"))
async def select_button_target(callback: CallbackQuery, state: FSMContext) -> None:
    _, project_text, source_text, target_text = callback.data.split(":")
    project_id, source_page_id, target_page_id = map(int, (project_text, source_text, target_text))
    project = owned_project(callback.from_user.id, project_id)
    data = await state.get_data()
    if await state.get_state() != AddButton.target.state:
        await callback.answer("Сначала введите подпись кнопки.", show_alert=True)
        return
    if (
        project is None
        or int(data.get("project_id", -1)) != project_id
        or int(data.get("source_page_id", -1)) != source_page_id
    ):
        await state.clear()
        await callback.answer("Сначала начните создание кнопки заново.", show_alert=True)
        return
    label = str(data["label"])
    if not database.add_button(project_id, source_page_id, target_page_id, label):
        await callback.answer("Не удалось добавить кнопку.", show_alert=True)
        return
    await state.clear()
    await callback.answer("Кнопка добавлена.")
    await show_page(callback.message, project_id, source_page_id)


@router.callback_query(F.data.startswith("deletebtn:"))
async def confirm_delete_button(callback: CallbackQuery) -> None:
    _, project_text, source_text, button_text = callback.data.split(":")
    project_id, source_page_id, button_id = map(int, (project_text, source_text, button_text))
    if owned_project(callback.from_user.id, project_id) is None:
        await callback.answer("Сценарий не найден.", show_alert=True)
        return
    button = database.get_button(project_id, source_page_id, button_id)
    if button is None:
        await callback.answer("Кнопка не найдена.", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, удалить", callback_data=f"confirmdelbtn:{project_id}:{source_page_id}:{button_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"canceldeletebtn:{project_id}:{source_page_id}")],
        ]
    )
    await callback.answer()
    await callback.message.answer(
        f"Удалить кнопку «{button['label']}» → «{button['target_page_title']}»?",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("confirmdelbtn:"))
async def delete_button(callback: CallbackQuery) -> None:
    _, project_text, source_text, button_text = callback.data.split(":")
    project_id, source_page_id, button_id = map(int, (project_text, source_text, button_text))
    if owned_project(callback.from_user.id, project_id) is None:
        await callback.answer("Сценарий не найден.", show_alert=True)
        return
    if not database.delete_button(project_id, source_page_id, button_id):
        await callback.answer("Кнопка не найдена.", show_alert=True)
        return
    await callback.answer("Кнопка удалена.")
    await show_page(callback.message, project_id, source_page_id)


@router.callback_query(F.data.startswith("canceldeletebtn:"))
async def cancel_delete_button(callback: CallbackQuery) -> None:
    _, project_text, source_text = callback.data.split(":")
    project_id, source_page_id = int(project_text), int(source_text)
    if owned_project(callback.from_user.id, project_id) is None:
        await callback.answer("Сценарий не найден.", show_alert=True)
        return
    await callback.answer("Удаление отменено.")
    await show_page(callback.message, project_id, source_page_id)


@router.callback_query(F.data.startswith("publish:"))
async def toggle_publish(callback: CallbackQuery) -> None:
    project_id = int(callback.data.split(":")[1])
    project = owned_project(callback.from_user.id, project_id)
    if project is None:
        await callback.answer("Сценарий не найден.", show_alert=True)
        return
    published = not bool(project["is_published"])
    database.set_published(project_id, callback.from_user.id, published)
    await callback.answer("Сценарий опубликован." if published else "Публикация снята.")
    await show_project(callback.message, project_id, callback.from_user.id)


@router.callback_query(F.data.startswith("link:"))
async def get_link(callback: CallbackQuery) -> None:
    project_id = int(callback.data.split(":")[1])
    project = owned_project(callback.from_user.id, project_id)
    if project is None:
        await callback.answer("Сценарий не найден.", show_alert=True)
        return
    await callback.answer()
    if not project["is_published"]:
        await callback.message.answer("Сначала опубликуйте сценарий.")
        return
    bot_info = await callback.bot.get_me()
    await callback.message.answer(
        f"Ссылка на сценарий:\nhttps://t.me/{bot_info.username}?start=flow_{project_id}"
    )


@router.callback_query(F.data.startswith("go:"))
async def follow_button(callback: CallbackQuery) -> None:
    _, project_text, page_text = callback.data.split(":")
    project_id, page_id = int(project_text), int(page_text)
    await callback.answer()
    await render_public_page(callback.message, project_id, page_id, edit=True)


async def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("Укажите BOT_TOKEN в файле .env или переменных окружения.")
    bot = Bot(token=token)
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(router)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
