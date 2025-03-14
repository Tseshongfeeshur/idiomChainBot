import json
import random
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler
from telegram.error import NetworkError, TelegramError
from pypinyin import pinyin, Style

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 全局常量
LIB_FILE = "lib.json"  # 主成语库文件路径
USER_LIB_FILE = "user-lib.json"  # 用户成语库文件路径
SCORES_FILE = "scores.json"  # 用户最佳成绩文件路径
TOKEN = ""  # Telegram Bot Token
ADMIN_ID = ""  # 管理员的Telegram ID

# 文件操作函数
def load_json(file):
    try:
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_json(file, data):
    try:
        with open(file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Failed to save {file}: {e}")

def load_combined_library():
    main_lib = load_json(LIB_FILE)
    user_lib = load_json(USER_LIB_FILE)
    combined = main_lib.copy()
    for start_py, idioms in user_lib.items():
        if start_py in combined:
            combined[start_py].update(idioms)
        else:
            combined[start_py] = idioms
    return combined

# 成语处理函数
def get_first_last_char(word):
    return word[0], word[-1]

def search_idiom(idiom, library):
    return next(((start_py, idioms[idiom]) for start_py, idioms in library.items() if idiom in idioms), (None, None))

def random_idiom(library):
    if not library:
        return None, None, None
    start_py = random.choice(list(library.keys()))
    idiom = random.choice(list(library[start_py].keys()))
    return idiom, start_py, library[start_py][idiom]

def find_next_idiom(last_char, last_py_end, library):
    candidates_same_char = []
    candidates_same_pinyin = []
    
    for start_py, idioms in library.items():
        for idiom, end_py in idioms.items():
            first_char = idiom[0]
            if first_char == last_char:
                candidates_same_char.append((idiom, end_py))
            elif start_py == last_py_end:
                candidates_same_pinyin.append((idiom, end_py))
    
    if candidates_same_char:
        return random.choice(candidates_same_char)
    if candidates_same_pinyin:
        return random.choice(candidates_same_pinyin)
    return None, None

def get_idiom_pinyin(idiom):
    pinyin_list = pinyin(idiom, style=Style.NORMAL)
    return pinyin_list[0][0], pinyin_list[-1][0]

# 成绩管理函数
def update_score(chat_id, rounds):
    scores = load_json(SCORES_FILE)
    current_best = scores.get(str(chat_id), 0)
    if rounds > current_best:
        scores[str(chat_id)] = rounds
        save_json(SCORES_FILE, scores)
    return scores.get(str(chat_id), rounds)

def get_result_message(chat_id, rounds):
    best_score = update_score(chat_id, rounds)
    return (
        f"本次接龙结束啦！持续共 {rounds} 回合。☺️\n"
        f"本群最佳成绩是 {best_score} 回合，厉害了！🥳\n"
        "下次再来挑战吧！😆"
    )

# 获取游戏状态
def get_game_data(context, chat_id):
    if f"game_{chat_id}" not in context.bot_data:
        context.bot_data[f"game_{chat_id}"] = {"game_active": False, "rounds": 0, "last_idiom": None, "last_end_py": None}
    return context.bot_data[f"game_{chat_id}"]

# 错误处理装饰器
async def with_error_handling(func, update: Update, context: CallbackContext):
    try:
        await func(update, context)
    except NetworkError as e:
        logger.error(f"Network error: {e}")
        if update.message:
            await update.message.reply_text("网络有点问题，请稍后再试！😅")
    except TelegramError as e:
        logger.error(f"Telegram error: {e}")
        if update.message:
            await update.message.reply_text("出了点小问题，请稍后再试！😓")
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        if update.message:
            await update.message.reply_text("哎呀，程序出错了，我去修修…😖")

# Bot 命令处理器
async def start(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    game_data = get_game_data(context, chat_id)
    
    keyboard = [[InlineKeyboardButton("你先来", callback_data="bot_first"), 
                InlineKeyboardButton("我先来", callback_data="user_first")]]
    welcome_text = (
        "*成语接龙 🥳*\n\n"
        "欢迎来玩成语接龙！😉\n\n"
        "1\\. 输入 /start，选择 *我先来* 或 *你先来* 开始游戏。\n"
        "2\\. 每次接龙，尽量使用首字和上个成语末字相同的成语。\n"
        "3\\. 如果接不下去，可以用 /cue 让我帮您接一个。\n"
        "4\\. 随时可以用 /end 结束游戏查看成绩。\n\n"
        "快来试试吧，看你能接多长！😆"
    )
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    game_data.update({"game_active": True, "rounds": 0})

async def cue(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    game_data = get_game_data(context, chat_id)
    
    if not game_data.get("game_active", False):
        await update.message.reply_text("请先发送 /start 开始游戏哦！🥳")
        return
        
    last_idiom = game_data.get("last_idiom")
    if not last_idiom:
        await update.message.reply_text("请先发送 /start 开始游戏哦！🥳")
        return
        
    library = load_combined_library()
    last_char = get_first_last_char(last_idiom)[1]
    last_py_end = game_data.get("last_end_py")
    
    next_idiom, next_end_py = find_next_idiom(last_char, last_py_end, library)
    if next_idiom:
        game_data["rounds"] += 1
        game_data.update({"last_idiom": next_idiom, "last_end_py": next_end_py})
        await update.message.reply_text(next_idiom)
    else:
        rounds = game_data["rounds"]
        game_data["game_active"] = False
        await update.message.reply_text(
            "坏了，我也接不下了…🥺\n" + 
            get_result_message(chat_id, rounds)
        )

async def end(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    game_data = get_game_data(context, chat_id)
    
    if not game_data.get("game_active", False):
        await update.message.reply_text("请先发送 /start 开始游戏哦！🥳")
        return
    rounds = game_data["rounds"]
    game_data["game_active"] = False
    await update.message.reply_text(get_result_message(chat_id, rounds))

async def button(update: Update, context: CallbackContext):
    query = update.callback_query
    chat_id = query.message.chat_id
    game_data = get_game_data(context, chat_id)
    await query.answer()
    
    if query.data == "user_first":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("您先来，请发送您的成语。😃")
        game_data.update({"last_idiom": None, "last_end_py": None, "rounds": 0})
    elif query.data == "bot_first":
        library = load_combined_library()
        idiom, _, end_py = random_idiom(library) or (None, None, None)
        if not idiom:
            await query.edit_message_text("我的成语库好像不太对…😢")
            return
        game_data.update({"last_idiom": idiom, "last_end_py": end_py, "rounds": 1})
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(idiom)
    elif query.data.startswith("submit_"):
        idiom = query.data.split("_", 1)[1]
        user_id = query.from_user.id
        user_link = f"[*{query.from_user.full_name}*](tg://user?id={user_id})"
        start_py, end_py = get_idiom_pinyin(idiom)
        
        admin_keyboard = [
            [InlineKeyboardButton("✅", callback_data=f"approve_{idiom}_{chat_id}_{start_py}_{end_py}"),
             InlineKeyboardButton("❎", callback_data=f"reject_{idiom}_{chat_id}")]
        ]
        msg = await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"{user_link}\n{idiom}\n{start_py} {end_py}",
            reply_markup=InlineKeyboardMarkup(admin_keyboard),
            parse_mode="Markdown"
        )
        context.bot_data[f"pending_{idiom}_{chat_id}"] = {
            "admin_msg_id": msg.message_id,
            "user_msg_id": query.message.message_id,
            "chat_id": chat_id
        }
        await query.edit_message_text(f"您的成语“{idiom}”已投喂，等待审核中…☺️")
    elif query.data.startswith("approve_"):
        _, idiom, chat_id, start_py, end_py = query.data.split("_", 4)
        user_lib = load_json(USER_LIB_FILE)
        if start_py not in user_lib:
            user_lib[start_py] = {}
        user_lib[start_py][idiom] = end_py
        save_json(USER_LIB_FILE, user_lib)
        
        await query.edit_message_text(f"{idiom} ✅")
        pending_key = f"pending_{idiom}_{chat_id}"
        if pending_key in context.bot_data:
            pending_data = context.bot_data[pending_key]
            await context.bot.edit_message_text(
                chat_id=pending_data["chat_id"],
                message_id=pending_data["user_msg_id"],
                text=f"您的成语“{idiom}”投喂成功！🥳\n我已经记住啦！😆"
            )
            del context.bot_data[pending_key]
    elif query.data.startswith("reject_"):
        _, idiom, chat_id = query.data.split("_", 2)
        await query.edit_message_text(f"{idiom} ❎")
        pending_key = f"pending_{idiom}_{chat_id}"
        if pending_key in context.bot_data:
            pending_data = context.bot_data[pending_key]
            await context.bot.edit_message_text(
                chat_id=pending_data["chat_id"],
                message_id=pending_data["user_msg_id"],
                text=f"您的成语“{idiom}”投喂失败…😢\n哪里不对呢？🤔"
            )
            del context.bot_data[pending_key]

async def handle_message(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    game_data = get_game_data(context, chat_id)
    
    if not game_data.get("game_active", False):
        await update.message.reply_text("请先发送 /start 开始游戏哦！🥳")
        return
        
    user_idiom = update.message.text.strip()
    library = load_combined_library()
    start_py, end_py = search_idiom(user_idiom, library)
    
    if not start_py:
        keyboard = [[InlineKeyboardButton("投喂成语", callback_data=f"submit_{user_idiom}")]]
        await update.message.reply_text(
            "好像不太对哦…要不试试别的？🤔\n或者用 /cue 让我帮您接一个！\n这是成语吗？您可以把它投喂给我呢…😋",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
        
    last_idiom = game_data.get("last_idiom")
    if last_idiom:
        last_char = get_first_last_char(last_idiom)[1]
        last_py_end = game_data["last_end_py"]
        if user_idiom[0] != last_char and start_py != last_py_end:
            keyboard = [[InlineKeyboardButton("投喂", callback_data=f"submit_{user_idiom}")]]
            await update.message.reply_text(
                "好像不太对哦…要不试试别的？🤔\n或者用 /cue 让我帮您接一个！\n这是成语吗？您可以把它投喂给我呢…😋",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
            
    game_data["rounds"] += 1
    rounds = game_data["rounds"]
    
    next_idiom, next_end_py = find_next_idiom(user_idiom[-1], end_py, library)
    if next_idiom:
        game_data.update({"last_idiom": next_idiom, "last_end_py": next_end_py})
        await update.message.reply_text(next_idiom)
        game_data["rounds"] += 1
    else:
        game_data["game_active"] = False
        await update.message.reply_text(
            "坏了，我接不下了…😥\n" +
            get_result_message(chat_id, rounds)
        )

# 全局错误处理器
async def error_handler(update: Update, context: CallbackContext):
    logger.error(f"Exception while handling an update: {context.error}", exc_info=True)
    if update and update.message:
        await update.message.reply_text("哎呀，出错了！\n我会尽快恢复的…😖")

# 主函数
def main():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", lambda u, c: with_error_handling(start, u, c)))
    application.add_handler(CommandHandler("cue", lambda u, c: with_error_handling(cue, u, c)))
    application.add_handler(CommandHandler("end", lambda u, c: with_error_handling(end, u, c)))
    application.add_handler(CallbackQueryHandler(lambda u, c: with_error_handling(button, u, c)))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: with_error_handling(handle_message, u, c)))
    
    application.add_error_handler(error_handler)
    
    while True:
        try:
            application.run_polling(poll_interval=2.0, timeout=20)
            break
        except NetworkError as e:
            logger.error(f"Network error during polling: {e}")
            asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Unexpected error during polling: {e}", exc_info=True)
            asyncio.sleep(5)

if __name__ == "__main__":
    main()