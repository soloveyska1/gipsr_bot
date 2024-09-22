import os
import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters, ConversationHandler
)
from dotenv import load_dotenv
import pandas as pd
from datetime import datetime, timedelta
import json
from telegram_bot_calendar import DetailedTelegramCalendar

# Загрузка переменных окружения из файла .env
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID'))  # Укажите ваш Telegram ID в .env

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Токен бота не найден! Убедитесь, что он указан в файле .env")

if not ADMIN_CHAT_ID:
    raise ValueError("ID администратора не найден! Укажите ADMIN_CHAT_ID в файле .env")

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Изменение BASE_DIR на путь в домашней директории пользователя
BASE_DIR = os.path.join(os.path.expanduser("~"), "gipsr_bot", "Gipsr_Orders", "clients")

# Убедимся, что папка для клиентов и другие необходимые папки существуют
os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, 'feedbacks'), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, 'data'), exist_ok=True)  # Для хранения других данных, если необходимо

# Типы заказов и их описания
ORDER_TYPES = {
    'self': {
        'name': 'Самостоятельная работа',
        'description': '💡 Самостоятельная работа предполагает выполнение небольших заданий, контрольных или эссе.'
    },
    'course_theory': {
        'name': 'Курсовая работа (теоретическая)',
        'description': '📚 Теоретическая курсовая работа - исследование, не включающее эмпирическую часть.'
    },
    'course_empirical': {
        'name': 'Курсовая работа (теория + эмпирика)',
        'description': '🔬 Курсовая работа с эмпирической частью включает проведение исследований и анализ данных.'
    },
    'vkr': {
        'name': 'ВКР',
        'description': '🎓 Выпускная квалификационная работа - итоговый проект для завершения обучения.'
    },
    'master': {
        'name': 'Магистерская диссертация',
        'description': '🎓 Магистерская диссертация - глубокое исследование по выбранной теме для получения степени магистра.'
    }
}

# Словарь для хранения информации о рефералах
referrals = {}

# Словарь для хранения информации о заказах пользователей
user_orders = {}

# Словарь для хранения отзывов
feedbacks = []

# Список пользователей, взаимодействовавших с ботом
user_ids = set()

# Режимы цен (Hard Mode и Light Mode)
PRICING_MODES = {
    'hard': {
        'name': 'Hard Mode',
        'description': '🔹 Если до дедлайна меньше 7 дней, цена увеличивается на 30%.\n'
                       '🔹 Если до дедлайна от 8 до 14 дней, цена увеличивается на 15%.\n'
                       '🔹 Если до дедлайна более 14 дней, действует базовая стоимость.'
    },
    'light': {
        'name': 'Light Mode',
        'description': '🔹 Если до дедлайна меньше 2-3 дней, цена увеличивается на 30%.\n'
                       '🔹 Если до дедлайна 7 дней и более, действует базовая стоимость.'
    }
}

current_pricing_mode = 'light'  # По умолчанию Light Mode

# Состояния диалога
(
    START,
    SELECT_MAIN_MENU,
    SELECT_ORDER_TYPE,
    INPUT_TOPIC,
    SELECT_DEADLINE_DATE,
    SELECT_SUPERVISOR_OPTION,
    INPUT_SUPERVISOR,
    SELECT_PRACTICE_BASE_OPTION,
    INPUT_PRACTICE_BASE,
    INPUT_PLAN_CHOICE,
    INPUT_PLAN_TEXT,
    UPLOAD_PLAN,
    CALCULATE_PRICE,
    CONFIRM_ORDER,
    LEAVE_FEEDBACK,
    ADMIN_MENU,
    ADMIN_BROADCAST,
    ADMIN_UPDATE_PRICES,
    ADMIN_UPDATE_ORDER_STATUS,
    PROFILE_MENU,
    DELETE_ORDER_CONFIRMATION,
    REPEAT_ORDER,
    ADMIN_CHANGE_PRICING_MODE,
    SHOW_PRICE_LIST,
    SHOW_FAQ
) = range(25)

# Цены (хранятся в отдельном файле prices.json в директории data)
PRICES_FILE = os.path.join(os.path.dirname(__file__), 'data', 'prices.json')

def load_prices():
    with open(PRICES_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_prices(prices):
    with open(PRICES_FILE, 'w', encoding='utf-8') as f:
        json.dump(prices, f, ensure_ascii=False, indent=4)

# Инициализация цен
try:
    PRICES = load_prices()
except FileNotFoundError:
    PRICES = {
        'self': {'base': 1500},
        'course_theory': {'base': 7000},
        'course_empirical': {'base': 11000},
        'vkr': {'base': 32000},
        'master': {'base': 42000}
    }
    save_prices(PRICES)

# Функция расчёта цены с учётом дедлайна
def calculate_price(order_type_key, deadline_date):
    prices = PRICES.get(order_type_key, {'base': 0})
    base_price = prices.get('base', 0)

    # Расчёт дней до дедлайна
    days_left = (deadline_date - datetime.now()).days

    # Применение правил ценообразования в зависимости от текущего режима
    if current_pricing_mode == 'hard':
        if days_left <= 7:
            return int(base_price * 1.3)
        elif 8 <= days_left <= 14:
            return int(base_price * 1.15)
        else:
            return base_price
    elif current_pricing_mode == 'light':
        if days_left <= 3:
            return int(base_price * 1.3)
        elif days_left >= 7:
            return base_price
        else:
            return base_price  # Можно добавить дополнительные условия при необходимости
    else:
        return base_price  # На случай, если режим не распознан

# Настройка локализации календаря на русский язык
class MyTranslationCalendar(DetailedTelegramCalendar):
    def __init__(self, **kwargs):
        super().__init__(locale='ru', **kwargs)

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_ids.add(user.id)
    text = update.message.text
    args = text.split()

    # Проверка на реферальный код
    if len(args) > 1:
        referrer_id = args[1]
        if referrer_id != str(user.id):
            referrals[user.id] = referrer_id
            # Отправка уведомления рефереру
            await context.bot.send_message(
                chat_id=int(referrer_id),
                text=f"🎉 Ваш друг {user.first_name} присоединился по вашей реферальной ссылке!\n"
                     "За денежной выплатой обращайтесь сюда: @Thisissaymoon"
            )

    # Генерация персональной реферальной ссылки
    ref_link = f"https://t.me/{context.bot.username}?start={user.id}"
    context.user_data['ref_link'] = ref_link

    # Переходим к главному меню
    return await main_menu(update, context)

# Обработчик команды /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🆘 *Доступные команды:*\n\n"
        "/start — начать работу с ботом или вернуться в главное меню.\n"
        "/help — показать это сообщение с описанием команд.\n"
        "/feedback — оставить отзыв о нашей работе.\n"
        "\n"
        "Вы также можете использовать кнопки меню для навигации по боту."
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

# Обработчик главного меню
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    keyboard = [
        [InlineKeyboardButton("📝 Сделать заказ", callback_data='make_order')],
        [InlineKeyboardButton("💰 Прайс-лист", callback_data='price_list')],
        [InlineKeyboardButton("👤 Мой профиль", callback_data='profile')],
        [InlineKeyboardButton("📄 FAQ", callback_data='faq')],
        [InlineKeyboardButton("📞 Связаться с администратором", url='https://t.me/Thisissaymoon')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    menu_text = (
        f"Привет, {user.first_name}! 👋\n\n"
        "Я помогу вам заказать работу.\n\n"
        "Выберите нужный раздел:\n\n"
        "📝 *Сделать заказ* — оформить новый заказ на выполнение работы.\n"
        "💰 *Прайс-лист* — ознакомиться с ценами на услуги.\n"
        "👤 *Мой профиль* — информация о ваших заказах и рефералах.\n"
        "📄 *FAQ* — ответы на часто задаваемые вопросы.\n"
        "📞 *Связаться с администратором* — задать вопрос напрямую."
    )

    if update.callback_query:
        await update.callback_query.message.edit_text(
            menu_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            menu_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    return SELECT_MAIN_MENU

# Обработчик выбора в главном меню
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == 'make_order':
        return await select_order_type(update, context)
    elif choice == 'price_list':
        return await show_price_list(update, context)
    elif choice == 'profile':
        return await show_profile(update, context)
    elif choice == 'faq':
        return await show_faq(update, context)
    else:
        await query.message.reply_text("Неизвестный выбор. Пожалуйста, используйте кнопки для навигации.")
        return SELECT_MAIN_MENU

# Обработчик показа прайс-листа
async def show_price_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    price_list_text = "💰 *Прайс-лист:*\n\n"
    for key, value in PRICES.items():
        order_info = ORDER_TYPES.get(key, {'name': key})
        order_name = order_info['name']
        base_price = value.get('base', 0)
        price_list_text += f"- {order_name}: от {base_price} руб.\n"

    pricing_mode_info = PRICING_MODES.get(current_pricing_mode, {})
    price_list_text += "\n*Как формируется цена:*\n"
    price_list_text += pricing_mode_info.get('description', '')

    keyboard = [
        [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(price_list_text, parse_mode='Markdown', reply_markup=reply_markup)
    return SHOW_PRICE_LIST  # Возвращаем состояние

# Обработчик показа FAQ
async def show_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    faq_text = (
        "❓ *Часто задаваемые вопросы:*\n\n"
        "1️⃣ *Как оформить заказ?*\n"
        "Выберите тип работы, введите необходимые данные и подтвердите заказ.\n\n"
        "2️⃣ *Как рассчитывается стоимость?*\n"
        "Стоимость зависит от типа работы и срочности. Чем ближе дедлайн, тем выше цена.\n\n"
        "3️⃣ *Как я могу отследить статус своего заказа?*\n"
        "Используйте раздел 'Мой профиль', чтобы увидеть информацию о ваших заказах.\n\n"
        "4️⃣ *Как работает реферальная программа?*\n"
        "Приглашайте друзей по вашей реферальной ссылке и получайте бонусы.\n\n"
        "5️⃣ *Как оставить отзыв?*\n"
        "Используйте раздел 'Мой профиль' или команду /feedback, чтобы поделиться своим мнением.\n\n"
        "Если у вас есть другие вопросы, свяжитесь с администратором: @Thisissaymoon"
    )
    keyboard = [
        [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(faq_text, parse_mode='Markdown', reply_markup=reply_markup)
    return SHOW_FAQ  # Возвращаем состояние

# Обработчик возврата в главное меню
async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await main_menu(update, context)

# Обработчик выбора типа заказа
async def select_order_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
    else:
        query = update

    keyboard = [
        [InlineKeyboardButton("💡 Самостоятельная работа", callback_data='self')],
        [InlineKeyboardButton("📚 Курсовая (теоретическая)", callback_data='course_theory')],
        [InlineKeyboardButton("🔬 Курсовая (теория + эмпирика)", callback_data='course_empirical')],
        [InlineKeyboardButton("🎓 ВКР", callback_data='vkr')],
        [InlineKeyboardButton("🎓 Магистерская диссертация", callback_data='master')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await query.message.edit_text(
            "Выберите тип работы, которую вы хотите заказать:",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "Выберите тип работы, которую вы хотите заказать:",
            reply_markup=reply_markup
        )

    return SELECT_ORDER_TYPE

# Обработчик выбора типа работы
async def select_order_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_type_key = query.data

    if order_type_key == 'back_to_main':
        return await main_menu(update, context)

    if order_type_key not in ORDER_TYPES:
        await query.message.reply_text("Неизвестный выбор. Пожалуйста, используйте кнопки для навигации.")
        return SELECT_ORDER_TYPE

    order_info = ORDER_TYPES.get(order_type_key)
    order_name = order_info['name']
    description = order_info['description']
    context.user_data['order_type_key'] = order_type_key
    context.user_data['order_type'] = order_name

    keyboard = [
        [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_order_type')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(
        f"Вы выбрали: *{order_name}*\n\n"
        f"{description}\n\n"
        f"Пожалуйста, введите тему вашей работы:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    return INPUT_TOPIC

# Обработчик кнопки "Назад" для выбора типа работы
async def back_to_order_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await select_order_type(update, context)

# Обработчик ввода темы
async def input_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        topic = update.message.text
        context.user_data['topic'] = topic
        return await select_deadline_date(update, context)

# Обработчик выбора даты дедлайна
async def select_deadline_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📅 Пожалуйста, выберите дату сдачи работы:")
    calendar, step = MyTranslationCalendar(min_date=datetime.now().date()).build()
    await update.message.reply_text(f"Выберите {step}", reply_markup=calendar)
    return SELECT_DEADLINE_DATE

# Обработчик календаря
async def handle_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    result, key, step = MyTranslationCalendar(min_date=datetime.now().date()).process(query.data)
    if not result and key:
        await query.message.edit_text(f"Выберите {step}", reply_markup=key)
        return SELECT_DEADLINE_DATE
    elif result:
        context.user_data['deadline'] = datetime.combine(result, datetime.min.time())
        await query.message.edit_text(f"🗓 Вы выбрали дату: {result.strftime('%d.%m.%Y')}")
        order_type_key = context.user_data.get('order_type_key')

        # Для самостоятельных работ пропускаем вопросы о научном руководителе и базе практики
        if order_type_key == 'self':
            context.user_data['supervisor'] = 'Не указано'
            context.user_data['practice_base'] = 'Не указано'
            return await ask_for_plan(query, context)
        else:
            # Спрашиваем про научного руководителя
            keyboard = [
                [InlineKeyboardButton("🧑‍🏫 Указать ФИО научного руководителя", callback_data='enter_supervisor')],
                [InlineKeyboardButton("⏭ Пропустить", callback_data='skip_supervisor')],
                [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_order_type')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(
                "Укажите ФИО вашего научного руководителя или пропустите этот шаг:",
                reply_markup=reply_markup
            )
            return SELECT_SUPERVISOR_OPTION

# Обработчик выбора опции научного руководителя
async def select_supervisor_option(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'enter_supervisor':
        await query.message.reply_text("Пожалуйста, введите ФИО вашего научного руководителя:")
        return INPUT_SUPERVISOR
    elif query.data == 'skip_supervisor':
        context.user_data['supervisor'] = 'Не указано'
        # Спрашиваем про базу практики
        keyboard = [
            [InlineKeyboardButton("🏢 Указать базу практики", callback_data='enter_practice_base')],
            [InlineKeyboardButton("⏭ Пропустить", callback_data='skip_practice_base')],
            [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_order_type')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            "Укажите базу практики или пропустите этот шаг:",
            reply_markup=reply_markup
        )
        return SELECT_PRACTICE_BASE_OPTION
    elif query.data == 'back_to_order_type':
        return await select_order_type(update, context)
    else:
        await query.message.reply_text("Неизвестный выбор. Пожалуйста, используйте кнопки для навигации.")
        return SELECT_SUPERVISOR_OPTION

# Обработчик ввода ФИО научного руководителя
async def input_supervisor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    supervisor = update.message.text
    context.user_data['supervisor'] = supervisor
    # Спрашиваем про базу практики
    keyboard = [
        [InlineKeyboardButton("🏢 Указать базу практики", callback_data='enter_practice_base')],
        [InlineKeyboardButton("⏭ Пропустить", callback_data='skip_practice_base')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_order_type')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Укажите базу практики или пропустите этот шаг:",
        reply_markup=reply_markup
    )
    return SELECT_PRACTICE_BASE_OPTION

# Обработчик выбора опции базы практики
async def select_practice_base_option(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'enter_practice_base':
        await query.message.reply_text("Пожалуйста, введите название базы практики:")
        return INPUT_PRACTICE_BASE
    elif query.data == 'skip_practice_base':
        context.user_data['practice_base'] = 'Не указано'
        return await ask_for_plan(query, context)
    elif query.data == 'back_to_order_type':
        return await select_order_type(update, context)
    else:
        await query.message.reply_text("Неизвестный выбор. Пожалуйста, используйте кнопки для навигации.")
        return SELECT_PRACTICE_BASE_OPTION

# Обработчик ввода базы практики
async def input_practice_base(update: Update, context: ContextTypes.DEFAULT_TYPE):
    practice_base = update.message.text
    context.user_data['practice_base'] = practice_base
    return await ask_for_plan(update, context)

# Функция запроса плана
async def ask_for_plan(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📄 Загрузить файл плана", callback_data='upload_plan')],
        [InlineKeyboardButton("📝 Написать план в чате", callback_data='write_plan')],
        [InlineKeyboardButton("⏭ Пропустить", callback_data='skip_plan')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_order_type')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(
            "У вас есть план работы? Вы можете загрузить файл с планом, написать его в чате или пропустить этот шаг.",
            reply_markup=reply_markup
        )
    else:
        await update_or_query.message.reply_text(
            "У вас есть план работы? Вы можете загрузить файл с планом, написать его в чате или пропустить этот шаг.",
            reply_markup=reply_markup
        )
    return INPUT_PLAN_CHOICE

# Обработчик выбора способа ввода плана
async def input_plan_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data
    if choice == 'upload_plan':
        await query.message.reply_text("Пожалуйста, загрузите файл с планом (документом):")
        return UPLOAD_PLAN
    elif choice == 'write_plan':
        await query.message.reply_text("Пожалуйста, введите план работы в чате:")
        return INPUT_PLAN_TEXT
    elif choice == 'skip_plan':
        context.user_data['plan'] = 'Не предоставлен'
        return await calculate_price_step(query, context)
    elif choice == 'back_to_order_type':
        return await select_order_type(update, context)
    else:
        await query.message.reply_text("Неизвестный выбор. Пожалуйста, используйте кнопки для навигации.")
        return INPUT_PLAN_CHOICE

# Обработчик загрузки файла плана
async def upload_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if document:
        file = await document.get_file()
        user = update.effective_user
        client_name = user.username if user.username else f"user_{user.id}"
        order_type_key = context.user_data.get('order_type_key', 'unknown')
        order_type = context.user_data.get('order_type', 'Неизвестный тип')
        order_dir = os.path.join(BASE_DIR, client_name, order_type)

        os.makedirs(order_dir, exist_ok=True)
        file_path = os.path.join(order_dir, document.file_name)
        await file.download_to_drive(file_path)
        context.user_data['plan'] = f"Файл: {document.file_name}"
        await update.message.reply_text("✅ Файл плана успешно загружен.")
    else:
        await update.message.reply_text("Пожалуйста, загрузите файл.")
        return UPLOAD_PLAN
    return await calculate_price_step(update, context)

# Обработчик ввода плана в чате
async def input_plan_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plan_text = update.message.text
    context.user_data['plan'] = plan_text
    return await calculate_price_step(update, context)

# Расчет стоимости и отправка сообщения
async def calculate_price_step(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data
    order_type_key = data.get('order_type_key')
    deadline = data.get('deadline')

    if isinstance(deadline, datetime):
        deadline_date = deadline
    else:
        deadline_date = datetime.now() + timedelta(days=30)

    price = calculate_price(order_type_key, deadline_date)
    data['price'] = price

    confirm_text = (
        f"✨ *Предварительная стоимость вашей работы составляет {price} рублей.*\n\n"
        "Если вы согласны, подтвердите заказ.\n"
        "Если хотите изменить данные, используйте команду /start для начала заново."
    )

    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить заказ", callback_data='confirm_order')],
        [InlineKeyboardButton("❌ Отменить", callback_data='cancel_order')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(confirm_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update_or_query.message.reply_text(confirm_text, reply_markup=reply_markup, parse_mode='Markdown')
    return CALCULATE_PRICE

# Обработчик подтверждения заказа
async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = context.user_data

    # Сохранение данных в файл
    user = update.effective_user
    client_name = user.username if user.username else f"user_{user.id}"
    order_type = data.get('order_type', 'Неизвестный тип')
    order_dir = os.path.join(BASE_DIR, client_name, order_type)
    os.makedirs(order_dir, exist_ok=True)
    order_filename = f"order_{len(os.listdir(order_dir)) + 1}.txt"
    order_path = os.path.join(order_dir, order_filename)

    # Сохранение заказа в словарь
    order_id = len(user_orders.get(user.id, [])) + 1
    order_data = {
        'order_id': order_id,
        'date': datetime.now(),
        'type': order_type,
        'topic': data.get('topic'),
        'deadline': data.get('deadline'),
        'price': data.get('price'),
        'status': 'Новый заказ'
    }

    user_orders.setdefault(user.id, []).append(order_data)

    with open(order_path, 'w', encoding='utf-8') as f:
        f.write(f"Пользователь: {user.first_name} (@{user.username})\n")
        f.write(f"ID: {user.id}\n")
        f.write(f"Тип работы: {order_type}\n")
        f.write(f"Тема: {data.get('topic')}\n")
        f.write(f"Сроки: {data.get('deadline').strftime('%d.%m.%Y')}\n")
        f.write(f"Научный руководитель: {data.get('supervisor', 'Не указано')}\n")
        f.write(f"База практики: {data.get('practice_base', 'Не указано')}\n")
        f.write(f"План: {data.get('plan', 'Не предоставлен')}\n")
        f.write(f"Стоимость: {data.get('price')} рублей\n")
        f.write(f"Статус: {order_data['status']}\n")

    # Обновление Excel-файла
    excel_path = os.path.join(BASE_DIR, 'orders.xlsx')
    order_data_excel = {
        'Дата': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'Пользователь': f"{user.first_name} (@{user.username})",
        'ID': user.id,
        'Тип работы': order_type,
        'Тема': data.get('topic'),
        'Сроки': data.get('deadline').strftime('%d.%m.%Y'),
        'Стоимость': data.get('price'),
        'Статус': 'Новый заказ'
    }
    if os.path.exists(excel_path):
        df = pd.read_excel(excel_path)
        df = pd.concat([df, pd.DataFrame([order_data_excel])], ignore_index=True)
    else:
        df = pd.DataFrame([order_data_excel])
    df.to_excel(excel_path, index=False)

    # Уведомление администратору
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"🆕 *Новый заказ от пользователя @{user.username}:*\n\n"
             f"Тип работы: {order_type}\n"
             f"Тема: {data.get('topic')}\n"
             f"Сроки: {data.get('deadline').strftime('%d.%m.%Y')}\n"
             f"Стоимость: {data.get('price')} рублей\n"
             f"ID заказа: {order_id}\n"
             f"Подробнее см. в Excel-файле.",
        parse_mode='Markdown'
    )

    await query.message.reply_text(
        "✅ *Ваш заказ подтверждён!*\n\nНаш администратор свяжется с вами в ближайшее время.\n"
        "Спасибо за обращение!",
        parse_mode='Markdown'
    )

    # Очистка данных пользователя
    context.user_data.clear()

    return await main_menu(update, context)

# Обработчик отмены заказа
async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "❌ Ваш заказ отменён. Если захотите начать заново, используйте команду /start."
    )
    context.user_data.clear()
    return await main_menu(update, context)

# Обработчик команды /feedback
async def feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Пожалуйста, оставьте ваш отзыв:")
    return LEAVE_FEEDBACK

# Обработчик получения отзыва
async def receive_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    feedback_text = update.message.text
    feedback_dir = os.path.join(BASE_DIR, 'feedbacks', user.username or f"user_{user.id}")
    os.makedirs(feedback_dir, exist_ok=True)
    feedback_file = os.path.join(feedback_dir, f"feedback_{datetime.now().strftime('%Y%m%d%H%M%S')}.txt")
    with open(feedback_file, 'w', encoding='utf-8') as f:
        f.write(feedback_text)
    await update.message.reply_text("Спасибо за ваш отзыв! 🙏")
    # Отправка отзыва администратору
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"Новый отзыв от @{user.username}:\n\n{feedback_text}"
    )
    return await main_menu(update, context)

# Обработчик показа профиля пользователя
async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    orders = user_orders.get(user.id, [])
    referral_count = sum(1 for ref in referrals.values() if ref == str(user.id))
    ref_link = context.user_data.get('ref_link', f"https://t.me/{context.bot.username}?start={user.id}")

    profile_text = f"👤 *Ваш профиль*\n\n"
    profile_text += f"Имя: {user.first_name}\n"
    profile_text += f"Количество рефералов: {referral_count}\n"
    profile_text += f"Ваша реферальная ссылка:\n{ref_link}\n\n"

    if orders:
        profile_text += "📋 *Ваши заказы:*\n"
        for order in orders:
            profile_text += (
                f"- ID заказа: {order['order_id']}\n"
                f"  Тип: {order['type']}\n"
                f"  Тема: {order['topic']}\n"
                f"  Статус: {order['status']}\n\n"
            )
    else:
        profile_text += "У вас пока нет заказов.\n"

    keyboard = [
        [InlineKeyboardButton("🗑 Удалить заказ", callback_data='delete_order')],
        [InlineKeyboardButton("🔄 Повторить заказ", callback_data='repeat_order')],
        [InlineKeyboardButton("💬 Оставить отзыв", callback_data='leave_feedback')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(profile_text, parse_mode='Markdown', reply_markup=reply_markup)
    return PROFILE_MENU

# Обработчик меню профиля
async def profile_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == 'delete_order':
        await query.message.reply_text("Введите ID заказа, который хотите удалить:")
        return DELETE_ORDER_CONFIRMATION
    elif data == 'repeat_order':
        await query.message.reply_text("Введите ID заказа, который хотите повторить:")
        return REPEAT_ORDER
    elif data == 'leave_feedback':
        await query.message.reply_text("Пожалуйста, оставьте ваш отзыв:")
        return LEAVE_FEEDBACK
    elif data == 'back_to_main':
        return await main_menu(update, context)
    else:
        await query.message.reply_text("Неизвестный выбор. Пожалуйста, используйте кнопки для навигации.")
        return PROFILE_MENU

# Обработчик подтверждения удаления заказа
async def delete_order_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    order_id_text = update.message.text.strip()
    try:
        order_id = int(order_id_text)
        orders = user_orders.get(user.id, [])
        order_found = False
        for order in orders:
            if order['order_id'] == order_id:
                orders.remove(order)
                order_found = True
                break
        if order_found:
            await update.message.reply_text(
                f"✅ Заказ с ID {order_id} успешно удалён.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Перейти в главное меню", callback_data='back_to_main')]
                ])
            )
            return PROFILE_MENU
        else:
            await update.message.reply_text("Заказ с таким ID не найден. Проверьте ID и попробуйте снова.")
            return DELETE_ORDER_CONFIRMATION
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректный числовой ID заказа.")
        return DELETE_ORDER_CONFIRMATION

# Обработчик повторения заказа (пока не реализовано)
async def repeat_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Функция повторения заказа пока не реализована.")
    return PROFILE_MENU

# Обработчик команды /admin
async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("Извините, эта команда доступна только администратору.")
        return

    keyboard = [
        [InlineKeyboardButton("📄 Просмотр заказов", callback_data='admin_view_orders')],
        [InlineKeyboardButton("💰 Изменить цены", callback_data='admin_update_prices')],
        [InlineKeyboardButton("💬 Просмотр отзывов", callback_data='admin_view_feedbacks')],
        [InlineKeyboardButton("🔄 Обновить статус заказа", callback_data='admin_update_order_status')],
        [InlineKeyboardButton("📢 Сделать рассылку", callback_data='admin_broadcast')],
        [InlineKeyboardButton("⚙️ Изменить режим ценообразования", callback_data='admin_change_pricing_mode')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_main_admin')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Админ-панель:", reply_markup=reply_markup)
    return ADMIN_MENU

# Обработчик админского меню
async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_CHAT_ID:
        await query.message.reply_text("Извините, эта команда доступна только администратору.")
        return SELECT_MAIN_MENU

    if query.data == 'admin_view_orders':
        await admin_view_orders(update, context)
        return ADMIN_MENU
    elif query.data == 'admin_update_prices':
        await query.message.reply_text("Отправьте новый прайс-лист в формате JSON:")
        return ADMIN_UPDATE_PRICES
    elif query.data == 'admin_view_feedbacks':
        await admin_view_feedbacks(update, context)
        return ADMIN_MENU
    elif query.data == 'admin_update_order_status':
        await query.message.reply_text("Введите ID пользователя, ID заказа и новый статус через пробел:")
        return ADMIN_UPDATE_ORDER_STATUS
    elif query.data == 'admin_broadcast':
        await query.message.reply_text("Введите сообщение для рассылки всем пользователям:")
        return ADMIN_BROADCAST
    elif query.data == 'admin_change_pricing_mode':
        await admin_change_pricing_mode(update, context)
        return ADMIN_CHANGE_PRICING_MODE
    elif query.data == 'back_to_main_admin':
        return await main_menu(update, context)
    else:
        await query.message.reply_text("Неизвестный выбор. Пожалуйста, используйте кнопки для навигации.")
        return ADMIN_MENU

# Функции для админ-панели
async def admin_view_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    orders_text = "📄 *Список заказов:*\n\n"
    for user_id, orders in user_orders.items():
        for order in orders:
            orders_text += (
                f"Пользователь ID: {user_id}\n"
                f"ID заказа: {order['order_id']}\n"
                f"Тип: {order['type']}\n"
                f"Тема: {order['topic']}\n"
                f"Статус: {order['status']}\n\n"
            )
    await update.callback_query.message.reply_text(orders_text or "Нет заказов.", parse_mode='Markdown')

async def admin_receive_new_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_prices_text = update.message.text
    try:
        new_prices = json.loads(new_prices_text)
        save_prices(new_prices)
        global PRICES
        PRICES = new_prices
        await update.message.reply_text("Цены успешно обновлены.")
    except json.JSONDecodeError:
        await update.message.reply_text("Ошибка в формате JSON. Попробуйте ещё раз.")
        return ADMIN_UPDATE_PRICES
    return ADMIN_MENU

async def admin_view_feedbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feedbacks_dir = os.path.join(BASE_DIR, 'feedbacks')
    feedbacks_text = "💬 *Отзывы пользователей:*\n\n"
    if os.path.exists(feedbacks_dir):
        for user_dir in os.listdir(feedbacks_dir):
            user_feedback_dir = os.path.join(feedbacks_dir, user_dir)
            if os.path.isdir(user_feedback_dir):
                for feedback_file in os.listdir(user_feedback_dir):
                    feedback_file_path = os.path.join(feedbacks_dir, user_dir, feedback_file)
                    with open(feedback_file_path, 'r', encoding='utf-8') as f:
                        feedback_content = f.read()
                        feedbacks_text += f"От @{user_dir}:\n{feedback_content}\n\n"
    else:
        feedbacks_text += "Отзывов пока нет."
    await update.callback_query.message.reply_text(feedbacks_text, parse_mode='Markdown')

async def admin_receive_order_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id_str, order_id_str, new_status = update.message.text.strip().split(None, 2)
        user_id = int(user_id_str)
        order_id = int(order_id_str)
        orders = user_orders.get(user_id, [])
        for order in orders:
            if order['order_id'] == order_id:
                order['status'] = new_status
                # Уведомляем пользователя
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"🔔 Статус вашего заказа #{order_id} обновлён: {new_status}"
                )
                await update.message.reply_text("Статус заказа обновлён.")
                return ADMIN_MENU
        await update.message.reply_text("Заказ не найден.")
        return ADMIN_MENU
    except ValueError:
        await update.message.reply_text("Неправильный формат данных. Попробуйте ещё раз.")
        return ADMIN_UPDATE_ORDER_STATUS

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    success_count = 0
    for user_id in user_ids:
        try:
            await context.bot.send_message(chat_id=user_id, text=message)
            success_count += 1
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
    await update.message.reply_text(f"Сообщение отправлено {success_count} пользователям.")
    return ADMIN_MENU

async def admin_change_pricing_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔴 Hard Mode", callback_data='set_hard_mode')],
        [InlineKeyboardButton("🟢 Light Mode", callback_data='set_light_mode')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_admin_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.message.reply_text("Выберите режим ценообразования:", reply_markup=reply_markup)
    return ADMIN_CHANGE_PRICING_MODE

async def admin_change_pricing_mode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    global current_pricing_mode
    if query.data == 'set_hard_mode':
        current_pricing_mode = 'hard'
        await query.message.reply_text("Режим ценообразования установлен на Hard Mode.")
        return ADMIN_MENU
    elif query.data == 'set_light_mode':
        current_pricing_mode = 'light'
        await query.message.reply_text("Режим ценообразования установлен на Light Mode.")
        return ADMIN_MENU
    elif query.data == 'back_to_admin_menu':
        return await admin_start(update, context)
    else:
        await query.message.reply_text("Неизвестный выбор. Пожалуйста, используйте кнопки для навигации.")
        return ADMIN_CHANGE_PRICING_MODE

# Обработчик отмены
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Действие отменено.")
    return await main_menu(update, context)

# Обработчик неизвестных сообщений
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Извините, я не понимаю эту команду. Пожалуйста, используйте меню для навигации."
    )

def main():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    user_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SELECT_MAIN_MENU: [
                CallbackQueryHandler(main_menu_handler),
                CallbackQueryHandler(back_to_main_menu, pattern='^back_to_main$')
            ],
            SHOW_PRICE_LIST: [
                CallbackQueryHandler(back_to_main_menu, pattern='^back_to_main$')
            ],
            SHOW_FAQ: [
                CallbackQueryHandler(back_to_main_menu, pattern='^back_to_main$')
            ],
            SELECT_ORDER_TYPE: [
                CallbackQueryHandler(select_order_type_callback),
                CallbackQueryHandler(back_to_main_menu, pattern='^back_to_main$')
            ],
            INPUT_TOPIC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, input_topic),
                CallbackQueryHandler(back_to_order_type, pattern='^back_to_order_type$')
            ],
            SELECT_DEADLINE_DATE: [
                CallbackQueryHandler(handle_calendar),
                CallbackQueryHandler(back_to_order_type, pattern='^back_to_order_type$')
            ],
            SELECT_SUPERVISOR_OPTION: [
                CallbackQueryHandler(select_supervisor_option),
                CallbackQueryHandler(back_to_order_type, pattern='^back_to_order_type$')
            ],
            INPUT_SUPERVISOR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, input_supervisor),
                CallbackQueryHandler(back_to_order_type, pattern='^back_to_order_type$')
            ],
            SELECT_PRACTICE_BASE_OPTION: [
                CallbackQueryHandler(select_practice_base_option),
                CallbackQueryHandler(back_to_order_type, pattern='^back_to_order_type$')
            ],
            INPUT_PRACTICE_BASE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, input_practice_base),
                CallbackQueryHandler(back_to_order_type, pattern='^back_to_order_type$')
            ],
            INPUT_PLAN_CHOICE: [
                CallbackQueryHandler(input_plan_choice),
                CallbackQueryHandler(back_to_order_type, pattern='^back_to_order_type$')
            ],
            INPUT_PLAN_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, input_plan_text),
                CallbackQueryHandler(back_to_order_type, pattern='^back_to_order_type$')
            ],
            UPLOAD_PLAN: [
                MessageHandler(filters.Document.ALL, upload_plan),
                CallbackQueryHandler(back_to_order_type, pattern='^back_to_order_type$')
            ],
            CALCULATE_PRICE: [
                CallbackQueryHandler(confirm_order, pattern='^confirm_order$'),
                CallbackQueryHandler(cancel_order, pattern='^cancel_order$')
            ],
            PROFILE_MENU: [
                CallbackQueryHandler(profile_menu_handler),
                CallbackQueryHandler(back_to_main_menu, pattern='^back_to_main$')
            ],
            DELETE_ORDER_CONFIRMATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, delete_order_confirmation),
                CallbackQueryHandler(back_to_main_menu, pattern='^back_to_main$')
            ],
            LEAVE_FEEDBACK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_feedback)
            ],
            ADMIN_MENU: [
                CallbackQueryHandler(admin_menu_handler),
            ],
            ADMIN_UPDATE_PRICES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_new_prices)
            ],
            ADMIN_UPDATE_ORDER_STATUS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_order_status)
            ],
            ADMIN_BROADCAST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast)
            ],
            ADMIN_CHANGE_PRICING_MODE: [
                CallbackQueryHandler(admin_change_pricing_mode_handler)
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CommandHandler('admin', admin_start),
            CommandHandler('help', help_command)
        ],
        per_user=True,
        allow_reentry=True
    )

    application.add_handler(user_conv_handler)
    application.add_handler(CommandHandler('feedback', feedback))
    application.add_handler(CommandHandler('admin', admin_start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Запуск бота
    application.run_polling()

if __name__ == '__main__':
    main()
