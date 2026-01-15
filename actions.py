from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, AllSlotsReset


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def get_lang(tracker: Tracker) -> str:
    lang = _norm(tracker.get_slot("lang"))
    return "mn" if lang == "mn" else "en"


def looks_like_mn(text: str) -> bool:
    return bool(re.search(r"[А-Яа-яӨөҮү]", text))


def parse_int_from_text(text: str, default: int = 7) -> int:
    m = re.search(r"(\d+)", _norm(text))
    if not m:
        return default
    d = int(m.group(1))
    return d if d > 0 else default


def parse_budget_to_usd(budget_text: str) -> Tuple[Optional[float], str]:
    """
    Rough parser. If MNT detected -> convert with ~3500 MNT = 1 USD (approx).
    """
    s = _norm(budget_text)
    if not s:
        return None, budget_text

    num_match = re.search(r"(\d[\d,\.]*)", s)
    if not num_match:
        return None, budget_text

    raw = num_match.group(1).replace(",", "")
    try:
        amount = float(raw)
    except ValueError:
        return None, budget_text

    is_mnt = ("₮" in s) or ("mnt" in s) or ("төг" in s) or ("сая" in s)
    is_usd = ("$" in s) or ("usd" in s) or ("dollar" in s)

    if "сая" in s:
        amount *= 1_000_000
        is_mnt = True

    if is_usd and not is_mnt:
        return amount, budget_text

    if is_mnt and not is_usd:
        return amount / 3500.0, budget_text

    # fallback guess
    if amount <= 10000:
        return amount, budget_text
    return amount / 3500.0, budget_text


def interest_bucket(interest: str) -> str:
    s = _norm(interest)
    if any(k in s for k in ["байгаль", "nature", "lake", "mountain"]):
        return "nature"
    if any(k in s for k in ["соёл", "culture", "museum", "history", "temple"]):
        return "culture"
    if any(k in s for k in ["адал", "adventure", "gobi", "camel", "horse"]):
        return "adventure"
    if any(k in s for k in ["тайван", "quiet", "relax"]):
        return "quiet"
    return "mixed"


def country_cluster(country: str) -> str:
    c = _norm(country)
    east = ["japan", "korea", "china", "taiwan", "hong kong", "япон", "солонгос", "хятад", "тайвань"]
    west = ["usa", "united states", "canada", "uk", "england", "germany", "france", "italy", "spain", "australia", "европ"]
    if any(x in c for x in east):
        return "east_asia"
    if any(x in c for x in west):
        return "west"
    return "other"


def mn_or_en(tracker: Tracker, mn: str, en: str) -> str:
    return mn if get_lang(tracker) == "mn" else en


def bullet(lines: List[str]) -> str:
    return "\n".join(f"• {x}" for x in lines)


def build_itinerary(days: int, bucket: str) -> List[str]:
    if days <= 3:
        return [
            "Day 1: Улаанбаатар — музей + төв талбай + оройн хоол",
            "Day 2: Тэрэлж эсвэл Хустайн нуруу (өдрийн аялал)",
            "Day 3: УБ — чөлөөт өдөр + буцах"
        ]

    if 4 <= days <= 6:
        plan = [
            "Day 1: Улаанбаатар — хотын өдөр",
            "Day 2: Тэрэлж — байгаль + морь (хүсвэл)",
            "Day 3: Хустайн нуруу — зэрлэг адуу",
            "Day 4: Хархорин–Эрдэнэзуу — соёл/түүх",
        ]
        if days >= 5:
            plan.append("Day 5: Орхоны хөндий / Улаан цутгалан (зам/улирал таарвал)")
        if days >= 6:
            plan.append("Day 6: УБ — амрах + буцах бэлтгэл")
        return plan

    # 7+ days
    if bucket == "adventure":
        plan = [
            "Day 1: Улаанбаатар — хотын өдөр",
            "Day 2: Цагаан суварга",
            "Day 3: Ёлын ам",
            "Day 4: Хонгорын элс",
            "Day 5: Баянзаг (Flaming Cliffs)",
            "Day 6: Улаанбаатар — буцах/амрах",
            "Day 7: Нөөц өдөр: Тэрэлж эсвэл хотын нэмэлт"
        ]
        if days >= 8:
            plan.append("Day 8: Их газрын чулуу (бага очдог, өвөрмөц хад)")
        if days >= 9:
            plan.append("Day 9: Хустайн нуруу (зэрлэг адуу)")
        if days >= 10:
            plan.append("Day 10: УБ — чөлөөт өдөр")
        return plan

    # nature/culture/quiet/mixed
    plan = [
        "Day 1: Улаанбаатар — хотын өдөр",
        "Day 2: Архангай руу (замын аялал)",
        "Day 3: Хорго–Тэрхийн Цагаан нуур",
        "Day 4: Хархорин–Эрдэнэзуу",
        "Day 5: Нэмэлт: Амарбаясгалант хийд (бага очдог) эсвэл Орхон",
        "Day 6: Улаанбаатар — буцах/амрах",
        "Day 7: Хустайн нуруу эсвэл Тэрэлж (day trip)"
    ]
    if days >= 8:
        plan.append("Day 8: Нөөц өдөр + shopping/кафе")
    if days >= 9:
        plan.append("Day 9: (Optional) Хөвсгөл рүү дотоод нислэгээр цаг хэмнэх")
    if days >= 10:
        plan.append("Day 10: Амралт + буцах")
    return plan


class ActionSetLanguage(Action):
    def name(self) -> str:
        return "action_set_language"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        text = tracker.latest_message.get("text", "")
        lang = None

        # entity lang (if any)
        for e in tracker.latest_message.get("entities", []):
            if e.get("entity") == "lang":
                lang = _norm(e.get("value"))
                break

        # allow plain words
        t = _norm(text)
        if not lang:
            if "монгол" in t or t == "mn":
                lang = "mn"
            elif "english" in t or t == "en":
                lang = "en"

        # fallback auto-detect
        if lang not in ["mn", "en"]:
            lang = "mn" if looks_like_mn(text) else "en"

        dispatcher.utter_message(text=("Ок ✅ Одооноос Монгол хэлээр ажиллая." if lang == "mn" else "OK ✅ Switching to English."))
        return [SlotSet("lang", lang)]


class ActionGreet(Action):
    def name(self) -> str:
        return "action_greet"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        msg = mn_or_en(
            tracker,
            "Сайн байна уу 👋 Би Монголын аяллын зөвлөх бот. ‘аялал’ гэж бичвэл төлөвлөж эхэлнэ. Хэл солих: /set_language{\"lang\":\"en\"}",
            "Hi 👋 I’m your Mongolia travel advisor. Type ‘travel’ to start. Switch: /set_language{\"lang\":\"mn\"}"
        )
        dispatcher.utter_message(text=msg)
        return []


class ActionHelp(Action):
    def name(self) -> str:
        return "action_help"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        msg = mn_or_en(
            tracker,
            "Тусламж 🧭\n• аялал — төлөвлөлт эхлүүлнэ\n• хаашаа очих вэ — зөвлөмж\n• байрлах газар — байр/ger camp\n• зардал — төсөв\n• reset — шинээр эхлэх",
            "Help 🧭\n• travel — start planning\n• where to go — recommendations\n• accommodation — stays/ger camps\n• cost — budget\n• reset — start over"
        )
        dispatcher.utter_message(text=msg)
        return []


class ActionResetRouting(Action):
    def name(self) -> str:
        return "action_reset_routing"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        keep_lang = get_lang(tracker)
        dispatcher.utter_message(text=mn_or_en(tracker, "Шинээр эхэлж байна…", "Starting over…"))
        return [AllSlotsReset(), SlotSet("lang", keep_lang)]


class ActionSubmitTravelPlan(Action):
    def name(self) -> str:
        return "action_submit_travel_plan"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        lang = get_lang(tracker)

        country = str(tracker.get_slot("country") or "Unknown")
        days = parse_int_from_text(str(tracker.get_slot("days") or "7"), default=7)
        budget_text = str(tracker.get_slot("budget") or "")
        interest = str(tracker.get_slot("interest") or "mixed")
        month = str(tracker.get_slot("month") or "")

        usd_est, _ = parse_budget_to_usd(budget_text)
        bucket = interest_bucket(interest)
        cluster = country_cluster(country)

        itinerary = build_itinerary(days, bucket)

        # “өмнө нь харж байгаагүй” нэмэлт санаануудыг country cluster-ээр бага зэрэг ялгая
        offbeat = []
        if cluster == "east_asia":
            offbeat = ["Их газрын чулуу (өвөрмөц хад)", "Амарбаясгалант хийд (нам тайван)", "Хустайн нуруу (зэрлэг адуу)"]
        elif cluster == "west":
            offbeat = ["Цагаан суварга (драматик canyon vibe)", "Амарбаясгалант хийд", "Орхоны хөндий"]
        else:
            offbeat = ["Хустайн нуруу", "Их газрын чулуу", "Орхоны хөндий"]

        # accommodation tier
        if usd_est is None:
            tier = "mid"
        elif usd_est < 700:
            tier = "budget"
        elif usd_est < 1600:
            tier = "mid"
        else:
            tier = "premium"

        accom_mn = {
            "budget": ["УБ: hostel/guesthouse (төвд ойр)", "Хөдөө: basic ger camp", "Group tour сонговол хямд"],
            "mid": ["УБ: 3–4* hotel эсвэл apartment", "Хөдөө: comfortable ger camp (хоолтой)", "Жижиг групп эсвэл private 4x4 (зарим өдөр)"],
            "premium": ["УБ: 4–5* hotel", "Хөдөө: premium ger camp (private bathroom)", "Private 4x4 + дотоод нислэг (цаг хэмнэнэ)"]
        }

        accom_en = {
            "budget": ["UB: hostel/guesthouse (central)", "Countryside: basic ger camps", "Group tours save money"],
            "mid": ["UB: 3–4* hotel or apartment", "Countryside: comfortable ger camps (meals)", "Small group or partial private 4x4"],
            "premium": ["UB: 4–5* hotel", "Countryside: premium ger camps (private bathroom)", "Private 4x4 + domestic flights to save time"]
        }

        # cost overview
        cost_lines_mn = []
        cost_lines_en = []
        if usd_est is not None:
            per_day = usd_est / max(days, 1)
            cost_lines_mn = [f"Нийт ~${usd_est:.0f} → өдөрт ~${per_day:.0f}", "Хуваарилалт: байр 30–40%, tour/унаа 35–50%, хоол 15–20%"]
            cost_lines_en = [f"Total ~${usd_est:.0f} → ~${per_day:.0f}/day", "Split: stays 30–40%, tours/transport 35–50%, food 15–20%"]
        else:
            cost_lines_mn = ["Төсвөө $/₮-өөр тодорхой хэлбэл илүү нарийн гаргана.", "Ерөнхий хуваарилалт: байр 30–40%, tour/унаа 35–50%, хоол 15–20%"]
            cost_lines_en = ["Share budget in $/₮ for a more precise estimate.", "General split: stays 30–40%, tours/transport 35–50%, food 15–20%"]

        if lang == "mn":
            msg = (
                "✅ Танд тохируулсан аяллын төлөвлөгөө\n"
                f"• Улс: {country}\n• Хугацаа: {days} өдөр\n• Төсөв: {budget_text}\n• Сонирхол: {interest}\n• Сар: {month}\n\n"
                "🗓️ Day-by-day itinerary:\n" + "\n".join(itinerary) + "\n\n"
                "🧭 Өмнө нь харж байгаагүй гоё сонголтууд:\n" + bullet(offbeat) + "\n\n"
                f"🏨 Байрлах зөвлөмж ({tier}):\n" + bullet(accom_mn[tier]) + "\n\n"
                "💸 Зардлын зураглал:\n" + bullet(cost_lines_mn) + "\n\n"
                "Дараагийн командууд:\n• хаашаа очих вэ\n• байрлах газар\n• цаг агаар\n• унаа\n• аюулгүй\n• зардлыг задал"
            )
        else:
            msg = (
                "✅ Personalized travel plan\n"
                f"• From: {country}\n• Duration: {days} days\n• Budget: {budget_text}\n• Preference: {interest}\n• Month: {month}\n\n"
                "🗓️ Day-by-day itinerary:\n" + "\n".join(itinerary) + "\n\n"
                "🧭 Off-the-beaten-path picks:\n" + bullet(offbeat) + "\n\n"
                f"🏨 Accommodation ({tier}):\n" + bullet(accom_en[tier]) + "\n\n"
                "💸 Cost overview:\n" + bullet(cost_lines_en) + "\n\n"
                "Next commands:\n• where to go\n• accommodation\n• weather\n• transport\n• safety\n• detailed breakdown"
            )

        dispatcher.utter_message(text=msg)
        return []


class ActionAnswerPlaces(Action):
    def name(self) -> str:
        return "action_answer_places"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        dispatcher.utter_message(text=mn_or_en(
            tracker,
            "🗺️ Санал болгох газрууд:\n• Хустайн нуруу\n• Их газрын чулуу\n• Амарбаясгалант хийд\n• Архангай (Хорго–Тэрхий)\n• Говь (Цагаан суварга–Ёлын ам–Хонгорын элс)",
            "🗺️ Recommended places:\n• Hustai NP\n• Ikh Gazriin Chuluu\n• Amarbayasgalant Monastery\n• Arkhangai (Khorgo–Terkhiin)\n• Gobi (Tsagaan Suvarga–Yolyn Am–Khongor Dunes)"
        ))
        return []


class ActionAnswerAccommodation(Action):
    def name(self) -> str:
        return "action_answer_accommodation"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        dispatcher.utter_message(text=mn_or_en(
            tracker,
            "🏨 Байрлах зөвлөмж:\n• УБ: төвийн hotel/apartment\n• Хөдөө: ger camp (private bathroom хэрэгтэй бол заавал лавла)\n• Орой сэрүүн — layering",
            "🏨 Accommodation tips:\n• UB: central hotel/apartment\n• Countryside: ger camps (ask for private bathroom)\n• Evenings can be chilly—bring layers"
        ))
        return []


class ActionAnswerWeather(Action):
    def name(self) -> str:
        return "action_answer_weather"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        month = str(tracker.get_slot("month") or "")
        dispatcher.utter_message(text=mn_or_en(
            tracker,
            f"🌤️ Цаг агаар ({month}): өдөр дулаан, орой сэрүүн. Салхи/тоос, гэнэтийн бороо байж болно. Салхины хамгаалалттай хүрэм + нарны тос + ус авч яваарай.",
            f"🌤️ Weather ({month}): warm days, cool evenings. Wind/dust and sudden rain can happen. Pack a windbreaker, sunscreen, and water."
        ))
        return []


class ActionAnswerTransport(Action):
    def name(self) -> str:
        return "action_answer_transport"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        dispatcher.utter_message(text=mn_or_en(
            tracker,
            "🚗 Тээвэр:\n• Хот: taxi/ride apps\n• Аймаг хооронд: дотоодын нислэг/автобус/private tour\n• Хөдөө: 4x4 хэрэгтэй үе олон",
            "🚗 Transport:\n• City: taxis/ride apps\n• Between regions: flights/bus/private tours\n• Countryside: often needs a 4x4"
        ))
        return []


class ActionAnswerSafety(Action):
    def name(self) -> str:
        return "action_answer_safety"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        dispatcher.utter_message(text=mn_or_en(
            tracker,
            "🛡️ Аюулгүй:\n• Хот: эд зүйлээ анхаар\n• Хөдөө: оффлайн map + power bank\n• Нар/хуурайшилт: ус сайн уух, нарны тос",
            "🛡️ Safety:\n• City: watch valuables\n• Countryside: offline maps + power bank\n• Sun/dry air: hydrate + sunscreen"
        ))
        return []


class ActionAnswerCost(Action):
    def name(self) -> str:
        return "action_answer_cost"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        dispatcher.utter_message(text=mn_or_en(
            tracker,
            "💸 Зардал: budget/mid/premium гэж ангилж болно. Төсөв + өдөр хэлбэл илүү нарийн гаргана. ‘нарийн тооцоо’ гэж бичээд үз.",
            "💸 Cost: can be budget/mid/premium. Share days + budget for a better estimate. Try ‘detailed breakdown’."
        ))
        return []


class ActionDetailedBreakdown(Action):
    def name(self) -> str:
        return "action_detailed_breakdown"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        days = parse_int_from_text(str(tracker.get_slot("days") or "7"), default=7)
        budget_text = str(tracker.get_slot("budget") or "")
        usd_est, _ = parse_budget_to_usd(budget_text)

        if usd_est is None:
            dispatcher.utter_message(text=mn_or_en(
                tracker,
                "Нарийн тооцоо хийхийн тулд төсвөө тодорхой бичнэ үү (ж: 1200$, 2 сая₮).",
                "For a detailed breakdown, please provide a clear budget (e.g., $1200 or 2 million ₮)."
            ))
            return []

        stay = usd_est * 0.35
        tours = usd_est * 0.45
        food = usd_est * 0.15
        misc = usd_est * 0.05

        dispatcher.utter_message(text=mn_or_en(
            tracker,
            "🧾 Нарийн тооцоо (ойролцоо)\n"
            f"• Нийт ~${usd_est:.0f} / {days} өдөр\n"
            f"• Байр ~${stay:.0f}\n• Аялал/унаа ~${tours:.0f}\n• Хоол ~${food:.0f}\n• Бусад ~${misc:.0f}",
            "🧾 Detailed breakdown (rough)\n"
            f"• Total ~${usd_est:.0f} / {days} days\n"
            f"• Stays ~${stay:.0f}\n• Tours/Transport ~${tours:.0f}\n• Food ~${food:.0f}\n• Misc ~${misc:.0f}"
        ))
        return []


class ActionFallback(Action):
    def name(self) -> str:
        return "action_fallback"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        text = _norm(tracker.latest_message.get("text", ""))

        # quick bye/thanks handling
        if any(k in text for k in ["bye", "баяртай", "дараа"]):
            dispatcher.utter_message(text=mn_or_en(tracker, "Баяртай 👋", "Bye 👋"))
            return []
        if any(k in text for k in ["thanks", "thank", "баярлалаа"]):
            dispatcher.utter_message(text=mn_or_en(tracker, "Таатай байна 😊", "Happy to help 😊"))
            return []

        dispatcher.utter_message(text=mn_or_en(
            tracker,
            "Уучлаарай, яг ойлгосонгүй 😅 Дараахыг турш:\n• аялал\n• хаашаа очих вэ\n• байрлах газар\n• цаг агаар\n• унаа\n• аюулгүй\n• reset",
            "Sorry, I didn’t catch that 😅 Try:\n• travel\n• where to go\n• accommodation\n• weather\n• transport\n• safety\n• reset"
        ))
        return []
