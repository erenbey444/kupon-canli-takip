import os
import time
import threading
import requests
from datetime import datetime, timezone
from flask import Flask, jsonify

app = Flask(__name__)

BSD_TOKEN = os.environ.get("BSD_API_TOKEN")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

BSD_LIVE_URL = "https://sports.bzzoiro.com/api/v2/events/live/"

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

monitor_started = False
monitor_lock = threading.Lock()

cache_lock = threading.Lock()

live_cache = {
    "updated_at": None,
    "bsd_live_matches": 0,
    "coupon_matches_found": 0,
    "found": [],
    "error": None
}


# BSD bağlantısını sadece arka plan takip motoru kullanacak.
bsd_session = requests.Session()

# requests'in .netrc / sistem kimlik bilgisi kontrolünü kapatır.
bsd_session.trust_env = False


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
            timeout=(5, 10)
        )

        response.raise_for_status()

    except Exception as e:
        print("Telegram hata:", repr(e))


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
        live_match.get("home_team")
        or live_match.get("home")
    )

    away = team_name(
        live_match.get("away_team")
        or live_match.get("away")
    )

    for coupon_match in COUPON:
        coupon_home = normalize(coupon_match["home"])
        coupon_away = normalize(coupon_match["away"])

        live_home = normalize(home)
        live_away = normalize(away)

        if not live_home or not live_away:
            continue

        home_ok = (
            coupon_home in live_home
            or live_home in coupon_home
        )

        away_ok = (
            coupon_away in live_away
            or live_away in coupon_away
        )

        if home_ok and away_ok:
            return coupon_match, home, away

    return None, home, away


def get_live_matches():
    if not BSD_TOKEN:
        raise RuntimeError("BSD_API_TOKEN eksik.")

    response = bsd_session.get(
        BSD_LIVE_URL,
        headers={
            "Authorization": f"Token {BSD_TOKEN}",
            "Accept": "application/json"
        },
        params={
            "limit": 200
        },
        timeout=(5, 10)
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        results = data.get("results")

        if isinstance(results, list):
            return results

        events = data.get("events")

        if isinstance(events, list):
            return events

    return []


def goal_message(
    coupon_match,
    home,
    away,
    home_score,
    away_score
):
    bet = coupon_match["bet"]

    if bet == "HT_DRAW":

        if home_score == away_score:
            return (
                f"🥅⚽⚽💚💚 GOOOL BE!\n"
                f"{home} {home_score}-{away_score} {away}\n"
                f"İlk yarı beraberlik yeniden geliyor 🙏🏻"
            )

        scoring_team = (
            home
            if home_score > away_score
            else away
        )

        return (
            f"🥺❌ {scoring_team} gol attı!\n"
            f"{home} {home_score}-{away_score} {away}\n"
            f"İlk yarı beraberlik için eşitlik golü lazım 🙏🏻"
        )

    if bet == "HOME_WIN":

        if home_score > away_score:
            return (
                f"🥅⚽💚 GOOOL BE!\n"
                f"{home} {home_score}-{away_score} {away}\n"
                f"{home} galibiyeti şu an geliyor 🙏🏻🔥"
            )

        if home_score < away_score:
            return (
                f"🥺❌ {away} gol attı!\n"
                f"{home} {home_score}-{away_score} {away}\n"
                f"{home} için dönüş lazım 🙏🏻"
            )

        return (
            f"⚽💚 {home} {home_score}-{away_score} {away}\n"
            f"Beraberlik oldu. {home} için 1 gol lazım 🙏🏻"
        )

    if bet == "AWAY_WIN":

        if away_score > home_score:
            return (
                f"🥅⚽💚 GOOOL BE!\n"
                f"{home} {home_score}-{away_score} {away}\n"
                f"{away} galibiyeti şu an geliyor 🙏🏻🔥"
            )

        if away_score < home_score:
            return (
                f"🥺❌ {home} gol attı!\n"
                f"{home} {home_score}-{away_score} {away}\n"
                f"{away} için dönüş lazım 🙏🏻"
            )

        return (
            f"⚽💚 {home} {home_score}-{away_score} {away}\n"
            f"Beraberlik oldu. {away} için 1 gol lazım 🙏🏻"
        )

    return (
        f"⚽ Gol!\n"
        f"{home} {home_score}-{away_score} {away}"
    )


def update_cache(matches):
    found = []

    for match in matches:
        coupon_match, home, away = find_coupon_match(match)

        if not coupon_match:
            continue

        home_score = score_value(match, "home")
        away_score = score_value(match, "away")

        found.append({
            "home": home,
            "away": away,
            "score": f"{home_score}-{away_score}",
            "bet": coupon_match["bet"]
        })

    with cache_lock:
        live_cache["updated_at"] = (
            datetime.now(timezone.utc).isoformat()
        )

        live_cache["bsd_live_matches"] = len(matches)
        live_cache["coupon_matches_found"] = len(found)
        live_cache["found"] = found
        live_cache["error"] = None


def update_cache_error(error):
    with cache_lock:
        live_cache["updated_at"] = (
            datetime.now(timezone.utc).isoformat()
        )

        live_cache["error"] = str(error)


def process_matches(matches):
    for match in matches:
        coupon_match, home, away = find_coupon_match(match)

        if not coupon_match:
            continue

        home_score = score_value(match, "home")
        away_score = score_value(match, "away")

        key = (
            f"{coupon_match['home']}|"
            f"{coupon_match['away']}"
        )

        current = (
            home_score,
            away_score
        )

        if key not in previous_scores:
            previous_scores[key] = current

            print(
                "Takibe alindi:",
                home,
                current,
                away
            )

            continue

        old = previous_scores[key]

        if current == old:
            continue

        old_total = old[0] + old[1]
        new_total = current[0] + current[1]

        if new_total > old_total:
            telegram(
                goal_message(
                    coupon_match,
                    home,
                    away,
                    home_score,
                    away_score
                )
            )

        previous_scores[key] = current


def monitor():
    print("CANLI TAKIP THREAD BASLADI")

    while True:
        try:
            matches = get_live_matches()

            print(
                f"BSD canlı maç sayısı: {len(matches)}"
            )

            update_cache(matches)

            process_matches(matches)

            time.sleep(10)

        except Exception as e:
            print(
                "BSD API hata:",
                repr(e)
            )

            update_cache_error(e)

            time.sleep(15)


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

        print(
            "Canli mac takip sistemi aktif."
        )


# Gunicorn app.py'yi import ettiğinde
# canlı takip motoru otomatik başlar.
start_monitor()


@app.route("/")
def home():
    with cache_lock:
        cache = dict(live_cache)

    return jsonify({
        "status": "online",
        "service": "Kuponumu Takip Et",
        "coupon_matches": len(COUPON),
        "monitor": (
            "active"
            if monitor_started
            else "inactive"
        ),
        "last_bsd_update": cache["updated_at"],
        "last_bsd_error": cache["error"]
    })


@app.route("/test")
def test():
    telegram(
        "⚽💚 TEST BAŞARILI!\n"
        "Kupon bildirim sistemi çalışıyor 🙏🏻🔥"
    )

    return jsonify({
        "telegram": "test sent",
        "monitor": monitor_started
    })


@app.route("/live-check")
def live_check():
    # BURADA BSD'YE YENİ İSTEK YOK.
    # Sadece arka plan takip motorunun
    # aldığı son veri gösterilir.

    with cache_lock:
        cache = {
            "updated_at": live_cache["updated_at"],
            "bsd_live_matches": live_cache[
                "bsd_live_matches"
            ],
            "coupon_matches_found": live_cache[
                "coupon_matches_found"
            ],
            "found": list(
                live_cache["found"]
            ),
            "error": live_cache["error"]
        }

    return jsonify({
        "monitor": (
            "active"
            if monitor_started
            else "inactive"
        ),
        **cache
    })


if __name__ == "__main__":
    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
