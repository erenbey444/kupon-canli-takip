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

COUPON = [
    {"home": "Mallorca B", "away": "Deportiva Minera", "bet": "HT_DRAW"},
    {"home": "Tenerife B", "away": "Atletico Central", "bet": "HT_DRAW"},
    {"home": "Puertollano C.F.", "away": "Atl. Paso", "bet": "HOME_WIN"},
    {"home": "Eintracht Frankfurt U19", "away": "RB Leipzig U19", "bet": "HOME_WIN"},
    {"home": "Sassuolo Women", "away": "AS Roma Women", "bet": "AWAY_WIN"},
]

previous_scores = {}
monitor_started = False
monitor_lock = threading.Lock()


def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram ayarlari eksik.")
        return

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=10
        )
        response.raise_for_status()
    except Exception as e:
        print("Telegram hata:", e)


def get_live_matches():
    if not BSD_TOKEN:
        print("BSD_API_TOKEN eksik.")
        return []

    try:
        response = requests.get(
            BSD_LIVE_URL,
            headers={"Authorization": f"Token {BSD_TOKEN}"},
            params={"limit": 200},
            timeout=15
        )

        response.raise_for_status()
        data = response.json()

        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            return data.get("results", data.get("events", []))

        return []

    except Exception as e:
        print("BSD API hata:", e)
        return []


def normalize(value):
    return str(value or "").lower().strip()


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
        except (ValueError, TypeError):
            pass

    return 0


def find_coupon_match(live_match):
    home = team_name(
        live_match.get("home_team") or live_match.get("home")
    )
    away = team_name(
        live_match.get("away_team") or live_match.get("away")
    )

    for coupon_match in COUPON:
        ch = normalize(coupon_match["home"])
        ca = normalize(coupon_match["away"])
        lh = normalize(home)
        la = normalize(away)

        home_ok = ch in lh or lh in ch
        away_ok = ca in la or la in ca

        if home_ok and away_ok:
            return coupon_match, home, away

    return None, home, away


def goal_message(coupon_match, home, away, hs, as_):
    bet = coupon_match["bet"]

    if bet == "HT_DRAW":
        if hs == as_:
            return (
                f"🥅⚽⚽💚💚 GOOOL BE!\n"
                f"{home} {hs}-{as_} {away}\n"
                f"İlk yarı beraberlik yeniden geliyor 🙏🏻"
            )

        scoring_team = home if hs > as_ else away

        return (
            f"🥺❌ {scoring_team} gol attı!\n"
            f"{home} {hs}-{as_} {away}\n"
            f"İlk yarı beraberlik gelmesi için eşitlik lazım 🙏🏻"
        )

    if bet == "HOME_WIN":
        if hs > as_:
            return (
                f"🥅⚽💚 GOOOL BE!\n"
                f"{home} {hs}-{as_} {away}\n"
                f"{home} galibiyeti şu an geliyor 🙏🏻🔥"
            )

        if hs < as_:
            return (
                f"🥺❌ {away} gol attı!\n"
                f"{home} {hs}-{as_} {away}\n"
                f"{home} için dönüş lazım 🙏🏻"
            )

        return (
            f"⚽💚 {home} {hs}-{as_} {away}\n"
            f"Beraberlik oldu. {home} için 1 gol lazım 🙏🏻"
        )

    if bet == "AWAY_WIN":
        if as_ > hs:
            return (
                f"🥅⚽💚 GOOOL BE!\n"
                f"{home} {hs}-{as_} {away}\n"
                f"{away} galibiyeti şu an geliyor 🙏🏻🔥"
            )

        if as_ < hs:
            return (
                f"🥺❌ {home} gol attı!\n"
                f"{home} {hs}-{as_} {away}\n"
                f"{away} için dönüş lazım 🙏🏻"
            )

        return (
            f"⚽💚 {home} {hs}-{as_} {away}\n"
            f"Beraberlik oldu. {away} için 1 gol lazım 🙏🏻"
        )

    return f"⚽ Gol! {home} {hs}-{as_} {away}"


def monitor():
    print("CANLI TAKIP THREAD BASLADI")

    while True:
        matches = get_live_matches()

        print(f"BSD canlı maç sayısı: {len(matches)}")

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
                print(f"Takibe alındı: {home} {hs}-{as_} {away}")
                continue

            old = previous_scores[key]

            if current != old:
                if hs + as_ > old[0] + old[1]:
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


def start_monitor():
    global monitor_started

    with monitor_lock:
        if monitor_started:
            return

        monitor_started = True

        thread = threading.Thread(
            target=monitor,
            daemon=True,
            name="live-match-monitor"
        )
        thread.start()

        print("Canli mac takip sistemi aktif.")


# Gunicorn app.py dosyasını import ettiğinde de çalışır.
start_monitor()


@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "service": "Kuponumu Takip Et",
        "matches": len(COUPON),
        "monitor": "active" if monitor_started else "inactive"
    })


@app.route("/test")
def test():
    telegram(
        "⚽💚 TEST BAŞARILI!\n"
        "Kupon bildirim sistemi ve canlı takip motoru çalışıyor 🙏🏻🔥"
    )

    return jsonify({
        "telegram": "test sent",
        "monitor": monitor_started
    })


@app.route("/live-check")
def live_check():
    matches = get_live_matches()

    found = []

    for match in matches:
        coupon_match, home, away = find_coupon_match(match)

        if coupon_match:
            found.append({
                "home": home,
                "away": away,
                "score": f"{score_value(match, 'home')}-{score_value(match, 'away')}",
                "bet": coupon_match["bet"]
            })

    return jsonify({
        "bsd_live_matches": len(matches),
        "coupon_matches_found": len(found),
        "found": found
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
