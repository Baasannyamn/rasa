from __future__ import annotations
import re
from typing import Any, Dict, List, Text, Optional

from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import EventType, SlotSet
from rasa_sdk.forms import FormValidationAction


# ---------- helpers ----------
MONTHS_EN = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
INTERESTS = {"nature", "culture", "adventure", "city", "food", "photography"}

def parse_number(text: str) -> Optional[float]:
    if not text:
        return None
    t = text.replace(",", ".")
    m = re.search(r"(-?\d+(?:\.\d+)?)", t)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None

def normalize_month(raw: str) -> Optional[int]:
    if not raw:
        return None
    s = raw.strip().lower()
    # "7 сар", "12" гэх мэт
    n = parse_number(s)
    if n is not None:
        mn = int(n)
        if 1 <= mn <= 12:
            return mn
        return None
    # "July"
    s2 = re.sub(r"[^a-z]", "", s)
    if s2 in MONTHS_EN:
        return MONTHS_EN[s2]
    return None

def origin_bucket(country: str) -> str:
    c = (country or "").strip().lower()
    east_asia = ["japan", "korea", "china", "taiwan", "hong kong", "singapore"]
    europe = ["germany", "france", "uk", "united kingdom", "italy", "spain", "netherlands", "sweden", "norway", "finland"]
    north_america = ["usa", "united states", "canada", "mexico"]
    if any(x in c for x in east_asia):
        return "east_asia"
    if any(x in c for x in europe):
        return "europe"
    if any(x in c for x in north_america):
        return "north_america"
    return "other"

def build_reco(country: str, days: int, budget: float, interest: str, month: int) -> Dict[str, Any]:
    bucket = origin_bucket(country)
    interest = (interest or "nature").lower()
    # “илүү өвөрмөц” санал (түгээмэл Terelj/Gobi-г бүрэн хаяхгүй, гэхдээ alternate-ыг түлхүү)
    alt_by_bucket = {
        "east_asia": [
            "Хэнтийн нуруу – Балдан Бэрээвэн хийд, Өглөгчийн хэрэм (бага очдог чиглэл)",
            "Дорнодын тал – Буйр нуур, Мэнэнгийн тал (зун зураг авалт гайхалтай)",
            "Завхан – Улаагчны Хар нуур, Отгонтэнгэр орчим"
        ],
        "europe": [
            "Алтай – Хотон, Хурган нуур (маш өвөрмөц уул-нуурын маршрут)",
            "Хөвсгөлийн хойд – Цаатан чиглэл (хууль ёсны зөвшөөрөл/бэлтгэлтэй)",
            "Архангай – Тайхар чулуу, Хоргын тогоо, Тэрхийн цагаан нуур"
        ],
        "north_america": [
            "Өмнөговийн “жуулчин ихтэй” хэсгээс гадна – Ноён уул/Цагаан суваргын өргөн тойрог",
            "Увс – Хяргас нуур, Увс нуурын сав (алслагдмал, сонин)",
            "Ховд – Хар-Ус нуур, Манхан элс"
        ],
        "other": [
            "Архангай – Хорго-Тэрхийн цогцолбор",
            "Завхан – Хар нуурын бүс",
            "Хөвсгөл – Хатгал, Жанхай"
        ],
    }
    base_places = alt_by_bucket.get(bucket, alt_by_bucket["other"])

    # хугацаанд тааруулж (days)
    if days <= 4:
        plan = [
            "Улаанбаатар (1 өдөр): төв музей + хоол",
            "Төв аймаг/Тэрэлж (1 өдөр): ойролцоох байгаль",
            "Нэмэлт 1–2 өдөр: " + base_places[0]
        ]
    elif days <= 8:
        plan = [
            "Улаанбаатар (1–2 өдөр)",
            "Ойр чиглэл (1–2 өдөр): Тэрэлж эсвэл Хустайн нуруу",
            "Өвөрмөц чиглэл (3–4 өдөр): " + base_places[0],
            "Нэмэлт өдөр: " + base_places[1]
        ]
    else:
        plan = [
            "Улаанбаатар (2 өдөр)",
            "Өвөрмөц чиглэл #1 (4–5 өдөр): " + base_places[0],
            "Өвөрмөц чиглэл #2 (4–5 өдөр): " + base_places[1],
            "Хэрэв амжвал: " + base_places[2]
        ]

    # budget зөвлөмж (rough)
    if budget < 600:
        budget_tip = "Төсөв бага тул: guesthouse/hostel + shared tour + хот дотор нийтийн тээвэр түлхүү."
    elif budget < 1500:
        budget_tip = "Дундаж төсөв: UB hotel + countryside camp/ger + group tour хамгийн зөв."
    else:
        budget_tip = "Өндөр төсөв: private driver + сайн кемп/буудал + дотоод нислэг (алслагдсан газар) боломжтой."

    # month weather hint (simple)
    if month in (12, 1, 2):
        weather = "Өвөл маш хүйтэн (-20°C…-35°C). Зөв хувцас, дулаан байр зайлшгүй."
    elif month in (6, 7, 8):
        weather = "Зун дулаан (15°C…30°C). Гэхдээ шөнөдөө сэрүүн, бороо салхи үе үе."
    else:
        weather = "Хавар/Намар сэрүүхэн, салхитай. Давхар хувцас + салхины хамгаалалт хэрэгтэй."

    # interest-based add-ons
    addon = []
    if interest == "culture":
        addon.append("Соёл: Чингис хаан музей/түүхийн музей + хийдүүд (Амарбаясгалант/Балдан Бэрээвэн).")
    if interest == "adventure":
        addon.append("Адал явдал: морин аялал 1–2 өдөр + offroad route (зөв оператор сонгох).")
    if interest == "food":
        addon.append("Хоол: хуушуур/цуйван/хорхог, мөн coffee shop tour (UB).")
    if interest == "photography":
        addon.append("Зураг: нар мандах/шингэх цэгүүд + тал нутгийн одтой тэнгэр (гэрэл багатай газар).")
    if interest == "city":
        addon.append("Хот: UB-д 1–2 өдөр илүү авч shopping + art gallery оруул.")

    return {
        "plan": plan,
        "budget_tip": budget_tip,
        "weather": weather,
        "addon": addon,
        "base_places": base_places
    }


# ---------- form validation ----------
class ValidateTravelForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_travel_form"

    async def validate_country(self, slot_value: Any, dispatcher: CollectingDispatcher,
                               tracker: Tracker, domain: Dict[Text, Any]) -> Dict[Text, Any]:
        v = str(slot_value or "").strip()
        if len(v) < 2:
            dispatcher.utter_message(text="Улсаа зөв бичнэ үү. (Ж: Japan, Korea, USA)||Please type a valid country. (e.g., Japan, Korea, USA)")
            return {"country": None}
        return {"country": v}

    async def validate_days(self, slot_value: Any, dispatcher: CollectingDispatcher,
                            tracker: Tracker, domain: Dict[Text, Any]) -> Dict[Text, Any]:
        num = parse_number(str(slot_value))
        if num is None:
            dispatcher.utter_message(text="Өдрийн тоог зөвхөн тоогоор өгнө үү. (Ж: 5)||Please enter days as a number. (e.g., 5)")
            return {"days": None}
        days = int(num)
        if not (1 <= days <= 30):
            dispatcher.utter_message(text="1-30 хооронд өдөр өгнө үү.||Please enter days between 1 and 30.")
            return {"days": None}
        return {"days": float(days)}

    async def validate_budget(self, slot_value: Any, dispatcher: CollectingDispatcher,
                              tracker: Tracker, domain: Dict[Text, Any]) -> Dict[Text, Any]:
        num = parse_number(str(slot_value))
        if num is None or num <= 0:
            dispatcher.utter_message(text="Төсвөө тоогоор өгнө үү. (Ж: 800)||Please enter budget as a number. (e.g., 800)")
            return {"budget": None}
        return {"budget": float(num)}

    async def validate_interest(self, slot_value: Any, dispatcher: CollectingDispatcher,
                                tracker: Tracker, domain: Dict[Text, Any]) -> Dict[Text, Any]:
        v = str(slot_value or "").strip().lower()
        # mongolian -> english mapping
        mapping = {
            "байгаль": "nature",
            "соёл": "culture",
            "адал": "adventure",
            "адал явдал": "adventure",
            "хот": "city",
            "хоол": "food",
            "зураг": "photography",
            "photography": "photography",
        }
        v = mapping.get(v, v)
        if v not in INTERESTS:
            dispatcher.utter_message(
                text="Сонирхлоо сонгоно уу: nature/culture/adventure/city/food/photography||Choose one: nature/culture/adventure/city/food/photography"
            )
            return {"interest": None}
        return {"interest": v}

    async def validate_month(self, slot_value: Any, dispatcher: CollectingDispatcher,
                             tracker: Tracker, domain: Dict[Text, Any]) -> Dict[Text, Any]:
        m = normalize_month(str(slot_value))
        if m is None:
            dispatcher.utter_message(text="Сараа 1-12 эсвэл July гэх мэтээр өгнө үү.||Enter month as 1-12 or e.g., July.")
            return {"month": None}
        return {"month": str(m)}


# ---------- actions ----------
class ActionTripSummary(Action):
    def name(self) -> Text:
        return "action_trip_summary"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        country = tracker.get_slot("country") or ""
        days = int(float(tracker.get_slot("days") or 0))
        budget = float(tracker.get_slot("budget") or 0)
        interest = tracker.get_slot("interest") or "nature"
        month = int(float(tracker.get_slot("month") or 7))

        reco = build_reco(country, days, budget, interest, month)

        mn_lines = [
            f"✅ Товч төлөвлөгөө ({days} өдөр) — {country} улсаас ирэх танд:",
            *[f"• {x}" for x in reco["plan"]],
            "",
            f"💰 Төсөв: {reco['budget_tip']}",
            f"🌦️ Цаг агаар: {reco['weather']}",
        ]
        if reco["addon"]:
            mn_lines.append("⭐ Нэмэлт санаа:")
            mn_lines += [f"• {x}" for x in reco["addon"]]
        mn_lines.append("")
        mn_lines.append("Та 'байр', 'унаа', 'аюулгүй', 'зардал', 'газрууд' гэж тус тусад нь асууж болно.")

        en_lines = [
            f"✅ Quick plan ({days} days) for a traveler from {country}:",
            *[f"• {x}" for x in reco["plan"]],
            "",
            f"💰 Budget: {reco['budget_tip']}",
            f"🌦️ Weather: {reco['weather']}",
        ]
        if reco["addon"]:
            en_lines.append("⭐ Add-ons:")
            en_lines += [f"• {x}" for x in reco["addon"]]
        en_lines.append("")
        en_lines.append("You can ask separately: 'stay', 'transport', 'safety', 'cost', 'places'.")

        dispatcher.utter_message(text="\n".join(mn_lines) + "||" + "\n".join(en_lines))
        return []


class ActionPlaces(Action):
    def name(self) -> Text:
        return "action_places"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        country = tracker.get_slot("country") or "Unknown"
        days = int(float(tracker.get_slot("days") or 6))
        budget = float(tracker.get_slot("budget") or 900)
        interest = tracker.get_slot("interest") or "nature"
        month = int(float(tracker.get_slot("month") or 7))

        reco = build_reco(country, days, budget, interest, month)
        mn = "📍 Танд санал болгох өвөрмөц газрууд:\n" + "\n".join([f"• {p}" for p in reco["base_places"]])
        en = "📍 Less-common but great places:\n" + "\n".join([f"• {p}" for p in reco["base_places"]])
        dispatcher.utter_message(text=mn + "||" + en)
        return []


class ActionAccommodation(Action):
    def name(self) -> Text:
        return "action_accommodation"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        budget = float(tracker.get_slot("budget") or 900)
        mn = [
            "🏨 Байрлах зөвлөмж:",
            "• Улаанбаатар: төвдөө hotel/hostel (байршил чухал)",
            "• Хөдөө: ger camp (аялалын мэдрэмж), эсвэл eco lodge",
        ]
        if budget < 600:
            mn.append("• Төсөв бага: hostel + shared ger camp сонго.")
        elif budget < 1500:
            mn.append("• Дундаж: 3–4* hotel + чанартай ger camp.")
        else:
            mn.append("• Өндөр: premium hotel + private ger camp/eco lodge.")
        mn.append("⚠️ Зуны улиралд урьдчилж захиалах нь дээр.")

        en = [
            "🏨 Stay tips:",
            "• Ulaanbaatar: choose central area (location matters).",
            "• Countryside: ger camps (classic experience) or eco lodges.",
        ]
        if budget < 600:
            en.append("• Low budget: hostel + shared ger camp.")
        elif budget < 1500:
            en.append("• Mid budget: 3–4* hotel + solid ger camp.")
        else:
            en.append("• High budget: premium hotel + private ger camp/eco lodge.")
        en.append("⚠️ Summer: book early.")

        dispatcher.utter_message(text="\n".join(mn) + "||" + "\n".join(en))
        return []


class ActionWeather(Action):
    def name(self) -> Text:
        return "action_weather"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        month = int(float(tracker.get_slot("month") or 7))
        if month in (12, 1, 2):
            mn = "❄️ Өвөл маш хүйтэн (-20…-35°C). Дулаан гутал, outerwear зайлшгүй."
            en = "❄️ Winter is extremely cold (-20…-35°C). Proper winter gear is essential."
        elif month in (6, 7, 8):
            mn = "🌤️ Зун дулаан (15…30°C). Шөнө сэрүүн, бороо үе үе — rain jacket авч яваарай."
            en = "🌤️ Summer is warm (15…30°C). Nights can be cool; occasional rain—bring a jacket."
        else:
            mn = "🌬️ Хавар/Намар сэрүүхэн, салхитай. Давхар хувцас хэрэгтэй."
            en = "🌬️ Spring/Fall is cool and windy—layer up."
        dispatcher.utter_message(text=mn + "||" + en)
        return []


class ActionTransport(Action):
    def name(self) -> Text:
        return "action_transport"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        mn = [
            "🚙 Тээврийн сонголт:",
            "• УБ дотор: автобус/такси",
            "• Хөдөө: driver+4x4 (хамгийн найдвартай), эсвэл group tour",
            "• Алслагдсан аймаг: дотоод нислэг (цаг хэмнэнэ)",
            "⚠️ Замын нөхцөл: off-road их тул маршрутаа бодитоор төлөвлө."
        ]
        en = [
            "🚙 Transport options:",
            "• In UB: bus/taxi",
            "• Countryside: private driver+4x4 (most reliable) or group tour",
            "• Far provinces: domestic flights save time",
            "⚠️ Many routes are off-road—plan realistically."
        ]
        dispatcher.utter_message(text="\n".join(mn) + "||" + "\n".join(en))
        return []


class ActionSafety(Action):
    def name(self) -> Text:
        return "action_safety"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        mn = [
            "🛡️ Аюулгүй байдлын зөвлөмж:",
            "• Хотод: олон хүнтэй газар халаасны хулгайгаас сэрэмжил",
            "• Хөдөөд: ус/түлш/цэнэглэгч нөөцтэй яв",
            "• Байгаль: цаг агаар хурдан өөрчлөгдөнө — хувцсаа давхарла",
            "• Алс маршрут: лицензтэй тур/жолооч сонго"
        ]
        en = [
            "🛡️ Safety tips:",
            "• In the city: watch pickpockets in crowded areas",
            "• Countryside: carry extra water/fuel/power bank",
            "• Nature: weather changes fast—bring layers",
            "• Remote routes: use licensed tours/drivers"
        ]
        dispatcher.utter_message(text="\n".join(mn) + "||" + "\n".join(en))
        return []


class ActionCost(Action):
    def name(self) -> Text:
        return "action_cost"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        mn = [
            "💵 Зардлын баримжаа (их ойролцоо):",
            "• Хот: өдөрт ~$30–$100 (хоол+унаа+үзвэр)",
            "• Ger camp: хүн/шөнө ~$25–$80 (чанараас хамаарна)",
            "• Private driver: өдөрт ~$80–$180 (route-оос хамаарна)",
            "Зөвхөн чиглэлээ хэлбэл илүү нарийн тооцоолж өгье."
        ]
        en = [
            "💵 Rough costs (very approximate):",
            "• City: ~$30–$100/day",
            "• Ger camp: ~$25–$80/person/night",
            "• Private driver: ~$80–$180/day",
            "Tell me your route and I can estimate more precisely."
        ]
        dispatcher.utter_message(text="\n".join(mn) + "||" + "\n".join(en))
        return []


class ActionFallback(Action):
    def name(self) -> Text:
        return "action_fallback"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        dispatcher.utter_message(response="utter_fallback")
        return []
