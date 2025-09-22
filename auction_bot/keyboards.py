from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


menu_main = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="Я поставщик"), KeyboardButton(text="Я организатор")],
], resize_keyboard=True)


menu_supplier_unregistered = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="Регистрация")],
], resize_keyboard=True)

menu_supplier_registered = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="Активные тендеры")],
], resize_keyboard=True)

menu_organizer = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="Создать тендер"), KeyboardButton(text="Мои тендеры")],
    [KeyboardButton(text="История"), KeyboardButton(text="Управление доступом")],
], resize_keyboard=True)


menu_admin = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="Пользователи"), KeyboardButton(text="Одобрить тендер")],
    [KeyboardButton(text="Статус тендеров"), KeyboardButton(text="История")],
], resize_keyboard=True)


menu_participant = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Подать заявку")],
    ],
    resize_keyboard=True
)