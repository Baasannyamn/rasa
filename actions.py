from __future__ import annotations
import re
from typing import Any, Dict, Optional, Text

from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.forms import FormValidationAction
from rasa_sdk.events import AllSlotsReset


# --- Budget parsing ---
def parse_budget_to_mnt(raw: str) -> Optional[float]:
    if not raw:
        return None
    s = raw.strip().lower()

    if any(w in s for w in ["бага", "low"]):
        return 1_500_000
    if any(w in s for w in ["дунд", "medium"]):
        return 3_500_000
    if any(w in s for w in ["өндөр", "high"]):
        return 7_000_000

    usd_rate = 3500.0
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(\$|usd)", s)
    if m:
        val = float(m.group(1).replace(",", "."))
        return val * usd_rate

    m = re.search(r"(\d+(?:[.,]\d+)?)\s*сая", s)
    if m:
        val = float(m.group(1).replace(",", "."))
        return val * 1_000_000

    m = re.search(r"(\d{4,})", s)
    if m:
        return float(m.group(1))

    return None


def budget_level_from_mnt(mnt: float) -> str:
    if mnt < 2_500_000:
        return "бага"
    if mnt < 5_500_000:
        return "дунд"
    return "өндөр"


def normalize_interest(raw: str) -> str:
    s = (raw or "").lower()
    if "соёл" in s or "culture" in s:
        return "соёл"
    if "адал" in s or "adventure" in s:
        return "адал явдал"
    if "тайван" in s or "quiet" in s:
        return "тайван"
    return "байгаль"


def normalize_style(raw: str) -> Optional[str]:
    s = (raw or "").strip().lower()
    if s in ["backpack", "budget", "хэмнэлттэй"]:
        return "backpack"
    if s in ["comfort", "standard", "тухтай"]:
        return "comfort"
    if s in ["luxury", "premium", "тансаг"]:
        return "luxury"
    return None


def parse_yesno(raw: str) -> Optional[bool]:
    s = (raw or "").strip().lower()
    if s in ["тийм", "yes", "ok", "болно", "хэрэгтэй"]:
        return True
    if s in ["үгүй", "no", "not needed", "хэрэггүй", "шаардлагагүй"]:
        return False
    return None


# --- Data: recommend by interest ---
RECO = {
    "байгаль": ["Хөвсгөл (нуур)", "Баян-Өлгий (Алтай Таван Богд)", "Архангай (Тэрхийн цагаан нуур)"],
    "соёл": ["Өвөрхангай (Хархорин/Эрдэнэзуу)", "Улаанбаатар (музей/соёл)", "Хэнтий (түүхэн чиглэл)"],
    "адал явдал": ["Өмнөговь (Говь)", "Завхан", "Говь-Алтай"],
    "тайван": ["Орхон", "Дархан-Уул", "Говьсүмбэр"],
}

SEASON_TIPS_MN = {
    "1": "Өвөл хүйтэн. Дулаан хувцас + хот/ойролцоо аялал тохиромжтой.",
    "2": "Өвөл/хаврын зааг. Замын нөхцөл шалгаарай.",
    "6": "Зуны эхлэл. Байгаль, нуур, уул тохиромжтой.",
    "7": "Оргил улирал. Урьдчилан захиалга зөв.",
    "8": "Зун. Хөвсгөл/Архангай/Алтай гоё үе.",
    "9": "Намар. Зөөлөн цаг агаар, зураг авахад гоё.",
    "12": "Өвөл. Хэт хүйтрэх боломжтой.",
}
SEASON_TIPS_EN = {
    "1": "Very cold winter. Warm clothes + city/nearby trips recommended.",
    "2": "Winter–spring transition. Check road conditions.",
    "6": "Early summer. Great for lakes/mountains.",
    "7": "Peak season. Book in advance.",
    "8": "Summer. Perfect for Khuvsgul/Arkhangai/Altai.",
    "9": "Autumn. Mild weather, great for photos.",
    "12": "Winter. Can be extremely cold.",
}

HOTEL_GUIDE_HINTS_MN = {
    "бага": "Hostel/guesthouse (1 шөнө ~ 60k–120k₮) + shared tour.",
    "дунд": "3*–4* (1 шөнө ~ 180k–350k₮) + day tour.",
    "өндөр": "4*–5* (1 шөнө ~ 400k₮+) + private guide/машин.",
}
HOTEL_GUIDE_HINTS_EN = {
    "бага": "Hostel/guesthouse (~60k–120k MNT/night) + shared tour.",
    "дунд": "3–4 star (~180k–350k MNT/night) + day tour.",
    "өндөр": "4–5 star (400k+ MNT/night) + private guide/car.",
}


class ValidateTravelForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_travel_form"

    def validate_budget_amount(self, value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]):
        mnt = parse_budget_to_mnt(str(value))
        if mnt is None:
            dispatcher.utter_message(text="Төсвөө ингэж бич: 2 сая / 500$ / бага/дунд/өндөр  |  Budget: 2 million MNT / 500$ / low-medium-high")
            return {"budget_amount": None}
        level = budget_level_from_mnt(mnt)
        return {"budget_amount": str(value), "budget_level": level}

    def validate_country(self, value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]):
        v = str(value).strip()
        if len(v) < 2:
            dispatcher.utter_message(text="Улсаа бичнэ үү. / Please type your country.")
            return {"country": None}
        return {"country": v}

    def validate_interest(self, value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]):
        v = normalize_interest(str(value))
        return {"interest": v}

    def validate_duration_days(self, value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]):
        s = str(value)
        m = re.search(r"(\d+)", s)
        days = float(m.group(1)) if m else None
        if days is None or days <= 0 or days > 60:
            dispatcher.utter_message(text="Хугацаа 1–60 өдөр. / Duration must be 1–60 days.")
            return {"duration_days": None}
        return {"duration_days": days}

    def validate_travel_month(self, value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]):
        s = str(value).lower().strip()
        m = re.search(r"(\d{1,2})", s)
        if not m:
            dispatcher.utter_message(text="Сараа 1–12 тоогоор бич. / Type month number 1–12.")
            return {"travel_month": None}
        month = int(m.group(1))
        if month < 1 or month > 12:
            dispatcher.utter_message(text="Сар 1–12 хооронд. / Month must be 1–12.")
            return {"travel_month": None}
        return {"travel_month": str(month)}

    def validate_destination(self, value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]):
        v = str(value).strip()
        if len(v) < 2:
            dispatcher.utter_message(text="Очих газар/аймгаа бич. / Type a destination (aimag/city) or 'мэдэхгүй'.")
            return {"destination": None}
        return {"destination": v}

    def validate_group_size(self, value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]):
        s = str(value)
        m = re.search(r"(\d+)", s)
        n = float(m.group(1)) if m else None
        if n is None or n <= 0 or n > 50:
            dispatcher.utter_message(text="Хүмүүсийн тоо 1–50. / Group size must be 1–50.")
            return {"group_size": None}
        return {"group_size": n}

    def validate_travel_style(self, value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]):
        norm = normalize_style(str(value))
        if not norm:
            dispatcher.utter_message(text="Style: backpack / comfort / luxury гэж бич. / Type: backpack/comfort/luxury")
            return {"travel_style": None}
        return {"travel_style": norm}

    def validate_need_guide(self, value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]):
        yn = parse_yesno(str(value))
        if yn is None:
            dispatcher.utter_message(text="Guide: тийм/үгүй (yes/no).")
            return {"need_guide": None}
        return {"need_guide": yn}

    def validate_need_hotel(self, value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]):
        yn = parse_yesno(str(value))
        if yn is None:
            dispatcher.utter_message(text="Hotel: тийм/үгүй (yes/no).")
            return {"need_hotel": None}
        return {"need_hotel": yn}


class ActionRecommendTrip(Action):
    def name(self) -> Text:
        return "action_recommend_trip"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]):
        lang = tracker.get_slot("language") or "mn"

        budget_level = tracker.get_slot("budget_level") or "дунд"
        country = (tracker.get_slot("country") or "").strip()
        interest = tracker.get_slot("interest") or "байгаль"
        days = float(tracker.get_slot("duration_days") or 5)
        month = str(tracker.get_slot("travel_month") or "6")
        destination = (tracker.get_slot("destination") or "мэдэхгүй").strip()
        group_size = int(float(tracker.get_slot("group_size") or 1))
        style = tracker.get_slot("travel_style") or "comfort"
        need_guide = bool(tracker.get_slot("need_guide"))
        need_hotel = bool(tracker.get_slot("need_hotel"))

        picks = RECO.get(interest, RECO["байгаль"])

        # Day budget baseline by budget_level + style
        base_per_day = {"бага": 180_000, "дунд": 350_000, "өндөр": 700_000}.get(budget_level, 350_000)
        style_mult = {"backpack": 0.85, "comfort": 1.0, "luxury": 1.45}.get(style, 1.0)
        per_day = int(base_per_day * style_mult)
        est_total = int(per_day * days * max(group_size, 1))

        if lang == "en":
            season_tip = SEASON_TIPS_EN.get(month, "Season tip can be refined later.")
            hint = HOTEL_GUIDE_HINTS_EN.get(budget_level, HOTEL_GUIDE_HINTS_EN["дунд"])
            msg = (
                f"🧭 Your inputs:\n"
                f"• Country: {country or '—'}\n"
                f"• Interest: {interest}\n"
                f"• Days: {int(days)}\n"
                f"• Month: {month}\n"
                f"• Destination: {destination}\n"
                f"• Group: {group_size}\n"
                f"• Style: {style}\n"
                f"• Guide: {'Yes' if need_guide else 'No'}\n"
                f"• Hotel: {'Yes' if need_hotel else 'No'}\n\n"
                f"✅ Suggested places (21 aimags coverage via templates):\n"
                f"1) {picks[0]}\n"
                f"2) {picks[1]}\n"
                f"3) {picks[2]}\n\n"
                f"🌦️ Season tip: {season_tip}\n\n"
                f"💰 Rough estimate (~{per_day:,} MNT/day/person): ~{est_total:,} MNT total\n"
                f"🏨/🧑‍💼 {hint}\n\n"
                f"Next upgrade: I can generate a day-by-day itinerary if you want."
            )
        else:
            season_tip = SEASON_TIPS_MN.get(month, "Улирлын зөвлөгөөг дараа нь нарийвчилж болно.")
            hint = HOTEL_GUIDE_HINTS_MN.get(budget_level, HOTEL_GUIDE_HINTS_MN["дунд"])
            msg = (
                f"🧭 Таны мэдээлэл:\n"
                f"• Улс: {country or '—'}\n"
                f"• Сонирхол: {interest}\n"
                f"• Хугацаа: {int(days)} өдөр\n"
                f"• Ирэх сар: {month}\n"
                f"• Очих газар: {destination}\n"
                f"• Хүмүүс: {group_size} хүн\n"
                f"• Style: {style}\n"
                f"• Guide: {'Тийм' if need_guide else 'Үгүй'}\n"
                f"• Байр: {'Тийм' if need_hotel else 'Үгүй'}\n\n"
                f"✅ Санал болгох чиглэлүүд (21 аймгийн хүрээнд templates):\n"
                f"1) {picks[0]}\n"
                f"2) {picks[1]}\n"
                f"3) {picks[2]}\n\n"
                f"🌦️ Улирлын зөвлөгөө: {season_tip}\n\n"
                f"💰 Ойролцоогоор (өдөрт ~{per_day:,}₮/хүн): нийт ~{est_total:,}₮\n"
                f"🏨/🧑‍💼 {hint}\n\n"
                f"Дараагийн шат: хүсвэл өдөр-өдрөөр маршрут гаргаж өгнө."
            )

        dispatcher.utter_message(text=msg)
        return []


class ActionResetChat(Action):
    def name(self) -> Text:
        return "action_reset_chat"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]):
        lang = tracker.get_slot("language") or "mn"
        dispatcher.utter_message(text="Шинэ чат эхэллээ ✅" if lang != "en" else "New chat started ✅")
        return [AllSlotsReset()]
