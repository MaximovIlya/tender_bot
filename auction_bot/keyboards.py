from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


menu_main = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="Я поставщик"), KeyboardButton(text="Я организатор")],
], resize_keyboard=True)


menu_supplier = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="Регистрация"), KeyboardButton(text="Активные тендеры")],
], resize_keyboard=True)


menu_organizer = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="Создать тендер"), KeyboardButton(text="Мои тендеры")],
    [KeyboardButton(text="Управление доступом")],
], resize_keyboard=True)


menu_admin = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="Пользователи"), KeyboardButton(text="Назначить роль")],
    [KeyboardButton(text="Одобрить тендер"), KeyboardButton(text="Статус тендеров")],
], resize_keyboard=True)