import os
import time
import json
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone
from flask import Flask, jsonify

app = Flask(__name__)

BSD_TOKEN = os.environ.get("BSD_API_TOKEN")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

BSD_LIVE_URL = "https://sports.bzzoiro.com/api/v2/events/live/"
POLL_SECONDS = 10

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
cache_lock = threading.Lock()

live_cache = {
    "updated_at": None,
    "bsd_live_matches": 0,
    "coupon_matches_found": 0,
    "found": [],
    "error": None,
    "last_http_status": None,
    "last_attempt_at": None,
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram ayarlari eksik.", flush=True)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    body = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": message}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "kupon-canli-takip/2.0"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            ok = 200 <= response.status < 300
            print(f"TELEGRAM HTTP {response.status}", flush=True)
            return ok
    except Exception as e:
        print("Telegram hata:", type(e).__name__, str(e), flush=True)
        return False


def normalize(value):
    return str(value or "").lower().strip()


def team_name(team):
    if isinstance(team, dict):
        return team.get("name") or team.get("short_name") or team.get("title") or ""
    return str(team or "")


def score_value(match, side):
    if side == "home":
        candidates = [match.get("home_score"), match.get("score_home"), match.get("homeScore")]
    else:
        candidates = [match.get("away_score"), match.get("score_away"), match.get("awayScore")]

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
    home = team_name(live_match.get("home_team") or live_match.get("home"))
    away = team_name(live_match.get("away_team") or live_match.get("away"))

    for coupon_match in COUPON:
        coupon_home = normalize(coupon_match["home"])
        coupon_away = normalize(coupon_match["away"])
        live_home = normalize(home)
        live_away = normalize(away)

        if not live_home or not live_away:
            continue

        home_ok = coupon_home in live_home or live_home in coupon_home
        away_ok = coupon_away in live_away or live_away in coupon_away

        if home_ok and away_ok:
            return coupon_match, home, away

    return None, home, away


def decode_matches(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("results", "events", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def get_live_matches():
    if not BSD_TOKEN:
        raise RuntimeError("BSD_API_TOKEN eksik.")

    print("BSD ISTEGI BASLIYOR", flush=True)
    req = urllib.request.Request(
        BSD_LIVE_URL,
        headers={
            "Authorization": f"Token {BSD_TOKEN}",
            "Accept": "application/json",
            "User-Agent": "kupon-canli-takip/2.0",
        },
        method="GET",
    )

    with urllib.request.urlopen(req, timeout=8) as response:
        status = response.status
        raw = response.read().decode("utf-8")

    print(f"BSD HTTP {status}", flush=True)
    data = json.loads(raw)
    return decode_matches(data), status


def goal_message(coupon_match, home, away, home_score, away_score):
    bet = coupon_match["bet"]

    if bet == "HT_DRAW":
        if home_score == away_score:
            return f"🥅⚽⚽💚💚 GOOOL BE!\n{home} {home_score}-{away_score} {away}\nİlk yarı beraberlik yeniden geliyor 🙏🏻"
        scoring_team = home if home_score > away_score else away
        return f"🥺❌ {scoring_team} gol attı!\n{home} {home_score}-{away_score} {away}\nİlk yarı beraberlik için eşitlik golü lazım 🙏🏻"

    if bet == "HOME_WIN":
        if home_score > away_score:
            return f"🥅⚽💚 GOOOL BE!\n{home} {home_score}-{away_score} {away}\n{home} galibiyeti şu an geliyor 🙏🏻🔥"
        if home_score < away_score:
            return f"🥺❌ {away} gol attı!\n{home} {home_score}-{away_score} {away}\n{home} için dönüş lazım 🙏🏻"
        return f"⚽💚 {home} {home_score}-{away_score} {away}\nBeraberlik oldu. {home} için 1 gol lazım 🙏🏻"

    if bet == "AWAY_WIN":
        if away_score > home_score:
            return f"🥅⚽💚 GOOOL BE!\n{home} {home_score}-{away_score} {away}\n{away} galibiyeti şu an geliyor 🙏🏻🔥"
        if away_score < home_score:
            return f"🥺❌ {home} gol attı!\n{home} {home_score}-{away_score} {away}\n{away} için dönüş lazım 🙏🏻"
        return f"⚽💚 {home} {home_score}-{away_score} {away}\nBeraberlik oldu. {away} için 1 gol lazım 🙏🏻"

    return f"⚽ Gol!\n{home} {home_score}-{away_score} {away}"


def update_cache(matches, http_status=None, error=None):
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
            "bet": coupon_match["bet"],
        })

    with cache_lock:
        live_cache["updated_at"] = now_iso()
        live_cache["bsd_live_matches"] = len(matches)
        live_cache["coupon_matches_found"] = len(found)
        live_cache["found"] = found
        live_cache["error"] = error
        live_cache["last_http_status"] = http_status


def process_matches(matches):
    for match in matches:
        coupon_match, home, away = find_coupon_match(match)
        if not coupon_match:
            continue

        home_score = score_value(match, "home")
        away_score = score_value(match, "away")
        key = f"{coupon_match['home']}|{coupon_match['away']}"
        current = (home_score, away_score)

        if key not in previous_scores:
            previous_scores[key] = current
            print("Takibe alindi:", home, current, away, flush=True)
            continue

        old = previous_scores[key]
        if current == old:
            continue

        if sum(current) > sum(old):
            telegram(goal_message(coupon_match, home, away, home_score, away_score))

        previous_scores[key] = current


def monitor():
    print("CANLI TAKIP THREAD BASLADI", flush=True)

    while True:
        with cache_lock:
            live_cache["last_attempt_at"] = now_iso()

        try:
            matches, status = get_live_matches()
            print(f"BSD CANLI MAC SAYISI {len(matches)}", flush=True)
            update_cache(matches, http_status=status, error=None)
            process_matches(matches)
            time.sleep(POLL_SECONDS)

        except urllib.error.HTTPError as e:
            msg = f"HTTPError {e.code}: {e.reason}"
            print("BSD API HATA:", msg, flush=True)
            update_cache([], http_status=e.code, error=msg)
            time.sleep(15)
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            print("BSD API HATA:", msg, flush=True)
            update_cache([], error=msg)
            time.sleep(15)


def start_monitor():
    global monitor_started
    with monitor_lock:
        if monitor_started:
            return
        monitor_started = True
        thread = threading.Thread(target=monitor, daemon=True, name="live-match-monitor")
        thread.start()
        print("CANLI MAC TAKIP SISTEMI AKTIF", flush=True)


start_monitor()


@app.route("/")
def home():
    with cache_lock:
        cache = dict(live_cache)
    return jsonify({
        "status": "online",
        "service": "Kuponumu Takip Et",
        "coupon_matches": len(COUPON),
        "monitor": "active" if monitor_started else "inactive",
        "last_bsd_update": cache["updated_at"],
        "last_bsd_attempt": cache["last_attempt_at"],
        "last_bsd_http": cache["last_http_status"],
        "last_bsd_error": cache["error"],
    })


@app.route("/test")
def test():
    ok = telegram("⚽💚 TEST BAŞARILI!\nKupon bildirim sistemi çalışıyor 🙏🏻🔥")
    return jsonify({"telegram": "sent" if ok else "failed", "monitor": monitor_started})


@app.route("/live-check")
def live_check():
    with cache_lock:
        cache = dict(live_cache)
    return jsonify({"monitor": "active" if monitor_started else "inactive", **cache})


@app.route("/bsd-test")
def bsd_test():
    started = time.monotonic()
    try:
        matches, status = get_live_matches()
        return jsonify({
            "ok": True,
            "http_status": status,
            "live_matches": len(matches),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        })
    except urllib.error.HTTPError as e:
        return jsonify({
            "ok": False,
            "http_status": e.code,
            "error": f"HTTPError: {e.reason}",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }), 502
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }), 502


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
