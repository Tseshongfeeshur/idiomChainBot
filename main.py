import json
import random
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler
from telegram.error import NetworkError, TelegramError

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 全局常量
LIB_FILE = "lib.json"  # 成语库文件路径
SCORES_FILE = "scores.json"  # 用户最佳成绩文件路径
TOKEN = "7496957549:AAHj13fl2eFrri7yQs_iJWboHl53MMOj0tA"  # Telegram Bot Token

# 文件操作函数
def load_json(file):
    try:
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to load {file}: {e}")
        return {}

def save_json(file, data):
    try:
        with open(file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Failed to save {file}: {e}")

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

# 成绩管理函数
def update_user_score(user_id, rounds):
    scores = load_json(SCORES_FILE)
    current_best = scores.get(str(user_id), 0)
    if rounds > current_best:
        scores[str(user_id)] = rounds
        save_json(SCORES_FILE, scores)
    return scores.get(str(user_id), rounds)

def get_result_message(user_id, rounds):
    best_score = update_user_score(user_id, rounds)
    return (
        f"本次接龙结束啦！持续共 {rounds} 回合。☺️\n"
        f"您的最佳成绩是 {best_score} 回合，厉害了！🥳\n"
        "下次再来挑战吧！😆"
    )

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
    keyboard = [[InlineKeyboardButton("你先来", callback_data="bot_first"), 
                InlineKeyboardButton("我先来", callback_data="user_first")]]
    welcome_text = (
        "*成语接龙 🥳*\n\n"
        "欢迎来玩成语接龙！😉\n\n"
        "1\\. 输入 `/start`，选择 *我先来* 或 *你先来* 开始游戏。\n"
        "2\\. 每次接龙，尽量使用首字和上个成语末字相同的成语。\n"
        "3\\. 如果接不下去，可以用 `/cue` 让我帮您接一个。\n"
        "4\\. 随时可以用 `/end` 结束游戏查看成绩。\n\n"
        "快来试试吧，看你能接多长！😆"
    )
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    context.user_data.update({"game_active": True, "rounds": 0})

async def cue(update: Update, context: CallbackContext):
    if not context.user_data.get("game_active", False):
        await update.message.reply_text("请先发送 /start 开始游戏哦！🥳")
        return
        
    last_idiom = context.user_data.get("last_idiom")
    if not last_idiom:
        await update.message.reply_text("请先发送 /start 开始游戏哦！🥳")
        return
        
    library = load_json(LIB_FILE)
    last_char = get_first_last_char(last_idiom)[1]
    last_py_end = context.user_data.get("last_end_py")
    
    next_idiom, next_end_py = find_next_idiom(last_char, last_py_end, library)
    if next_idiom:
        context.user_data["rounds"] += 1
        context.user_data.update({"last_idiom": next_idiom, "last_end_py": next_end_py})
        await update.message.reply_text(next_idiom)
    else:
        rounds = context.user_data["rounds"]
        context.user_data["game_active"] = False
        await update.message.reply_text(
            "坏了，我也接不下了…🥺\n" + 
            get_result_message(update.message.from_user.id, rounds)
        )

async def end(update: Update, context: CallbackContext):
    if not context.user_data.get("game_active", False):
        await update.message.reply_text("请先发送 /start 开始游戏哦！🥳")
        return
    rounds = context.user_data["rounds"]
    context.user_data["game_active"] = False
    await update.message.reply_text(get_result_message(update.message.from_user.id, rounds))

async def button(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    if query.data == "user_first":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("您先来，请发送您的成语。😃")
        context.user_data.update({"last_idiom": None, "last_end_py": None, "rounds": 0})
    elif query.data == "bot_first":
        library = load_json(LIB_FILE)
        idiom, _, end_py = random_idiom(library) or (None, None, None)
        if not idiom:
            await query.edit_message_text("我的成语库好像不太对…😢")
            return
        context.user_data.update({"last_idiom": idiom, "last_end_py": end_py, "rounds": 1})
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(idiom)

async def handle_message(update: Update, context: CallbackContext):
    if not context.user_data.get("game_active", False):
        await update.message.reply_text("请先发送 /start 开始游戏哦！🥳")
        return
        
    user_idiom = update.message.text.strip()
    library = load_json(LIB_FILE)
    start_py, end_py = search_idiom(user_idiom, library)
    
    if not start_py:
        await update.message.reply_text("好像不太对哦…🧐\n要不试试别的？\n或者用 /cue 让我帮您接一个！😆")
        return
        
    last_idiom = context.user_data.get("last_idiom")
    if last_idiom:
        last_char = get_first_last_char(last_idiom)[1]
        last_py_end = context.user_data["last_end_py"]
        if user_idiom[0] != last_char and start_py != last_py_end:
            await update.message.reply_text("好像不太对哦…🧐\n要不试试别的？\n或者用 /cue 让我帮您接一个！😆")
            return
            
    context.user_data["rounds"] += 1
    rounds = context.user_data["rounds"]
    
    next_idiom, next_end_py = find_next_idiom(user_idiom[-1], end_py, library)
    if next_idiom:
        context.user_data.update({"last_idiom": next_idiom, "last_end_py": next_end_py})
        await update.message.reply_text(next_idiom)
        context.user_data["rounds"] += 1
    else:
        context.user_data["game_active"] = False
        await update.message.reply_text(
            "坏了，我接不下了…😥\n" +
            get_result_message(update.message.from_user.id, rounds)
        )

# 全局错误处理器
async def error_handler(update: Update, context: CallbackContext):
    logger.error(f"Exception while handling an update: {context.error}", exc_info=True)
    if update and update.message:
        await update.message.reply_text("哎呀，出错了！我会尽快恢复的…😖")

# 主函数
def main():
    application = Application.builder().token(TOKEN).build()
    
    # 注册处理器并添加错误处理
    application.add_handler(CommandHandler("start", lambda u, c: with_error_handling(start, u, c)))
    application.add_handler(CommandHandler("cue", lambda u, c: with_error_handling(cue, u, c)))
    application.add_handler(CommandHandler("end", lambda u, c: with_error_handling(end, u, c)))
    application.add_handler(CallbackQueryHandler(lambda u, c: with_error_handling(button, u, c), pattern="^(user_first|bot_first)$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: with_error_handling(handle_message, u, c)))
    
    # 添加全局错误处理器
    application.add_error_handler(error_handler)
    
    # 启动轮询并处理网络错误
    while True:
        try:
            application.run_polling(poll_interval=3.0, timeout=20)
            break
        except NetworkError as e:
            logger.error(f"Network error during polling: {e}")
            asyncio.sleep(5)  # 等待5秒后重试
        except Exception as e:
            logger.error(f"Unexpected error during polling: {e}", exc_info=True)
            asyncio.sleep(5)  # 等待5秒后重试

if __name__ == "__main__":
    main()