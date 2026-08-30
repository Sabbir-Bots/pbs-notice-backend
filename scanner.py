from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
import time

from bs4 import BeautifulSoup

import firebase_admin
from firebase_admin import credentials, db, messaging

import requests
import urllib3


# =========================================================
# CONFIGURATION
# =========================================================

FIREBASE_DATABASE_URL = (
    "https://love-lucky-62b3c-default-rtdb.firebaseio.com"
)

FIREBASE_CREDENTIALS_FILE = "firebase_credentials.json"

RECENT_NOTICE_HOURS = 72
MAX_NOTICES_PER_SOURCE = 10
REQUEST_TIMEOUT = 30
REQUEST_DELAY_SECONDS = 1


# =========================================================
# SSL WARNING
# =========================================================

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)


# =========================================================
# TIME HELPERS
# =========================================================

def utc_now():
    return datetime.now(timezone.utc)


BD_TIMEZONE = ZoneInfo("Asia/Dhaka")


def local_now_string():
    # Always store Bangladesh local time explicitly.
    return utc_now().astimezone(
        BD_TIMEZONE
    ).isoformat(
        timespec="seconds"
    )


def unix_now():
    return int(time.time())


# =========================================================
# FIREBASE INITIALIZATION
# =========================================================

try:
    cred = credentials.Certificate(
        FIREBASE_CREDENTIALS_FILE
    )

    firebase_admin.initialize_app(
        cred,
        {
            "databaseURL": FIREBASE_DATABASE_URL
        },
    )

    print("✅ Firebase initialized successfully.")

except ValueError:
    print("ℹ️ Firebase already initialized.")

except Exception as e:
    print(
        f"❌ Firebase initialization failed: {e}"
    )
    raise


# =========================================================
# LOAD SOURCES.JSON
# =========================================================

try:
    with open(
        "sources.json",
        "r",
        encoding="utf-8"
    ) as f:

        MASTER_SOURCES = json.load(f)

    print(
        f"✅ sources.json loaded: "
        f"{len(MASTER_SOURCES)} entries."
    )

except Exception as e:

    print(
        f"❌ sources.json ফাইল পড়তে সমস্যা হয়েছে: {e}"
    )

    MASTER_SOURCES = []


# =========================================================
# SOURCE VALIDATION
# =========================================================

def validate_sources():

    if not MASTER_SOURCES:

        print(
            "❌ sources.json খালি অথবা পড়া যায়নি।"
        )

        return False

    ids = []

    bad_entries = []

    for source in MASTER_SOURCES:

        source_id = str(
            source.get("id", "")
        ).strip()

        url = str(
            source.get("url", "")
        ).strip()

        if source_id:
            ids.append(source_id)

        if not source_id or not url:
            bad_entries.append(
                source_id or "<missing id>"
            )

    if len(ids) != len(set(ids)):

        print(
            "❌ sources.json-এ duplicate id পাওয়া গেছে।"
        )

        return False

    if bad_entries:

        print(
            "❌ নিচের entry-গুলোর ID অথবা URL missing:"
        )

        print(
            ", ".join(bad_entries)
        )

        return False

    print(
        f"✅ Master source validation OK: "
        f"{len(MASTER_SOURCES)} টি entry."
    )

    return True


# =========================================================
# FIREBASE: SCANNER RUN STATUS
# =========================================================

def start_scanner_run():

    started_unix = unix_now()
    started_readable = local_now_string()

    try:

        db.reference("last_updated").set(
            {
                "timestamp": started_readable,
                "unix": started_unix,
                "status": "running",
            }
        )

        db.reference(
            "scanner_status"
        ).update(
            {
                "status": "running",
                "started_at": started_readable,
                "started_at_unix": started_unix,
            }
        )

    except Exception as e:

        print(
            f"⚠️ last_updated/scanner_status update failed: {e}"
        )

    return started_unix


def finish_scanner_run(
    started_unix,
    stats
):

    finished_unix = unix_now()
    finished_readable = local_now_string()

    duration = max(
        0,
        finished_unix - started_unix
    )

    try:

        db.reference("last_updated").set(
            {
                "timestamp": finished_readable,
                "unix": finished_unix,
                "status": "completed",
                "duration_seconds": duration,
            }
        )

        db.reference(
            "scanner_status"
        ).set(
            {
                "status": "completed",
                "started_at_unix": started_unix,
                "finished_at": finished_readable,
                "finished_at_unix": finished_unix,
                "duration_seconds": duration,
                "total_sources": stats["total"],
                "success": stats["success"],
                "no_notice": stats["no_notice"],
                "new_notices": stats["new_notices"],
                "failed": stats["failed"],
                "skipped": stats["skipped"],
                "notifications_sent": stats[
                    "notifications_sent"
                ],
                "notification_failures": stats[
                    "notification_failures"
                ],
            }
        )

    except Exception as e:

        print(
            f"⚠️ scanner status update failed: {e}"
        )


# =========================================================
# FIREBASE: 72-HOUR NOTICE CLEANUP
# =========================================================

def cleanup_expired_recent_notices():

    now = unix_now()

    recent_ref = db.reference(
        "today_latest_notice"
    )

    try:

        existing = (
            recent_ref.get()
            or {}
        )

        if not isinstance(
            existing,
            dict
        ):

            print(
                "⚠️ today_latest_notice format invalid; cleanup skipped."
            )

            return 0

        deleted = 0

        for key, value in list(
            existing.items()
        ):

            if not isinstance(
                value,
                dict
            ):

                continue

            expires_at = value.get(
                "expires_at_unix"
            )

            try:

                expires_at = int(
                    expires_at
                )

            except (
                TypeError,
                ValueError
            ):

                continue

            if expires_at <= now:

                try:

                    recent_ref.child(
                        key
                    ).delete()

                    deleted += 1

                except Exception as e:

                    print(
                        f"⚠️ Expired notice delete failed "
                        f"[{key}]: {e}"
                    )

        print(
            f"🧹 72-hour cleanup: "
            f"{deleted} টি expired notice deleted."
        )

        return deleted

    except Exception as e:

        print(
            f"⚠️ 72-hour cleanup failed: {e}"
        )

        return 0


# =========================================================
# FIREBASE: ADD NOTICE TO 72-HOUR FEED
# =========================================================

def add_to_recent_notices(
    source_id,
    pbs_code,
    name_bn,
    name_en,
    serial,
    item
):

    created_unix = unix_now()

    expires_unix = (
        created_unix
        +
        (RECENT_NOTICE_HOURS * 60 * 60)
    )

    payload = {

        "id": source_id,

        "pbs": pbs_code,

        "name_bn": name_bn,

        "name_en": name_en,

        "serial": serial,

        "notice_title": item.get(
            "title",
            ""
        ),

        "notice_link": item.get(
            "pdf_link",
            ""
        ),

        "notice_date": item.get(
            "date",
            ""
        ),

        "created_at": local_now_string(),

        "created_at_unix": created_unix,

        "expires_at_unix": expires_unix,

        "expires_after_hours":
            RECENT_NOTICE_HOURS,
    }

    try:

        db.reference(
            "today_latest_notice"
        ).push(
            payload
        )

        return True

    except Exception as e:

        print(
            f"⚠️ 72-hour notice save failed: {e}"
        )

        return False


# =========================================================
# SEND DATA-ONLY FCM
# =========================================================

def send_push_notification(
    source_id,
    name_bn,
    name_en,
    title,
    link,
    topic
):

    if not topic:

        print(
            f"⚠️ [{name_bn}] "
            "FCM Topic পাওয়া যায়নি।"
        )

        return False

    message = messaging.Message(

        # IMPORTANT:
        # notification= এখানে ব্যবহার করা হয়নি।
        # এটি DATA-ONLY FCM message.
        data={

            "id":
                source_id,

            "name_en":
                name_en,

            "title":
                f"🔔 {name_bn}",

            "body":
                title,

            "url":
                link,

            "source":
                name_bn,

            "click_action":
                "NOTICE_DETAILS",
        },

        topic=topic
    )

    try:

        response = messaging.send(
            message
        )

        print()
        print(
            f"📱 [{name_bn}] "
            "FCM Data-only notification "
            "সফলভাবে পাঠানো হয়েছে!"
        )

        print(
            f"   Topic: {topic}"
        )

        print(
            f"   Message ID: {response}"
        )

        return True

    except Exception as e:

        print()
        print(
            f"❌ [{name_bn}] "
            "FCM notification পাঠাতে ব্যর্থ!"
        )

        print(
            f"   Topic: {topic}"
        )

        print(
            f"   Error: {e}"
        )

        return False


# =========================================================
# MAIN NOTICE SCANNER
# =========================================================

def check_notices():

    if not validate_sources():

        return

    started_unix = start_scanner_run()

    cleanup_expired_recent_notices()

    stats = {

        "total":
            len(MASTER_SOURCES),

        "success":
            0,

        "no_notice":
            0,

        "new_notices":
            0,

        "failed":
            0,

        "skipped":
            0,

        "notifications_sent":
            0,

        "notification_failures":
            0,
    }

    print()
    print("=" * 70)

    print(
        f"[{local_now_string()}] "
        f"স্ক্যানিং শুরু হয়েছে: "
        f"মোট {len(MASTER_SOURCES)} টি অফিস/পবিস..."
    )

    print("=" * 70)

    for source in MASTER_SOURCES:

        source_id = str(
            source.get("id", "")
        ).strip()

        pbs_code = str(
            source.get("pbs", "")
        ).strip()

        name_bn = str(
            source.get("name_bn", "")
        ).strip()

        name_en = str(
            source.get("name_en", "")
        ).strip()

        serial = str(
            source.get("serial", "")
        ).strip()

        url = str(
            source.get("url", "")
        ).strip()

        topic = str(
            source.get("topic", "")
        ).strip()

        if not pbs_code:
            pbs_code = source_id

        print()
        print(
            f"🔎 [{name_bn}] স্ক্যান করা হচ্ছে..."
        )

        try:

            headers = {

                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/120.0.0.0 "
                    "Safari/537.36"
                )
            }

            request_started = time.time()

            response = requests.get(

                url,

                headers=headers,

                timeout=REQUEST_TIMEOUT,

                verify=False
            )

            response_seconds = round(
                time.time()
                -
                request_started,
                2
            )

            if response.status_code != 200:

                stats["failed"] += 1

                print(
                    f"⚠️ [{name_bn}] "
                    f"সাইট রেসপন্স করেনি। "
                    f"Status: {response.status_code} "
                    f"({response_seconds}s)"
                )

                time.sleep(
                    REQUEST_DELAY_SECONDS
                )

                continue

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            notice_table = soup.find(
                "table"
            )

            if not notice_table:

                stats["skipped"] += 1

                print(
                    f"⚠️ [{name_bn}] "
                    "কোনো table পাওয়া যায়নি।"
                )

                time.sleep(
                    REQUEST_DELAY_SECONDS
                )

                continue

            rows = notice_table.find_all(
                "tr"
            )

            notices_found = []

            for row in rows:

                cells = row.find_all(
                    "td"
                )

                if len(cells) < 2:
                    continue

                title_cell = cells[1]

                link_tag = title_cell.find(
                    "a"
                )

                notice_title = ""
                notice_link = ""
                notice_date = ""

                if (
                    link_tag
                    and
                    link_tag.text.strip()
                ):

                    notice_title = (
                        link_tag
                        .text
                        .strip()
                    )

                    notice_link = (
                        link_tag
                        .get(
                            "href",
                            ""
                        )
                        .strip()
                    )

                else:

                    text_val = (
                        title_cell
                        .text
                        .strip()
                    )

                    if text_val:

                        notice_title = (
                            text_val
                        )

                        any_link = (
                            row.find("a")
                        )

                        notice_link = (
                            any_link
                            .get(
                                "href",
                                ""
                            )
                            .strip()
                            if any_link
                            else ""
                        )

                if len(cells) >= 3:

                    notice_date = (
                        cells[2]
                        .text
                        .strip()
                    )

                if not notice_date:

                    notice_date = (
                        datetime.now()
                        .strftime(
                            "%d-%m-%Y"
                        )
                    )

                if notice_title:

                    if notice_link.startswith(
                        "/"
                    ):

                        base_domain = (
                            "/".join(
                                url.split("/")[:3]
                            )
                        )

                        notice_link = (
                            base_domain
                            +
                            notice_link
                        )

                    elif notice_link.startswith(
                        "//"
                    ):

                        notice_link = (
                            (
                                "https:"
                                if url.startswith(
                                    "https://"
                                )
                                else "http:"
                            )
                            +
                            notice_link
                        )

                    notices_found.append(
                        {
                            "title":
                                notice_title,

                            "pdf_link":
                                notice_link,

                            "date":
                                notice_date,
                        }
                    )

                    if (
                        len(notices_found)
                        >= MAX_NOTICES_PER_SOURCE
                    ):

                        break

            if not notices_found:

                stats["no_notice"] += 1

                print(
                    f"⚠️ [{name_bn}] "
                    "টেবিল থেকে কোনো notice পাওয়া যায়নি।"
                )

                time.sleep(
                    REQUEST_DELAY_SECONDS
                )

                continue

            stats["success"] += 1

            ref = db.reference(
                f"notices/{source_id}"
            )

            last_saved_title = (
                ref.child(
                    "last_title"
                ).get()
            )

            latest_notice = (
                notices_found[0]
            )

            notice_title = (
                latest_notice["title"]
            )

            notice_link = (
                latest_notice["pdf_link"]
            )

            notice_date = (
                latest_notice["date"]
            )

            # =================================================
            # UPDATE MAIN PBS NODE
            # =================================================

            ref.child("id").set(
                source_id
            )

            ref.child("pbs").set(
                pbs_code
            )

            ref.child("name_bn").set(
                name_bn
            )

            ref.child("name_en").set(
                name_en
            )

            ref.child("serial").set(
                serial
            )

            ref.child("pbs_url").set(
                url
            )

            ref.child("last_title").set(
                notice_title
            )

            ref.child("last_pdf").set(
                notice_link
            )

            ref.child(
                "last_notice_date"
            ).set(
                notice_date
            )

            ref.child(
                "last_scanned_at"
            ).set(
                local_now_string()
            )

            ref.child(
                "last_scanned_at_unix"
            ).set(
                unix_now()
            )

            # =================================================
            # HISTORY
            # =================================================

            history_ref = ref.child(
                "notices_history"
            )

            existing_history = (
                history_ref.get()
                or {}
            )

            existing_titles = set()

            if isinstance(
                existing_history,
                dict
            ):

                for value in (
                    existing_history.values()
                ):

                    if isinstance(
                        value,
                        dict
                    ):

                        old_title = value.get(
                            "notice_title"
                        )

                        if old_title:
                            existing_titles.add(
                                old_title
                            )

            newly_added_history = []

            for item in notices_found:

                item_title = item[
                    "title"
                ]

                if (
                    item_title
                    not in existing_titles
                ):

                    history_ref.push(
                        {
                            "id":
                                source_id,

                            "pbs":
                                pbs_code,

                            "name_bn":
                                name_bn,

                            "name_en":
                                name_en,

                            "serial":
                                serial,

                            "notice_title":
                                item_title,

                            "notice_link":
                                item[
                                    "pdf_link"
                                ],

                            "notice_date":
                                item[
                                    "date"
                                ],

                            "added_at":
                                local_now_string(),

                            "added_at_unix":
                                unix_now(),
                        }
                    )

                    existing_titles.add(
                        item_title
                    )

                    newly_added_history.append(
                        item
                    )

            # =================================================
            # 72-HOUR RECENT NOTICE FEED
            # =================================================

            for item in newly_added_history:

                added = (
                    add_to_recent_notices(
                        source_id,
                        pbs_code,
                        name_bn,
                        name_en,
                        serial,
                        item
                    )
                )

                if added:

                    stats[
                        "new_notices"
                    ] += 1

            # =================================================
            # NEW LATEST NOTICE → FCM
            # =================================================

            if (
                notice_title
                !=
                last_saved_title
            ):

                print()
                print(
                    "🚨 ======================================="
                )

                print(
                    f"🆕 [{name_bn}] "
                    "নতুন নোটিশ পাওয়া গেছে!"
                )

                print(
                    f"   Title: {notice_title}"
                )

                print(
                    f"   Link: {notice_link}"
                )

                print(
                    f"   Topic: {topic}"
                )

                print(
                    "🚨 ======================================="
                )

                sent = send_push_notification(

                    source_id,

                    name_bn,

                    name_en,

                    notice_title,

                    notice_link,

                    topic
                )

                if sent:

                    stats[
                        "notifications_sent"
                    ] += 1

                else:

                    stats[
                        "notification_failures"
                    ] += 1

            else:

                print(
                    f"✓ [{name_bn}] "
                    "কোনো নতুন notice নেই।"
                )

            print(
                f"   Firebase: ✅ Updated"
            )

            print(
                f"   History: "
                f"{len(newly_added_history)} "
                f"নতুন entry"
            )

            print(
                f"   Response time: "
                f"{response_seconds}s"
            )

        except requests.exceptions.Timeout:

            stats["failed"] += 1

            print(
                f"⏱️ [{name_bn}] "
                "Website request timeout."
            )

        except requests.exceptions.RequestException as e:

            stats["failed"] += 1

            print(
                f"🌐 [{name_bn}] "
                f"Website request error: {e}"
            )

        except Exception as e:

            stats["failed"] += 1

            print(
                f"❌ [{name_bn}] "
                f"স্ক্যান করতে গিয়ে সমস্যা হয়েছে: {e}"
            )

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

    # =========================================================
    # FINALIZE RUN
    # =========================================================

    finish_scanner_run(
        started_unix,
        stats
    )

    print()
    print("=" * 70)

    print(
        "📊 SCAN SUMMARY"
    )

    print(
        f"Total sources          : {stats['total']}"
    )

    print(
        f"Successful scans       : {stats['success']}"
    )

    print(
        f"No notice              : {stats['no_notice']}"
    )

    print(
        f"New history entries    : {stats['new_notices']}"
    )

    print(
        f"Failed                 : {stats['failed']}"
    )

    print(
        f"Skipped                 : {stats['skipped']}"
    )

    print(
        f"FCM sent               : {stats['notifications_sent']}"
    )

    print(
        f"FCM failed             : {stats['notification_failures']}"
    )

    print("=" * 70)


# =========================================================
# PROGRAM START
# =========================================================

if __name__ == "__main__":

    print()
    print("=" * 70)

    print(
        "🚀 PBS NOTICE SCANNER STARTED"
    )

    print(
        "📡 FCM MODE: DATA-ONLY"
    )

    print(
        "🔥 Firebase: ENABLED"
    )

    print(
        "🕒 Recent notice retention: "
        f"{RECENT_NOTICE_HOURS} hours"
    )

    print(
        "🇧🇩 Timezone: Asia/Dhaka (UTC+06:00)"
    )

    print("=" * 70)

    print()

    try:

        check_notices()

    except KeyboardInterrupt:

        print(
            "\n⛔ Scanner manually stopped."
        )

    except Exception as e:

        print(
            f"\n❌ Fatal scanner error: {e}"
        )

        # GitHub Actions-এ failure detect করার জন্য
        raise

    print()
    print("=" * 70)

    print(
        "✅ সকল PBS ও REB সাইটের "
        "স্ক্যানিং সম্পন্ন হয়েছে।"
    )

    print("=" * 70)
