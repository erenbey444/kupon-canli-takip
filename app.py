import os
import time
import threading
import requests
from flask import Flask, jsonify

app = Flask(__name__)

BSD_TOKEN = os.environ.get("BSD_API_TOKEN")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

BSD_LIVE_URL = "https://sports.bzzoiro.com/api/v2/events/live/"

# Daha sonra kupondan otomatik oluşturacağız.
COUPON = [
    {
        "home": "Mallorca B",
        "away": "Deportiva Minera",
        "bet": "HT_DRAW"
    },
    {
        "home": "Tenerife B",
        "away": "Atletico Central",
        "bet": "HT_DRAW"
    },
    {
        "home": "Puertollano C.F.",
        "away": "Atl. Paso",
        "bet": "HOME_WIN"
    },
    {
        "home": "Eintracht Frankfurt U19",
        "away": "RB Leipzig U19",
        "bet": "HOME_WIN"
    },
    {
        "home": "Sassuolo Women",
        "away": "AS Roma Women",
        "bet": "AWAY_WIN"
    }
]

previous_scores = {}


def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram ayarlari eksik.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=10
        )
    except Exception as e:
        print("Telegram hata:", e)


def get_live_matches():
    if not BSD_TOKEN:
        print("BSD_API_TOKEN eksik.")
        return []

    headers = {
        "Authorization": f"Token {BSD_TOKEN}"
    }

    try:
        response = requests.get(
            BSD_LIVE_URL,
            headers=headers,
            timeout=15
        )

        response.raise_for_status()
        data = response.json()

        if isinstance(data, list):
            return data

        return data.get("results", data.get("events", []))

    except Exception as e:
        print("BSD API hata:", e)
        return []


def text(value):
    if value is None:
        return ""
    return str(value).lower().strip()


def team_name(team):
    if isinstance(team, dict):
        return (
            team.get("name")
            or team.get("short_name")
            or team.get("title")
            or ""
        )

    return str(team or "")


def score_value(match, side):
    candidates = []

    if side == "home":
        candidates = [
            match.get("home_score"),
            match.get("score_home"),
            match.get("homeScore")
        ]
    else:
        candidates = [
            match.get("away_score"),
            match.get("score_away"),
            match.get("awayScore")
        ]

    score = match.get("score")

    if isinstance(score, dict):
        candidates.append(score.get(side))

    for value in candidates:
        try:
            if value is not None:
                return int(value)
        except:
            pass

    return 0


def find_coupon_match(live_match):
    home = team_name(
        live_match.get("home_team")
        or live_match.get("home")
    )

    away = team_name(
        live_match.get("away_team")
        or live_match.get("away")
    )

    for coupon_match in COUPON:
        if (
            text(coupon_match["home"]) in text(home)
            or text(home) in text(coupon_match["home"])
        ) and (
            text(coupon_match["away"]) in text(away)
            or text(away) in text(coupon_match["away"])
        ):
            return coupon_match, home, away

    return None, home, away


def goal_message(coupon_match, home, away, hs, as_):
    bet = coupon_match["bet"]
    total = hs + as_

    if bet == "HT_DRAW":
        if hs == as_:
            return (
                f"⚽💚 GOOOL! {home} {hs}-{as_} {away}\n"
                f"İlk yarı beraberlik yeniden geliyor 🙏🏻"
            )

        scoring_team = home if hs > as_ else away

        return (
            f"🥺⚽ {scoring_team} gol attı! "
            f"{home} {hs}-{as_} {away}\n"
            f"İlk yarı beraberlik için eşitlik golü lazım 🙏🏻"
        )

    if bet == "HOME_WIN":
        if hs > as_:
            return (
                f"🥅⚽💚 GOOOL BE! "
                f"{home} {hs}-{as_} önde!\n"
                f"{home} galibiyeti şu an geliyor 🙏🏻🔥"
            )

        if hs < as_:
            return (
                f"🥺❌ {away} öne geçti: "
                f"{home} {hs}-{as_} {away}\n"
                f"{home} dönüşü lazım 🙏🏻"
            )

        return (
            f"⚽ {home} {hs}-{as_} {away}\n"
            f"Beraberlik oldu, {home} için 1 gol lazım 🙏🏻"
        )

    if bet == "AWAY_WIN":
        if as_ > hs:
            return (
                f"🥅⚽💚 GOOOL BE! "
                f"{away} {as_}-{hs} önde!\n"
                f"{away} galibiyeti şu an geliyor 🙏🏻🔥"
            )

        if as_ < hs:
            return (
                f"🥺❌ {home} öne geçti: "
                f"{home} {hs}-{as_} {away}\n"
                f"{away} dönüşü lazım 🙏🏻"
            )

        return (
            f"⚽ {home} {hs}-{as_} {away}\n"
            f"Beraberlik oldu, {away} için 1 gol lazım 🙏🏻"
        )

    if bet == "OVER_25":
        remaining = max(0, 3 - total)

        if remaining == 0:
            return "💚💚💚 GOOOOOL! ✅ 2.5 ÜST GELDİ! 🔥"

        return (
            f"🥅⚽💚 GOOOL BE!\n"
            f"2.5 Üst için {remaining} gol daha lazım 🙏🏻"
        )

    if bet == "BTTS":
        if hs > 0 and as_ > 0:
            return "🔥⚽⚽ KG VAR GELDİ! ✅💚"

        waiting = away if hs > 0 else home

        return (
            f"⚽💚 İlk gol geldi!\n"
            f"Şimdi {waiting} takımından gol bekliyoruz 🙏🏻"
        )

    return f"⚽ Gol! {home} {hs}-{as_} {away}"


def monitor():
    telegram("🟢 Kuponumu Takip Et aktif! Canlı maçları bekliyorum ⚽")

    while True:
        matches = get_live_matches()

        for match in matches:
            coupon_match, home, away = find_coupon_match(match)

            if not coupon_match:
                continue

            hs = score_value(match, "home")
            as_ = score_value(match, "away")

            key = f"{coupon_match['home']}|{coupon_match['away']}"
            current = (hs, as_)

            if key not in previous_scores:
                previous_scores[key] = current
                continue

            old = previous_scores[key]

            if current != old:
                if (hs + as_) > (old[0] + old[1]):
                    telegram(
                        goal_message(
                            coupon_match,
                            home,
                            away,
                            hs,
                            as_
                        )
                    )

                previous_scores[key] = current

        time.sleep(10)


@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "service": "Kuponumu Takip Et",
        "matches": len(COUPON)
    })


@app.route("/test")
def test():
    telegram("⚽💚 TEST BAŞARILI! Kupon bildirim sistemi çalışıyor 🙏🏻🔥")

    return jsonify({
        "telegram": "test sent"
    })


if __name__ == "__main__":
    threading.Thread(
        target=monitor,
        daemon=True
    ).start()

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )
