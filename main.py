import json
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler
from telegram.helpers import escape_markdown
from pypinyin import pinyin, Style

# 全局常量
ADMIN_ID =   # 管理员 Telegram ID
LIB_FILE = "lib.json"  # 成语库文件路径
PENDING_FILE = "pending_contributions.json"  # 待审核成语记录文件路径
TOKEN = ""  # Telegram Bot Token

# 文件操作函数
def load_json(file):
    """加载 JSON 文件，若文件不存在或解析失败返回空字典"""
    try:
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_json(file, data):
    """保存数据到 JSON 文件"""
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# 拼音与成语处理函数
def get_pinyin(word):
    """获取词的首字和末字拼音，失败时返回 None"""
    try:
        pinyin_list = pinyin(word, style=Style.NORMAL)
        return pinyin_list[0][0], pinyin_list[-1][0]
    except Exception:
        return None, None

def search_idiom(idiom, library):
    """在库中查找成语，返回首末拼音，若不存在返回 (None, None)"""
    return next(((start_py, idioms[idiom]) for start_py, idioms in library.items() if idiom in idioms), (None, None))

def random_idiom(library):
    """从库中随机选择一个成语，返回 (成语, 首拼音, 末拼音)"""
    if not library:
        return None, None, None
    start_py = random.choice(list(library.keys()))
    idiom = random.choice(list(library[start_py].keys()))
    return idiom, start_py, library[start_py][idiom]

def find_next_idiom(last_py_end, library):
    """根据末拼音寻找下一个接龙成语"""
    if last_py_end in library:
        idiom = random.choice(list(library[last_py_end].keys()))
        return idiom, library[last_py_end][idiom]
    return None, None

# Bot 命令处理器
async def start(update: Update, context: CallbackContext):
    """处理 /start 命令，开始成语接龙"""
    keyboard = [[InlineKeyboardButton("你先来", callback_data="bot_first"), InlineKeyboardButton("我先来", callback_data="user_first")]]
    welcome_text = (
        "*成语接龙 🥳*\n"
        "欢迎来玩成语接龙！😉\n"
        "1\\. 输入 `/start`，选择 *我先来* 或 *你先来* 决定您的先后手，开始游戏。\n"
        "2\\. 每次接龙，成语的首字拼音要接上一个的末字拼音。\n"
        "3\\. 如果您的成语我还不会，您可以选择 *投喂* 给我，审核成功后我就记住啦！\n"
        "4\\. 想直接投喂成语？用 `/add [成语]`，我也会认真学习！\n"
        "快来试试吧，看你能接多长！😆"
    )
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    context.user_data["game_active"] = True

async def add(update: Update, context: CallbackContext):
    """处理 /add 命令，添加新成语并提交审核"""
    if not context.args:
        await update.message.reply_text("您投喂了什么呀…！🥺\n使用方法：/add [待投喂成语]")
        return
    idiom = " ".join(context.args).strip()
    library = load_json(LIB_FILE)
    if search_idiom(idiom, library)[0]:
        await update.message.reply_text(f"真遗憾，您刚刚投喂的成语“{idiom}”我似乎已经知道了…😥")
        return
    response = await update.message.reply_text(f"您刚刚投喂了成语“{idiom}”，正在审核中…😉")
    pending = load_json(PENDING_FILE)
    pending[idiom] = {"chat_id": update.message.chat_id, "message_id": response.message_id, "user_id": update.message.from_user.id}
    save_json(PENDING_FILE, pending)
    await send_review_request(context, idiom, update.message.from_user)

# 按钮与消息处理器
async def button(update: Update, context: CallbackContext):
    """处理游戏开始按钮（用户先/机器人先）"""
    query = update.callback_query
    await query.answer()
    if query.data == "user_first":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("您先来，请发送您的成语。😃")
        context.user_data.update({"last_idiom": None, "last_end_py": None})
    elif query.data == "bot_first":
        library = load_json(LIB_FILE)
        idiom, _, end_py = random_idiom(library) or (None, None, None)
        if not idiom:
            await query.edit_message_text("我的成语库好像不太对…😢")
            return
        context.user_data.update({"last_idiom": idiom, "last_end_py": end_py})
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(idiom)

async def handle_message(update: Update, context: CallbackContext):
    """处理用户消息，进行成语接龙"""
    if not context.user_data.get("game_active", False):
        await update.message.reply_text("请您发送 /start 以开始成语接龙。🥳")
        return
    user_idiom = update.message.text.strip()
    library = load_json(LIB_FILE)
    start_py, end_py = search_idiom(user_idiom, library)
    if not start_py:
        keyboard = [[InlineKeyboardButton("好耶", callback_data=f"contribute_{user_idiom}"), InlineKeyboardButton("坏耶", callback_data="retry")]]
        await update.message.reply_text(f"真抱歉，我还不知道“{user_idiom}”这个成语呢…😥\n要将它投喂给我吗？😋", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    if context.user_data.get("last_end_py") and start_py != context.user_data["last_end_py"]:
        await update.message.reply_text("好像不太对哦…🧐\n要不您再试试？🤔")
        return
    next_idiom, next_end_py = find_next_idiom(end_py, library) or (None, None)
    if next_idiom:
        context.user_data.update({"last_idiom": next_idiom, "last_end_py": next_end_py})
        await update.message.reply_text(next_idiom)
    else:
        await update.message.reply_text("坏了，我好像接不下去了…😨\n您赢啦！🥳")
        context.user_data["game_active"] = False

# 审核相关函数
async def send_review_request(context, idiom, user):
    """向管理员发送成语审核请求"""
    start_py, end_py = get_pinyin(idiom)
    keyboard = [[InlineKeyboardButton("通过", callback_data=f"approve_{idiom}"), InlineKeyboardButton("拒绝", callback_data=f"reject_{idiom}")]]
    first_name = escape_markdown(user.first_name, version=2)
    await context.bot.send_message(
        ADMIN_ID,
        f"[@{first_name}](tg://user?id={user.id})\n{idiom}\n{start_py} {end_py}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="MarkdownV2"
    )

async def handle_contribution(update: Update, context: CallbackContext):
    """处理用户贡献新成语的按钮选择"""
    query = update.callback_query
    await query.answer()
    if query.data == "retry":
        await query.edit_message_text("谢谢您体谅我贫瘠的成语水平，那您再试试吧。😉")
        return
    if query.data.startswith("contribute_"):
        idiom = query.data.split("_", 1)[1]
        library = load_json(LIB_FILE)
        if search_idiom(idiom, library)[0]:
            await query.edit_message_text(f"真遗憾，您刚刚投喂的成语“{idiom}”我似乎已经知道了…😥\n这把算我赢咯！😜")
            return
        context.user_data["game_active"] = False
        await query.edit_message_text(f"那这把就姑且算是平局吧…😶‍🌫️\n您刚刚投喂了成语“{idiom}”，正在审核中…😉")
        pending = load_json(PENDING_FILE)
        pending[idiom] = {"chat_id": query.message.chat_id, "message_id": query.message.message_id, "user_id": query.from_user.id}
        save_json(PENDING_FILE, pending)
        await send_review_request(context, idiom, query.from_user)

async def handle_admin_approval(update: Update, context: CallbackContext):
    """处理管理员审核按钮（通过/拒绝）"""
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    idiom = query.data.split("_", 1)[1]
    pending = load_json(PENDING_FILE)
    contribution = pending.get(idiom)
    if not contribution:
        await query.edit_message_text("审核失败：找不到对应的用户入库记录。")
        return
    user_chat_id, user_message_id = contribution["chat_id"], contribution["message_id"]
    if query.data.startswith("approve_"):
        start_py, end_py = get_pinyin(idiom)
        library = load_json(LIB_FILE)
        library.setdefault(start_py, {})[idiom] = end_py
        save_json(LIB_FILE, library)
        await query.edit_message_text(f"{idiom} ✅")
        await context.bot.edit_message_text(chat_id=user_chat_id, message_id=user_message_id, text=f"您刚刚投喂的成语“{idiom}”我已经牢牢记住啦！🥰")
    else:
        await query.edit_message_text(f"{idiom} ❎")
        await context.bot.edit_message_text(chat_id=user_chat_id, message_id=user_message_id, text=f"真遗憾，您刚刚投喂的成语“{idiom}”似乎有点不对劲…😥")
    del pending[idiom]
    save_json(PENDING_FILE, pending)

# 主函数
def main():
    """启动 Bot 并注册所有处理器"""
    application = Application.builder().token(TOKEN).build()
    application.add_handlers([
        CommandHandler("start", start),
        CommandHandler("add", add),
        CallbackQueryHandler(button, pattern="^(user_first|bot_first)$"),
        CallbackQueryHandler(handle_contribution, pattern="^(contribute_|retry)"),
        CallbackQueryHandler(handle_admin_approval, pattern="^(approve_|reject_)"),
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    ])
    application.run_polling(poll_interval=2.0)

if __name__ == "__main__":
    main()