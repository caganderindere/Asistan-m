import json

import httpx

from server.live import CubaTools
from server.telegram import TelegramBot

PROJECTS = {"current": r"D:\a", "projects": [{"name": "balbal", "path": r"D:\web\balbal"}]}


class World:
    """Telegram and Gemini as the bot sees them."""

    def __init__(self, gemini_replies):
        self.sent, self.answered, self.gemini_bodies = [], [], []
        self.gemini_replies = list(gemini_replies)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "generativelanguage" in url:
            self.gemini_bodies.append(json.loads(request.content))
            parts = self.gemini_replies.pop(0)
            return httpx.Response(200, json={"candidates": [{"content": {"parts": parts}}]})
        method = url.rsplit("/", 1)[-1]
        if method == "sendMessage":
            self.sent.append(json.loads(request.content))
        elif method == "answerCallbackQuery":
            self.answered.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {}})


def make_bot(tmp_path, world, chat_id=None):
    settings = {"token": "T"} | ({"chat_id": chat_id} if chat_id else {})
    (tmp_path / "telegram.json").write_text(json.dumps(settings), encoding="utf-8")
    handed, pressed, heard = [], [], []

    async def hand_over(text, folder):
        handed.append((folder, text))

    tools = CubaTools(hand_over, pressed.append, tmp_path, projects=lambda: PROJECTS)

    async def toggle():
        return "uzak"

    bot = TelegramBot(tmp_path / "telegram.json", "key", "m", tools, lambda: "durum iyi", toggle,
                      lambda: pressed.append("stop"), heard=lambda *a: heard.append(a),
                      transport=httpx.MockTransport(world))
    bot.handed, bot.pressed, bot.heard = handed, pressed, heard
    return bot


def message(chat, text):
    return {"message": {"chat": {"id": chat}, "text": text}}


async def test_pairing_with_the_code_then_strangers_get_nothing(tmp_path):
    world = World([])
    bot = make_bot(tmp_path, world)
    assert not bot.paired and len(bot.pair_code) == 6
    await bot.handle(message(5, "/esle 000"))
    assert not bot.paired and world.sent == []
    await bot.handle(message(5, f"/esle {bot.pair_code}"))
    assert bot.paired and json.loads((tmp_path / "telegram.json").read_text())["chat_id"] == 5
    await bot.handle(message(9, "/durum"))
    await bot.handle(message(5, "/durum"))
    assert [m["text"] for m in world.sent][-1] == "durum iyi" and all(m["chat_id"] == 5 for m in world.sent)


async def test_a_message_can_hand_work_to_a_project(tmp_path):
    world = World([
        [{"functionCall": {"name": "terminale_ver", "args": {"proje": "balbal", "talimat": "Başlığı düzelt."}}}],
        [{"text": "Ekibe verdim efendim."}],
    ])
    bot = make_bot(tmp_path, world, chat_id=5)
    await bot.handle(message(5, "balbal'da başlığı düzelt"))
    assert bot.handed == [(r"D:\web\balbal", "Başlığı düzelt.")]
    assert world.sent[-1]["text"] == "Ekibe verdim efendim."
    second = world.gemini_bodies[1]["contents"]
    assert second[-1]["parts"][0]["functionResponse"]["response"]["ok"] is True
    assert "Telegram" in world.gemini_bodies[0]["systemInstruction"]["parts"][0]["text"]
    assert [h[:2] for h in bot.heard] == [("Çağan", "balbal'da başlığı düzelt"), ("Cuba", "Ekibe verdim efendim.")]


async def test_approval_buttons_answer_the_latest_question_once(tmp_path):
    world = World([])
    bot = make_bot(tmp_path, world, chat_id=5)
    choices = []
    await bot.ask_approval("Onay?", choices.append)
    key = world.sent[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].split(":")[0]
    await bot.handle({"callback_query": {"id": "q1", "from": {"id": 9}, "data": f"{key}:evet"}})
    assert choices == []  # not Çağan
    await bot.handle({"callback_query": {"id": "q2", "from": {"id": 5}, "data": f"{key}:evet"}})
    await bot.handle({"callback_query": {"id": "q3", "from": {"id": 5}, "data": f"{key}:hayir"}})
    assert choices == ["evet"]
    assert world.answered[-1]["text"] == "Bu soru artık geçerli değil."
    await bot.close()
