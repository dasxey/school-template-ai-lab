from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
from typing import Optional, Tuple
from data_base.db import (
    init_db,
    add_entry,
    get_entries,
    add_insight,
    get_insights,
)
import random
import os
import tempfile
import json
import logging
import subprocess
import shutil
import base64
from openai import OpenAI  # подключаем OpenAI SDK

from dotenv import load_dotenv
load_dotenv()

import sys
logger = logging.getLogger("mindheaven")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logger.addHandler(handler)

# ВНИМАНИЕ: не храни ключ в коде.
# Поставь переменную окружения: `export OPENAI_API_KEY="..."`.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")

PSYCHOLOGIST_SYSTEM = """Ти — «Віртуальний друг 2.0»: українськомовний віртуальний помічник та емпатійний розрадник для підлітків.
Твоя мета — допомагати долати труднощі перехідного періоду, використовуючи мудрість та емпатію. Ти надихаєшся досвідом Лесі Українки та Івана Франка, формуючи у підлітків ідентичність і критичне мислення.

Ти допомагаєш із:
- Стосунками (школа, батьки, друзі).
- Протидією булінгу, аб’юзу, харасменту, сталкінгу, мобінгу та лукізму, пошуком «Я» і делікатними питаннями дівчат.
- Викликами війни (страх, сум за домівкою, втома від війни, повітряні тривоги чи окупація).

Принципи ефективного спілкування (за Карлом Роджерсом та Брайаном Трейсі):
— Спілкування — це складна взаємодія і побудова довіри. Май чіткий НАМІР допомогти і переконайся, що твій фокус уваги на співрозмовнику.
— Використовуй емпатію та активне слухання: спочатку коротко відзеркаль емоцію або проблему людини (1 речення), щоб показати, що ти справді чуєш її.
— Обов’язково отримуй зворотний зв’язок: став відкриті питання («Як ти це бачиш?», «Чи відгукується це тобі?»), щоб перевірити розуміння і перетворити монолог на діалог.
— Далі м’яко підтримай: давай дружні поради, уникаючи оціночних суджень і моралізаторства.
— Пам'ятай: ти даєш професійні поради, але НЕ проводиш медичні консультації і не заміняєш кваліфіковану допомогу.
— Будь лаконічним (4–8 речень), пиши людяно.

Безпека та обмеження:
— Категорично заборонено генерувати сексуальний контент, жорстокість або поради, що можуть нашкодити.
— Відповідай ВИКЛЮЧНО на безпечні теми.
— Якщо тема розмови небезпечна (насильство, агресія), відповідай нейтрально, наголошуй на важливості фізичної і емоційної безпеки або відмовляйся підтримувати таку розмову."""


def _build_turn_history_for_llm(max_pairs: int = 6) -> list:
    """Останні записи з щоденника як чергування: користувач → асистент (як зберігає `add_entry`)."""
    limit = max(2, max_pairs * 2)
    entries = get_entries(limit=limit)
    messages = []
    for i, e in enumerate(entries):
        role = "user" if i % 2 == 0 else "assistant"
        t = (e.get("text") or "").strip()
        if not t:
            continue
        if len(t) > 700:
            t = t[:700] + "…"
        messages.append({"role": role, "content": t})
    return messages


def _hint_for_openai_error(exc_text: str) -> str:
    low = (exc_text or "").lower()
    if "openai_api_key" in low or "api key" in low or "401" in exc_text or "unauthorized" in low:
        return (
            "Перевір змінну OPENAI_API_KEY у терміналі перед запуском сервера: "
            'export OPENAI_API_KEY="sk-..." Потім перезапусти main.py чи uvicorn.'
        )
    if "429" in exc_text or "rate limit" in low:
        return "Занадто багато запитів до OpenAI. Зачекай 1–2 хвилини й спробуй знову."
    if "quota" in low or "billing" in low or "insufficient" in low or "credit" in low:
        return "Перевір баланс і біллінг на https://platform.openai.com (можливо закінчились кредити)."
    if "timeout" in low or "connection" in low or "network" in low or "resolve" in low:
        return "Немає стабільного зв’язку з OpenAI. Перевір інтернет або VPN."
    return "Переконайся, що ключ валідний, є інтернет і сервіс OpenAI доступний (status.openai.com)."


def _heuristic_mood_from_text(text: str) -> str:
    lowered = (text or "").lower()
    if any(w in lowered for w in ["сум", "погано", "самотн", "страх", "тривог", "важко"]):
        return "sad"
    if any(w in lowered for w in ["раді", "щаслив", "добре", "класно", "весел"]):
        return "happy"
    return "neutral"


def _emotion_ai_analyze(user_text: str, modality: str, visual_hint: str = "") -> Optional[str]:
    """Емоції за текстом + контекстом (голос / відео / кадр). Повертає sad|happy|neutral або None."""
    if openai_client is None:
        return None
    if not (user_text or "").strip() and not (visual_hint or "").strip():
        return None
    try:
        payload = {
            "user_text": (user_text or "").strip(),
            "modality": modality,
            "visual_hint": (visual_hint or "").strip(),
        }
        completion = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ти аналізуєш емоційний стан користувача. Відповідь одним JSON: "
                        '{"mood":"sad"|"happy"|"neutral","note_uk":"коротко українською, 1 речення"}. '
                        "modality: text | voice | video. Якщо є visual_hint — врахуй обличчя/позу."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.2,
            max_tokens=120,
        )
        raw = (completion.choices[0].message.content or "").strip()
        data = json.loads(raw)
        m = (data.get("mood") or "").strip().lower()
        if m in ("sad", "happy", "neutral"):
            return m
    except Exception as e:
        logger.warning("emotion_ai_analyze failed: %s", e)
    return None


def _resolve_mood(user_text: str, modality: str, visual_hint: str = "") -> str:
    ai = _emotion_ai_analyze(user_text, modality, visual_hint)
    if ai:
        return ai
    return _heuristic_mood_from_text(user_text)


def _psychologist_reply(user_content: str) -> Tuple[str, Optional[str]]:
    """Діалог з пам’яттю останніх реплік і стилем психолога."""
    if openai_client is None:
        return (
            "Зараз я не можу зв’язатися з сервісом підказок: не задано ключ OpenAI. "
            + _hint_for_openai_error("OPENAI_API_KEY не задан"),
            "OPENAI_API_KEY не задан.",
        )
    history = _build_turn_history_for_llm(6)
    messages: list = [{"role": "system", "content": PSYCHOLOGIST_SYSTEM}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_content})
    try:
        completion = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=0.78,
            max_tokens=520,
        )
        reply_text = (completion.choices[0].message.content or "").strip()
        if not reply_text:
            return ("Порожня відповідь від моделі. Спробуй ще раз.", "empty completion")
        return (reply_text, None)
    except Exception as e:
        err = str(e)
        logger.warning("openai chat error: %s", err)
        hint = _hint_for_openai_error(err)
        return (
            f"Не вдалося отримати відповідь від OpenAI. {hint}",
            err,
        )


def _complete_chat_turn(
    *,
    diary_user_text: str,
    prompt_for_model: str,
    modality: str,
    visual_hint: str = "",
    emotion_text: Optional[str] = None,
) -> dict:
    """Єдиний шлях: настрій → відповідь → щоденник → інсайт."""
    mood_src = emotion_text if emotion_text is not None else diary_user_text
    mood = _resolve_mood(mood_src, modality, visual_hint)
    reply_text, error_detail = _psychologist_reply(prompt_for_model)

    if error_detail:
        add_entry(diary_user_text, mood)
        add_entry(
            "[Сервіс: відповідь зараз недоступна — перевір OPENAI_API_KEY і інтернет.]",
            "neutral",
        )
        hint = _hint_for_openai_error(error_detail)
        return {
            "reply": reply_text,
            "mood": mood,
            "insight_saved": False,
            "error": error_detail,
            "hint_uk": hint,
        }

    add_entry(diary_user_text, mood)
    add_entry(reply_text, mood)

    insight_saved = False
    if reply_text:
        insight_saved = _extract_and_store_insight(diary_user_text, reply_text, mood)

    return {"reply": reply_text, "mood": mood, "insight_saved": insight_saved}


def _whisper_transcribe(file_path: Path) -> str:
    if openai_client is None:
        logger.warning("openai_client is None, skipping Whisper transcription.")
        return ""
    logger.info("Starting Whisper transcription for file: %s", file_path)
    with open(file_path, "rb") as audio_f:
        tr = openai_client.audio.transcriptions.create(
            model="gpt-4o-transcribe",
            language="uk",
            file=audio_f,
        )
    res = (tr.text or "").strip()
    logger.info("Whisper transcription completed. Length: %d chars", len(res))
    return res


def _ffmpeg_extract_audio(video_path: Path) -> Path:
    ffmpeg_bin = str(Path(__file__).resolve().parent.parent / "ffmpeg" / "bin" / "ffmpeg.exe")
    if not os.path.exists(ffmpeg_bin):
        if not shutil.which("ffmpeg"):
            logger.warning("ffmpeg not found in PATH for audio extraction. Sending original to Whisper.")
            return video_path
        ffmpeg_bin = "ffmpeg"
    
    logger.info("Starting ffmpeg audio extraction for video: %s using %s", video_path, ffmpeg_bin)
    out = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    out.close()
    out_path = Path(out.name)
    try:
        r = subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-i", str(video_path),
                "-q:a", "0",
                "-map", "a",
                str(out_path),
            ],
            capture_output=True,
            timeout=60,
        )
        if r.returncode != 0:
            logger.error("ffmpeg audio extraction failed with code %s. stderr: %s", r.returncode, r.stderr.decode('utf-8', errors='ignore'))
            out_path.unlink(missing_ok=True)
            return video_path
            
        logger.info("Successfully extracted audio to %s", out_path)
        return out_path
    except Exception as e:
        logger.warning("ffmpeg audio extraction error: %s", e)
        out_path.unlink(missing_ok=True)
        return video_path


def _ffmpeg_extract_frame(video_path: Path) -> Optional[Path]:
    ffmpeg_bin = str(Path(__file__).resolve().parent.parent / "ffmpeg" / "bin" / "ffmpeg.exe")
    if not os.path.exists(ffmpeg_bin):
        if not shutil.which("ffmpeg"):
            logger.warning("ffmpeg is not installed or not in PATH. Checked path: %s", ffmpeg_bin)
            return None
        ffmpeg_bin = "ffmpeg"
        
    logger.info("Starting ffmpeg frame extraction for video: %s using %s", video_path, ffmpeg_bin)
    out = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    out.close()
    out_path = Path(out.name)
    try:
        r = subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-i",
                str(video_path),
                "-ss",
                "00:00:00.500",
                "-vframes",
                "1",
                str(out_path),
            ],
            capture_output=True,
            timeout=45,
        )
        if r.returncode != 0:
            logger.error("ffmpeg failed with return code %s. stderr: %s", r.returncode, r.stderr.decode('utf-8', errors='ignore'))
            try:
                out_path.unlink(missing_ok=True)
            except OSError:
                pass
            return None
            
        if not out_path.exists() or out_path.stat().st_size < 80:
            logger.error("ffmpeg did not produce a valid output file. size: %s", out_path.stat().st_size if out_path.exists() else 'missing')
            try:
                out_path.unlink(missing_ok=True)
            except OSError:
                pass
            return None
            
        logger.info("Successfully extracted frame to %s", out_path)
        return out_path
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("ffmpeg frame extraction exception: %s", e)
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def _vision_frame_hint(image_path: Path) -> str:
    if openai_client is None:
        return ""
    try:
        b64 = base64.standard_b64encode(image_path.read_bytes()).decode("ascii")
        completion = openai_client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Коротко українською (1–2 речення): що видно з обличчя/пози людини, "
                                "який настрій (тривога/спокій/радість). Без моралі."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                    ],
                }
            ],
            max_tokens=150,
        )
        return (completion.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("vision frame: %s", e)
        return ""


def _extract_and_store_insight(user_text: str, reply_text: str, heuristic_mood: str) -> bool:
    """Один короткий виклик моделі: що саме варто запам'ятати для друга-помічника."""
    if openai_client is None or len(user_text.strip()) < 8:
        return False
    system = (
        "Ти частина застосунку «друг-помічник». З повідомлення користувача та короткої відповіді асистента "
        "визнач, чи є щось важливе для довгострокової пам'яті (те, що сильно хвилює, радує або є ключовим фактом про людину). "
        "Відповідь строго одним JSON-об'єктом полями: "
        "save (boolean) — чи зберігати в щоденник важливого; "
        "summary (string, українською, до 160 символів) — нейтральний зміст без моралі; "
        "polarity одне з: worry, joy, neutral — переважний тон для цього запису; "
        "importance число 1–5 (5 — максимально важливо повернутися до цього пізніше); "
        "quote (string) — дуже коротка цитата з тексту користувача або порожній рядок. "
        "save=true лише якщо importance >= 3 і є конкретний зміст (не привітання/жарти без підстав)."
    )
    user_payload = json.dumps(
        {
            "user_message": user_text,
            "assistant_reply": reply_text[:500],
            "heuristic_mood": heuristic_mood,
        },
        ensure_ascii=False,
    )
    try:
        completion = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_payload},
            ],
            temperature=0.25,
            max_tokens=220,
        )
        raw = (completion.choices[0].message.content or "").strip()
        data = json.loads(raw)
    except Exception as e:
        logger.warning("insight extraction failed: %s", e)
        return False

    if not data.get("save"):
        return False
    try:
        importance = int(data.get("importance", 0))
    except (TypeError, ValueError):
        importance = 0
    if importance < 3:
        return False
    summary = (data.get("summary") or "").strip()
    if not summary:
        return False
    pol = (data.get("polarity") or "neutral").strip().lower()
    if pol not in ("worry", "joy", "neutral"):
        pol = "neutral"
    quote = (data.get("quote") or "").strip()
    add_insight(summary, pol, importance, quote or None)
    return True


# ==========================
# FastAPI app
# ==========================
app = FastAPI(title="MindHeaven API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================
# Путь к фронтенду и отдача index.html
# ==========================
BASE_DIR = Path(__file__).parent.parent
app.mount("/visual", StaticFiles(directory=str(BASE_DIR / "visual")), name="visual")

@app.get("/")
def read_index():
    return FileResponse(str(BASE_DIR / "visual" / "index.html"))


@app.get("/diary.html")
def diary_alias():
    """Старе посилання diary.html з кореня → коректний шлях до статики."""
    return RedirectResponse(url="/visual/diary.html", status_code=307)


# ==========================
# Startup
# ==========================
@app.on_event("startup")
def on_startup():
    init_db()

# ==========================
# Проверка здоровья
# ==========================
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "app": "MindHeaven",
        "openai_configured": bool(OPENAI_API_KEY),
    }

# ==========================
# Текстовые сообщения
# ==========================
class MessageIn(BaseModel):
    text: str

@app.post("/api/message")
async def message_endpoint(payload: MessageIn):
    user_text = (payload.text or "").strip()
    if not user_text:
        empty_replies = [
            "Я поруч. Розкажи кількома реченнями: що з тобою зараз відбувається і що з цього найважче?",
            "Можеш написати одне слово про свій стан — а я запитаю далі. З чого хочеш почати?",
            "Я слухаю. Що зараз у тебе на думці або в тілі — перше, що спливло?",
        ]
        return {"reply": random.choice(empty_replies), "mood": "neutral", "insight_saved": False}

    return _complete_chat_turn(
        diary_user_text=user_text,
        prompt_for_model=user_text,
        modality="text",
    )


# ==========================
# Голос: Whisper → текст → той самий діалог, що й у тексті
# ==========================
@app.post("/api/voice")
async def voice_endpoint(audio: UploadFile = File(...)):
    tmp_path: Optional[Path] = None
    try:
        raw = await audio.read()
        if not raw:
            raise HTTPException(status_code=400, detail="Порожній аудіофайл")

        suffix = Path(audio.filename or "rec.webm").suffix.lower()
        if suffix not in (".webm", ".m4a", ".mp3", ".wav", ".mp4", ".mpeg", ".mpga", ".ogg"):
            suffix = ".webm"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)

        if openai_client is None:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY не задан.")

        transcript = _whisper_transcribe(tmp_path)
        if not transcript:
            return {
                "reply": "Не вдалося розпізнати мовлення. Спробуй ще раз або напиши текстом.",
                "mood": "neutral",
                "text": "",
                "transcript": "",
                "insight_saved": False,
            }

        diary_line = f"[Голос → текст] {transcript}"
        prompt = (
            "Користувач надіслав ГОЛОСОВЕ повідомлення; нижче текст, автоматично розпізнаний з аудіо. "
            "Відповідай українською як друг-помічник.\n\n"
            f"Текст:\n{transcript}"
        )
        result = _complete_chat_turn(
            diary_user_text=diary_line,
            prompt_for_model=prompt,
            modality="voice",
            emotion_text=transcript,
        )
        result["text"] = transcript
        result["transcript"] = transcript
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("voice_endpoint")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


# ==========================
# Відео-кружок: Whisper (аудіо) + кадр через ffmpeg + vision (якщо є ffmpeg)
# ==========================
@app.post("/api/video")
async def video_endpoint(video: UploadFile = File(...)):
    logger.info("Received POST /api/video request. Filename: %s", video.filename)
    tmp_path: Optional[Path] = None
    frame_path: Optional[Path] = None
    try:
        raw = await video.read()
        if not raw:
            raise HTTPException(status_code=400, detail="Порожній відеофайл")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)

        if openai_client is None:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY не задан.")

        audio_path = _ffmpeg_extract_audio(tmp_path)
        try:
            transcript = _whisper_transcribe(audio_path)
        finally:
            if audio_path != tmp_path:
                try:
                    audio_path.unlink(missing_ok=True)
                except OSError:
                    pass

        visual_hint = ""
        frame_path = _ffmpeg_extract_frame(tmp_path)
        if frame_path is not None:
            try:
                visual_hint = _vision_frame_hint(frame_path)
            finally:
                try:
                    frame_path.unlink()
                except OSError:
                    pass
            frame_path = None

        diary_lines = []
        if transcript:
            diary_lines.append(f"[Відео, аудіо] {transcript}")
        if visual_hint:
            diary_lines.append(f"[Кадр кружка] {visual_hint}")
        if not diary_lines:
            diary_text = "[Відео-кружок] Немає розпізнаного мовлення; опис кадру недоступний (потрібен ffmpeg для кадру)."
        else:
            diary_text = "\n".join(diary_lines)

        prompt_parts = []
        if transcript:
            prompt_parts.append(f"Розпізнаний текст з аудіо доріжки відео-кружка:\n{transcript}")
        if visual_hint:
            prompt_parts.append(f"Опис того, що видно на кадрі (обличчя, настрій):\n{visual_hint}")
        if not prompt_parts:
            prompt_for_model = (
                "Користувач надіслав відео-кружок, але без чіткого мовлення та без опису кадру. "
                "Підтримай м'яко, запропонуй описати словами, що відчуває зараз."
            )
        else:
            prompt_for_model = (
                "Користувач надіслав ВІДЕО-КРУЖОК. Використай дані нижче. Відповідай українською як друг-помічник.\n\n"
                + "\n\n".join(prompt_parts)
            )

        emotion_src = transcript or diary_text
        result = _complete_chat_turn(
            diary_user_text=diary_text,
            prompt_for_model=prompt_for_model,
            modality="video",
            visual_hint=visual_hint,
            emotion_text=emotion_src,
        )
        
        logger.info("Successfully completed processing video turn. Mood: %s", result.get("mood"))
        
        result["text"] = transcript
        result["transcript"] = transcript
        result["visual_hint"] = visual_hint
        return result
    except HTTPException as e:
        logger.warning("HTTPException in video_endpoint: %s", e.detail)
        raise
    except Exception as e:
        logger.exception("video_endpoint")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass

# ==========================
# История сообщений
# ==========================
@app.get("/api/history")
async def get_history(limit: int = 10):
    history = get_entries(limit=limit)
    return {"items": history}


@app.get("/api/insights")
async def get_insights_api(limit: int = 80):
    items = get_insights(limit=limit)
    return {"items": items}


# ==========================
# Точка входа
# ==========================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=True)