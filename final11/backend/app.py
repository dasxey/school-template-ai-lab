from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from data_base.db import init_db, add_entry, get_entries
import random


class MessageIn(BaseModel):
    text: str


app = FastAPI(title="MindHeaven API")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok", "app": "MindHeaven"}


@app.post("/api/message")
async def message_endpoint(payload: MessageIn):
    """
    Ендпоінт, який приймає текст користувача, оцінює настрій,
    повертає емпатичну відповідь та зберігає запис у щоденник (SQLite).
    """
    user_text = (payload.text or "").strip()
    if not user_text:
        empty_replies = [
            "Я поруч. Спробуй кількома реченнями описати, що з тобою зараз відбувається.",
            "Можеш написати, що ти відчуваєш — навіть якщо це всього одне слово.",
            "Я готовий слухати. Опиши свої думки або емоції так, як тобі зручно.",
        ]
        return {
            "reply": random.choice(empty_replies),
            "mood": "neutral",
        }

    # Дуже проста "оцінка настрою" за ключовими словами – лише для демо.
    lowered = user_text.lower()
    if any(word in lowered for word in ["сум", "погано", "самотн", "страх", "тривог"]):
        mood = "sad"
    elif any(word in lowered for word in ["раді", "щасливий", "добре", "класно"]):
        mood = "happy"
    else:
        mood = "neutral"

    # Набір різних емпатичних відповідей під настрій
    sad_replies = [
        (
            "Дякую, що поділився/поділилася тим, що тобі непросто. "
            "Твої почуття нормальні й важливі. Можеш трохи детальніше описати, "
            "що саме зараз найбільше тисне на тебе?"
        ),
        (
            "Звучить так, ніби тобі зараз важко. Я з тобою — давай обережно розберемо, "
            "що саме викликає цей стан. Чи було щось конкретне сьогодні, що посилило ці емоції?"
        ),
        (
            "Мені шкода, що ти це переживаєш. Ти не один/одна з цими відчуттями. "
            "Як ти це відчуваєш у тілі — напруження, втома, порожнеча?"
        ),
    ]

    happy_replies = [
        (
            "Радий чути про приємні емоції! Можеш розповісти, що саме зробило твій настрій кращим? "
            "Такі моменти корисно запам’ятовувати."
        ),
        (
            "Звучить радісно. Класно, що в твоєму дні є щось хороше. "
            "Що б ти хотів/хотіла зберегти з цього стану на майбутнє?"
        ),
        (
            "Це дуже цінно — помічати свої хороші відчуття. "
            "Як ти думаєш, що допомогло тобі відчути себе краще сьогодні?"
        ),
    ]

    neutral_replies = [
        (
            "Дякую за відвертість. Твої переживання важливі, навіть якщо вони здаються заплутаними. "
            "Що в цій ситуації турбує тебе найбільше?"
        ),
        (
            "Я чую, що все не так однозначно. Можеш описати, які думки найчастіше повертаються до тебе сьогодні?"
        ),
        (
            "Ти добре робиш, що пробуєш це проговорити. "
            "Якщо вибрати одне слово для твого стану зараз — яке б ти обрав/обрала?"
        ),
    ]

    if mood == "sad":
        reply = random.choice(sad_replies)
    elif mood == "happy":
        reply = random.choice(happy_replies)
    else:
        reply = random.choice(neutral_replies)

    # Збереження в БД через модуль data_base
    add_entry(user_text, mood)

    return {"reply": reply, "mood": mood}


@app.get("/api/history")
async def get_history(limit: int = 10):
    """
    Повертає останні N записів щоденника емоцій
    (для майбутнього графіка настрою).
    """
    history = get_entries(limit=limit)
    return {"items": history}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

