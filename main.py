import asyncio
import os
import html
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from typing import Callable, Dict, Any, Awaitable
import database

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# Читаем один или несколько ID админов через запятую из .env
raw_admins = os.getenv("ADMIN_ID", "")
ADMIN_IDS = [admin_id.strip() for admin_id in raw_admins.split(",") if admin_id.strip()]
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "hellteenmid")

bot = Bot(token=TOKEN)
dp = Dispatcher()

CANCEL_TEXT = "❌ Отменить заполнение"

# === КЛАВИАТУРЫ ДЛЯ АНКЕТЫ ===
cancel_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=CANCEL_TEXT)]],
    resize_keyboard=True
)

skills_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🌱 Начальный"), KeyboardButton(text="⚡ Средний"), KeyboardButton(text="🔥 Продвинутый")],
        [KeyboardButton(text=CANCEL_TEXT)]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

yes_no_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✅ Да"), KeyboardButton(text="❌ Нет")],
        [KeyboardButton(text="🤔 Затрудняюсь ответить")],
        [KeyboardButton(text=CANCEL_TEXT)]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

rm_kb = ReplyKeyboardRemove()


# === ПРОВЕРКА БАНА ===
class BanMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[types.Update, Dict[str, Any]], Awaitable[Any]],
        event: types.Update,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if user and database.is_user_banned(user.id):
            return
        return await handler(event, data)

dp.update.middleware(BanMiddleware())


# === СОСТОЯНИЯ АНКЕТЫ (FSM) ===
class Form(StatesGroup):
    role_id = State()
    role_name = State()
    sub_role_id = State()
    name = State()
    pronouns = State()
    age = State()
    timezone = State()
    experience = State()
    skills = State()
    composer_genres = State()
    duration = State()
    tz = State()
    role_specific = State()
    goals = State()
    deadlines = State()
    price = State()
    portfolio = State()


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
async def safe_delete_message(message: types.Message):
    """Безопасное удаление сообщения (не падает, если сообщению > 48 часов)."""
    try:
        await message.delete()
    except TelegramBadRequest:
        try:
            await message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass


async def safe_callback_answer(callback: types.CallbackQuery, text: str = None, show_alert: bool = False):
    """Безопасный ответ на callback (не падает, если запрос устарел)."""
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except TelegramBadRequest:
        pass


def build_admin_app_kb(app_id: int, user_id: int, username: str) -> InlineKeyboardMarkup:
    clean_username = username if username and username != "none" else "None"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"app_approve_{app_id}_{user_id}_{clean_username}"),
            InlineKeyboardButton(text="❌ Отказать", callback_data=f"app_reject_{app_id}_{user_id}")
        ],
        [
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"app_delete_{app_id}_{user_id}"),
            InlineKeyboardButton(text="🚫 Забанить", callback_data=f"ban_{user_id}")
        ]
    ])


def format_admin_app_text(app_id, role_name, sub_name, user_name, user_id, username, form_text) -> str:
    sub_text = f" ({html.escape(sub_name)})" if sub_name else ""
    user_link = f"@{html.escape(username)}" if username and username != "none" else f"<a href='tg://user?id={user_id}'>Профиль</a>"
    return (
        f"📥 <b>АНКЕТА #{app_id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💼 <b>Направление:</b> {html.escape(role_name.capitalize())}{sub_text}\n"
        f"👤 <b>Кандидат:</b> {html.escape(user_name or 'Без имени')} ({user_link} | <code>{user_id}</code>)\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"{form_text}"
    )


# === АДМИН-ПАНЕЛЬ ===
@dp.message(F.text == "/admin")
async def admin_panel(message: types.Message):
    if str(message.from_user.id) not in ADMIN_IDS:
        return
    apps = database.get_new_applications()
    if not apps:
        await message.answer("📭 <b>Новых неразобранных анкет пока нет.</b>", parse_mode="HTML")
        return

    await message.answer(f"📂 <b>Неразобранных анкет: {len(apps)}</b>", parse_mode="HTML")
    for app in apps:
        app_id, form_text, role_name, user_name, user_id, username, sub_role_id = app
        sub_name = database.get_sub_role_name(sub_role_id)
        text = format_admin_app_text(app_id, role_name, sub_name, user_name, user_id, username, form_text)
        kb = build_admin_app_kb(app_id, user_id, username)
        await message.answer(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)


@dp.callback_query(F.data.startswith("app_"))
async def handle_application(callback: types.CallbackQuery):
    if str(callback.from_user.id) not in ADMIN_IDS:
        await safe_callback_answer(callback, "У вас нет прав администратора.", show_alert=True)
        return

    try:
        data = callback.data.split("_")
        action, app_id, user_id = data[1], int(data[2]), data[3]
        username = "_".join(data[4:]) if len(data) > 4 else None

        open_app_ids = [a[0] for a in database.get_new_applications()]
        if app_id not in open_app_ids:
            await safe_callback_answer(callback, "Эту анкету уже обработал второй админ!", show_alert=True)
            try:
                await callback.message.edit_text(
                    callback.message.html_text + "\n\nℹ️ <b>Анкета уже была обработана другим администратором.</b>",
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            except TelegramBadRequest:
                pass
            return

        # Отвечаем на callback сразу, чтобы не истёк таймаут Telegram
        await safe_callback_answer(callback, "Действие выполнено!")

        admin_tag = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.first_name

        if action == "approve":
            database.update_application_status(app_id, 1)
            user_mention = f"@{username}" if username and username != "None" else f"ID {user_id}"

            approver_contact = callback.from_user.username or ADMIN_USERNAME
            contact_info = (
                f"Напишите администратору: @{approver_contact}"
                if not username or username == "None"
                else "Мы напишем вам в личные сообщения в ближайшее время!"
            )
            try:
                await bot.send_message(
                    user_id,
                    f"🎉 <b>Поздравляем! Ваша заявка в команду «If You Die» одобрена!</b>\n\n"
                    f"Мы ознакомились с вашей анкетой и будем рады поработать вместе.\n"
                    f"💬 {contact_info}",
                    parse_mode="HTML"
                )
            except (TelegramBadRequest, TelegramForbiddenError) as send_err:
                print(f"Не удалось отправить сообщение кандидату {user_id}: {send_err}")

            await callback.message.edit_text(
                callback.message.html_text + f"\n\n✅ <b>СТАТУС: ОДОБРЕНО ({user_mention}) — админ {admin_tag}</b>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )

        elif action == "reject":
            database.delete_application(app_id)
            try:
                await bot.send_message(
                    user_id,
                    "<b>Ответ по вашей заявке в проект «If You Die»</b>\n\n"
                    "Спасибо за интерес к нашей игре и уделенное время! К сожалению, сейчас мы не готовы "
                    "пригласить вас в команду. Не расстраивайтесь и желаем вам вдохновения в будущих проектах!",
                    parse_mode="HTML"
                )
            except (TelegramBadRequest, TelegramForbiddenError) as send_err:
                print(f"Не удалось отправить сообщение кандидату {user_id}: {send_err}")

            await callback.message.edit_text(
                callback.message.html_text + f"\n\n❌ <b>СТАТУС: ОТКЛОНЕНО — админ {admin_tag}</b>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )

        elif action == "delete":
            database.delete_application(app_id)
            try:
                await callback.message.delete()
            except TelegramBadRequest:
                await callback.message.edit_text(
                    callback.message.html_text + f"\n\n🗑 <b>СТАТУС: УДАЛЕНО — админ {admin_tag}</b>",
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )

    except Exception as e:
        print(f"Ошибка в админке: {e}")
        await safe_callback_answer(callback, "Произошла ошибка при обработке.", show_alert=True)


@dp.callback_query(F.data.startswith("ban_"))
async def ban_handler(callback: types.CallbackQuery):
    if str(callback.from_user.id) not in ADMIN_IDS:
        await safe_callback_answer(callback, "У вас нет прав администратора.", show_alert=True)
        return

    user_id = callback.data.split("_")[1]
    database.ban_user(user_id)
    await safe_callback_answer(callback, "🚫 Пользователь заблокирован, его анкеты удалены!", show_alert=True)
    try:
        await callback.message.edit_text(
            callback.message.html_text + "\n\n🚫 <b>ПОЛЬЗОВАТЕЛЬ ЗАБАНЕН</b>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    except TelegramBadRequest:
        pass


# === ГЛАВНОЕ МЕНЮ И НАВИГАЦИЯ ===
def get_main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤝 Вступить в команду", callback_data="menu_roles")],
        [
            InlineKeyboardButton(text="📖 О проекте", callback_data="menu_about"),
            InlineKeyboardButton(text="🌐 Наши соцсети", callback_data="menu_social")
        ],
        [
            InlineKeyboardButton(text="🎮 Джем-игра (Uninvited)", url="https://hellteen.itch.io/uninvited"),
            InlineKeyboardButton(text="🛠 Поддержка", url="https://t.me/hellteenmid")
        ]
    ])

def get_back_to_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="menu_main")]
    ])

def get_about_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Поиграть в Uninvited (Itch.io)", url="https://hellteen.itch.io/uninvited")],
        [InlineKeyboardButton(text="🤝 Подать заявку в команду", callback_data="menu_roles")],
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="menu_main")]
    ])

def get_roles_kb():
    roles = database.get_all_roles()
    role_emojis = {
        "художник": "🎨",
        "программист": "💻",
        "композитор": "🎵",
        "сценарист": "📜",
        "аниматор": "🎞"
    }
    kb = []
    for r_id, r_name in roles:
        emoji = "🔹"
        for key, emj in role_emojis.items():
            if key in r_name.lower():
                emoji = emj
                break
        kb.append([InlineKeyboardButton(text=f"{emoji} {r_name.capitalize()}", callback_data=f"role_info_{r_id}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад в меню", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

async def edit_menu_message(callback: types.CallbackQuery, text: str, kb: InlineKeyboardMarkup):
    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest:
        pass

PHOTO_FILE_ID = None

MAIN_MENU_TEXT = (
    "<b>Добро пожаловать в бот инди-проекта «If You Die»!</b>\n\n"
    "Мы разрабатываем атмосферную сюжетную игру на стыке драмы и психологического хоррора "
    "и ищем увлечённых людей в нашу команду.\n\n"
)

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    global PHOTO_FILE_ID
    await state.clear()
    photo_path = "iyd.png" if os.path.exists("iyd.png") else "iyd.jpg" if os.path.exists("iyd.jpg") else None

    if PHOTO_FILE_ID:
        await message.answer_photo(PHOTO_FILE_ID, caption=MAIN_MENU_TEXT, reply_markup=get_main_menu_kb(), parse_mode="HTML")
    elif photo_path:
        sent_msg = await message.answer_photo(types.FSInputFile(photo_path), caption=MAIN_MENU_TEXT, reply_markup=get_main_menu_kb(), parse_mode="HTML")
        PHOTO_FILE_ID = sent_msg.photo[-1].file_id
    else:
        await message.answer(MAIN_MENU_TEXT, reply_markup=get_main_menu_kb(), parse_mode="HTML")


@dp.callback_query(F.data == "menu_main")
async def menu_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_callback_answer(callback)
    await edit_menu_message(callback, MAIN_MENU_TEXT, get_main_menu_kb())


@dp.callback_query(F.data == "menu_about")
async def menu_about(callback: types.CallbackQuery):
    await safe_callback_answer(callback)
    text = (
        "<b>О проекте «If You Die»</b>\n\n"
        "<b>Жанр:</b> Приключение, драма, психологический хоррор.\n"
        "<b>Геймплей:</b> Передвижение по локациям (WASD), исследование мира, взаимодействие с предметами и диалоги.\n"
        "<b>Вдохновение:</b> <i>Hello Charlotte, OMORI, вселенная Okegom.</i>\n\n"
        "<blockquote><b>Сюжет:</b>\n"
        "Ши - воспитанник закрытого религиозного культа, мечтающий о свободе. "
        "Когда его лучший друг Кей оказывается на пороге «вознесения», Ши решает любой ценой спасти его.\n"
        "Пока приготовления к церемонии становятся всё более тревожными, времени на побег остаётся всё меньше. "
        "Однако не всякая вера ведёт к спасению... И действительно ли Кей хочет быть спасён?</blockquote>\n\n"
        "<b>Наши проекты:</b>\n"
        "У нас уже есть выпущенная на геймджеме мини-игра — <a href='https://hellteen.itch.io/uninvited'><b>Uninvited</b></a>, "
        "в которой как раз дебютировал главный герой нашей основной игры! Можете оценить её по кнопке ниже.\n\n"
        "<b>Текущий этап:</b> Набор команды, работа над скелетом сюжета, прописание сценария и работа над основными механиками."
    )
    await edit_menu_message(callback, text, get_about_kb())


@dp.callback_query(F.data == "menu_social")
async def menu_social(callback: types.CallbackQuery):
    await safe_callback_answer(callback)
    text = (
        "🌐 <b>Наши соцсети и ссылки</b>\n\n"
        "Следите за дневниками разработки, концепт-артами и новостями проекта:\n\n"
        "🔹 <b>Telegram-канал:</b> <a href='https://t.me/solace_games'>Solace Games</a>\n"
        "🔹 <b>TikTok:</b> <a href='https://www.tiktok.com/@solacegames0?_r=1&_t=ZS-9B4W2lx4LIq'>@solacegames0</a>\n"
        "🔹 <b>Itch.io (наша джем-игра):</b> <a href='https://hellteen.itch.io/uninvited'>Uninvited</a>"
    )
    await edit_menu_message(callback, text, get_back_to_main_kb())


@dp.callback_query(F.data == "menu_roles")
async def menu_roles(callback: types.CallbackQuery):
    await safe_callback_answer(callback)
    text = (
        "<b>Кого мы ищем в команду:</b>\n\n"
        "Нажмите на интересующую вас роль ниже, чтобы ознакомиться с задачами и заполнить анкету."
    )
    await edit_menu_message(callback, text, get_roles_kb())


@dp.callback_query(F.data.startswith("role_info_"))
async def show_role_info(callback: types.CallbackQuery):
    await safe_callback_answer(callback)
    role_id = int(callback.data.split("_")[2])
    role_name = database.get_role_name(role_id)
    desc = database.get_role_description(role_id)

    text = (
        f"💼 <b>Вакансия: {html.escape(role_name.capitalize())}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>О роли и задачах:</b>\n"
        f"<blockquote>{html.escape(desc)}</blockquote>\n\n"
        f"Готовы попробовать свои силы? Нажмите кнопку ниже, чтобы перейти к анкете!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Заполнить анкету", callback_data=f"role_apply_{role_id}")],
        [InlineKeyboardButton(text="🔙 К списку вакансий", callback_data="menu_roles")]
    ])
    await edit_menu_message(callback, text, kb)


@dp.callback_query(F.data.startswith("role_apply_"))
async def apply_role(callback: types.CallbackQuery, state: FSMContext):
    await safe_callback_answer(callback)
    role_id = int(callback.data.split("_")[2])
    role_name = database.get_role_name(role_id)
    await state.update_data(role_id=role_id, role_name=role_name)

    sub = database.get_sub_roles(role_id)
    if sub:
        kb_buttons = [[InlineKeyboardButton(text=f"{s[1].capitalize()}", callback_data=f"sub_{s[0]}")] for s in sub]
        kb_buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"role_info_{role_id}")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)

        desc_text = ""
        if "художник" in role_name.lower():
            desc_text = (
                "\n\n📌 <b>Кратко о направлениях:</b>\n"
                "• <b>Художник-фоновик:</b> Отрисовка задних фонов и окружения с учётом перспективы.\n"
                "• <b>Level-художник:</b> Проектирование и визуальное оформление игровых локаций.\n"
                "• <b>UI-художник:</b> Отрисовка интерфейса, диалоговых окон, кнопок и меню.\n"
                "• <b>Рендер-художник:</b> Полноценный покрас, работа со светом и тенями по готовым скетчам."
            )

        text = f"Вы выбрали направление: <b>{html.escape(role_name.capitalize())}</b>\n\n👇 Уточните вашу специализацию:{desc_text}"
        await edit_menu_message(callback, text, kb)
    else:
        await state.update_data(sub_role_id=None)
        await safe_delete_message(callback.message)
        await start_questions(callback.message, state)


@dp.callback_query(F.data.startswith("sub_"))
async def sub_role_selected(callback: types.CallbackQuery, state: FSMContext):
    await safe_callback_answer(callback)
    await state.update_data(sub_role_id=int(callback.data.split("_")[1]))
    await safe_delete_message(callback.message)
    await start_questions(callback.message, state)


# === ОБРАБОТЧИК ОТМЕНЫ АНКЕТЫ ===
@dp.message(F.text == CANCEL_TEXT)
async def cancel_form(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Заполнение анкеты отменено.", reply_markup=rm_kb)
    await cmd_start(message, state)


# === ШАГИ АНКЕТЫ ===
async def start_questions(message: types.Message, state: FSMContext):
    data = await state.get_data()
    role_title = data.get("role_name", "").capitalize()
    sub_id = data.get("sub_role_id")
    sub_title = f" ({database.get_sub_role_name(sub_id)})" if sub_id else ""

    await message.answer(
        f"📋 <b>Заполнение анкеты: {html.escape(role_title)}{html.escape(sub_title)}</b>\n"
        f"<i>Вы в любой момент можете прервать анкету кнопкой внизу экрана.</i>\n\n"
        f"<b>Как к вам можно обращаться?</b>",
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )
    await state.set_state(Form.name)

@dp.message(Form.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("<b>Ваши местоимения?</b>", reply_markup=cancel_kb, parse_mode="HTML")
    await state.set_state(Form.pronouns)

@dp.message(Form.pronouns)
async def process_pronouns(message: types.Message, state: FSMContext):
    await state.update_data(pronouns=message.text)
    await message.answer("<b>Ваш возраст?</b>", reply_markup=cancel_kb, parse_mode="HTML")
    await state.set_state(Form.age)

@dp.message(Form.age)
async def process_age(message: types.Message, state: FSMContext):
    await state.update_data(age=message.text)
    await message.answer("<b>Ваш часовой пояс?</b>", reply_markup=cancel_kb, parse_mode="HTML")
    await state.set_state(Form.timezone)

@dp.message(Form.timezone)
async def process_timezone(message: types.Message, state: FSMContext):
    await state.update_data(timezone=message.text)
    await message.answer("<b>Был ли у вас опыт работы в данной сфере? Опишите кратко:</b>", reply_markup=cancel_kb, parse_mode="HTML")
    await state.set_state(Form.experience)

@dp.message(Form.experience)
async def process_exp(message: types.Message, state: FSMContext):
    await state.update_data(experience=message.text)
    await message.answer("<b>Как вы оцениваете текущий уровень своих навыков?</b>", reply_markup=skills_kb, parse_mode="HTML")
    await state.set_state(Form.skills)

@dp.message(Form.skills)
async def process_skills(message: types.Message, state: FSMContext):
    await state.update_data(skills=message.text)
    data = await state.get_data()
    role = data.get("role_name", "").lower()

    if "композитор" in role:
        await message.answer("<b>В каких музыкальных жанрах и программах (DAW) вы работаете?</b>", reply_markup=cancel_kb, parse_mode="HTML")
        await state.set_state(Form.composer_genres)
    else:
        await message.answer("<b>Как долго вы планируете участвовать в проекте?</b>", reply_markup=cancel_kb, parse_mode="HTML")
        await state.set_state(Form.duration)

@dp.message(Form.composer_genres)
async def process_composer_genres(message: types.Message, state: FSMContext):
    await state.update_data(composer_genres=message.text)
    await message.answer("<b>Как долго вы планируете участвовать в проекте?</b>", reply_markup=cancel_kb, parse_mode="HTML")
    await state.set_state(Form.duration)

@dp.message(Form.duration)
async def process_duration(message: types.Message, state: FSMContext):
    await state.update_data(duration=message.text)
    data = await state.get_data()
    role = data.get("role_name", "").lower()

    if "сценарист" in role:
        await message.answer("<b>Какие цели вы преследуете в проекте?</b>\n<i>(Опыт / портфолио / заработок / другое — опишите)</i>", reply_markup=cancel_kb, parse_mode="HTML")
        await state.set_state(Form.goals)
    else:
        await message.answer("<b>Есть ли у вас опыт работы по чёткому техническому заданию (ТЗ)?</b>", reply_markup=yes_no_kb, parse_mode="HTML")
        await state.set_state(Form.tz)

@dp.message(Form.tz)
async def process_tz(message: types.Message, state: FSMContext):
    await state.update_data(tz=message.text)
    data = await state.get_data()

    role_name = data.get("role_name", "").lower()
    sub_id = data.get("sub_role_id")
    sub_name = (database.get_sub_role_name(sub_id) or "").lower() if sub_id else ""

    if "аниматор" in role_name:
        await message.answer(
            "<b>🎞 В каких программах и техниках анимации вы работаете?</b>\n"
            "<i>(Покадровая 2D, костная в Spine / DragonBones / Live2D, анимация напрямую в Unity и т.д.)</i>",
            reply_markup=cancel_kb,
            parse_mode="HTML"
        )
        await state.set_state(Form.role_specific)
    elif "программист" in role_name:
        await message.answer(
            "<b>Насколько уверенно вы работаете с Unity (2D) и C#?</b>\n"
            "<i>Расскажите, какие механики или системы вам уже приходилось реализовывать.</i>",
            reply_markup=cancel_kb,
            parse_mode="HTML"
        )
        await state.set_state(Form.role_specific)
    elif "фон" in sub_name:
        await message.answer(
            "<b>Сможете ли вы подстроиться под стиль основного художника и органично вписать окружение (фон)? </b>",
            reply_markup=cancel_kb,
            parse_mode="HTML"
        )
        await state.set_state(Form.role_specific)
    elif any(k in sub_name for k in ["лвл", "уровн", "lavel", "level"]):
        await message.answer(
            "<b>Был ли у вас опыт в отрисовке 2D-локаций/уровней (тайлсеты, пропсы)? Представляете, как строится сцена?</b>",
            reply_markup=cancel_kb,
            parse_mode="HTML"
        )
        await state.set_state(Form.role_specific)
    elif "рендер" in sub_name:
        await message.answer(
            "<b>Сможете ли вы подстраиваться под лайн и стиль другого художника при покрасе и рендере?</b>",
            reply_markup=yes_no_kb,
            parse_mode="HTML"
        )
        await state.set_state(Form.role_specific)
    elif "ui" in sub_name:
        await message.answer(
            "<b>Был ли опыт оформления игровых интерфейсов (меню, инвентарь, диалоговые окна) под заданную стилистику?</b>",
            reply_markup=cancel_kb,
            parse_mode="HTML"
        )
        await state.set_state(Form.role_specific)
    elif "скетч" in sub_name:
        await message.answer(
            "<b>Хотите работать над скетчами спрайтов, катсцен или всем вместе? Сможете ли подстроиться под стиль проекта?</b>",
            reply_markup=cancel_kb,
            parse_mode="HTML"
        )
        await state.set_state(Form.role_specific)
    else:
        await message.answer(
            "<b>Какие цели вы преследуете в проекте?</b>\n<i>(Получение опыта / портфолио / заработок / другое — опишите)</i>",
            reply_markup=cancel_kb,
            parse_mode="HTML"
        )
        await state.set_state(Form.goals)

@dp.message(Form.role_specific)
async def process_role_specific(message: types.Message, state: FSMContext):
    await state.update_data(role_specific=message.text)
    await message.answer(
        "<b>Какие вы ставите цели на данный проект?</b>\n<i>(Получение опыта / портфолио / заработок / другое — опишите)</i>",
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )
    await state.set_state(Form.goals)

@dp.message(Form.goals)
async def process_goals(message: types.Message, state: FSMContext):
    await state.update_data(goals=message.text)
    await message.answer("<b>Готовы ли вы соблюдать согласованные дедлайны?</b>", reply_markup=yes_no_kb, parse_mode="HTML")
    await state.set_state(Form.deadlines)

@dp.message(Form.deadlines)
async def process_deadlines(message: types.Message, state: FSMContext):
    await state.update_data(deadlines=message.text)
    await message.answer(
        "<b>Готовы ли вы неопределенное время работать на энтузиазме, за идею и ее продвижение?</b>\n<i>Укажите ваш прайс и финансовые ожидания от проекта, мы учтем.</i>",
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )
    await state.set_state(Form.price)

@dp.message(Form.price)
async def process_price(message: types.Message, state: FSMContext):
    await state.update_data(price=message.text)
    await message.answer(
        "<b>Прикрепите ссылку на ваше портфолио c примерами работ. (Если отсутствует - так и укажите)</b>\n"
        "<i>(ArtStation, Behance, GitHub, Google Диск, Telegram-канал и т.д.)</i>",
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )
    await state.set_state(Form.portfolio)

@dp.message(Form.portfolio)
async def process_portfolio(message: types.Message, state: FSMContext):
    await state.update_data(portfolio=message.text)
    data = await state.get_data()

    user_id = message.from_user.id
    username = message.from_user.username or "none"
    first_name = message.from_user.first_name or "Пользователь"

    database.ensure_user_exists(user_id, username, first_name)

    key_names = {
        "name": "👤 Имя",
        "pronouns": "🗣 Местоимения",
        "age": "🎂 Возраст",
        "timezone": "🕒 Часовой пояс",
        "experience": "📚 Опыт",
        "skills": "📊 Уровень навыков",
        "composer_genres": "🎵 Жанры и DAW",
        "duration": "⏳ Длительность участия",
        "tz": "📋 Опыт работы по ТЗ",
        "role_specific": "🎯 Профильный вопрос",
        "goals": "🧭 Цели",
        "deadlines": "⏰ Дедлайны",
        "price": "💳 Прайс",
        "portfolio": "🔗 Портфолио"
    }

    form_lines = []
    for k, rus_key in key_names.items():
        val = data.get(k)
        if val is not None:
            form_lines.append(f"• <b>{rus_key}:</b> {html.escape(str(val))}")

    form_text = "\n".join(form_lines)
    role_id = data["role_id"]
    sub_role_id = data.get("sub_role_id")
    role_name = data.get("role_name", "Неизвестно")

    database.save_application(user_id, role_id, sub_role_id, form_text)

    new_apps = database.get_new_applications()
    latest_app_id = new_apps[-1][0] if new_apps else 0
    sub_name = database.get_sub_role_name(sub_role_id)

    admin_card = format_admin_app_text(
        latest_app_id, role_name, sub_name, first_name, user_id, username, form_text
    )
    admin_kb = build_admin_app_kb(latest_app_id, user_id, username)

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🔔 <b>Поступила новая заявка!</b>\n\n{admin_card}",
                reply_markup=admin_kb,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception as e:
            print(f"Не удалось отправить уведомление админу {admin_id}: {e}")

    await message.answer("🎉 <b>Готово!</b>", reply_markup=rm_kb, parse_mode="HTML")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Вернуться в главное меню", callback_data="menu_main")]
    ])
    await message.answer(
        "<b>Ваша анкета успешно отправлена!</b>\n\n"
        "Спасибо за интерес к проекту <b>«If You Die»</b>. Мы внимательно изучим вашу заявку "
        "и пришлём ответ в ближайшее время!",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.clear()


async def main():
    logging.basicConfig(level=logging.INFO)
    try:
        for admin_id in ADMIN_IDS:
            database.unban_user(int(admin_id))
        print(f"✅ База подключена, админы ({', '.join(ADMIN_IDS)}) активны!")
    except Exception as e:
        print(f"❌ Ошибка базы данных: {e}")

    me = await bot.get_me()
    print(f"🚀 Бот запущен! Пиши /start сюда: @{me.username}")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())