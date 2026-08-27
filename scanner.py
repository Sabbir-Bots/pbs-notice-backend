from datetime import datetime
import json
import time

from bs4 import BeautifulSoup

import firebase_admin
from firebase_admin import credentials, db, messaging

import requests
import urllib3


# =========================================================
# SSL Certificate Warning বন্ধ করা
# =========================================================

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)


# =========================================================
# Firebase Initialize
# =========================================================

try:

    cred = credentials.Certificate(
        "firebase_credentials.json"
    )

    firebase_admin.initialize_app(
        cred,
        {
            "databaseURL": (
                "https://love-lucky-62b3c-default-rtdb.firebaseio.com"
            )
        },
    )

    print("✅ Firebase initialized successfully.")

except ValueError:

    # Firebase আগে থেকেই initialized থাকলে
    # এই error আসতে পারে।
    print("ℹ️ Firebase already initialized.")

except Exception as e:

    print(
        f"❌ Firebase initialization failed: {e}"
    )


# =========================================================
# sources.json Load
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


    # -----------------------------------------------------
    # Duplicate ID Check
    # -----------------------------------------------------

    ids = [
        str(
            source.get("id", "")
        ).strip()

        for source in MASTER_SOURCES
    ]


    if len(ids) != len(set(ids)):

        print(
            "❌ sources.json-এ duplicate id পাওয়া গেছে।"
        )

        return False


    # -----------------------------------------------------
    # Required Field Check
    # -----------------------------------------------------

    bad_entries = []


    for source in MASTER_SOURCES:

        source_id = str(
            source.get("id", "")
        ).strip()


        url = str(
            source.get("url", "")
        ).strip()


        if not source_id or not url:

            bad_entries.append(
                source_id or "<missing id>"
            )


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
# MAIN NOTICE SCANNER
# =========================================================

def check_notices():

    # -----------------------------------------------------
    # Validate sources আগে
    # -----------------------------------------------------

    if not validate_sources():

        return


    print()
    print("=" * 70)

    print(
        f"[{datetime.now()}] "
        f"স্ক্যানিং শুরু হয়েছে: "
        f"মোট {len(MASTER_SOURCES)} টি অফিস/পবিস..."
    )

    print("=" * 70)


    # =====================================================
    # প্রতিটি PBS / REB Scan
    # =====================================================

    for source in MASTER_SOURCES:

        # -------------------------------------------------
        # sources.json থেকে তথ্য নেওয়া
        # -------------------------------------------------

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


        # -------------------------------------------------
        # PBS code missing হলে ID backup
        # -------------------------------------------------

        if not pbs_code:

            pbs_code = source_id


        print()
        print(
            f"🔎 [{name_bn}] স্ক্যান করা হচ্ছে..."
        )


        try:

            # =================================================
            # HTTP Headers
            # =================================================

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


            # =================================================
            # Website Request
            # =================================================

            response = requests.get(

                url,

                headers=headers,

                timeout=30,

                verify=False
            )


            # =================================================
            # HTTP Response Check
            # =================================================

            if response.status_code != 200:

                print(
                    f"⚠️ [{name_bn}] "
                    f"সাইট রেসপন্স করেনি। "
                    f"Status: {response.status_code}"
                )

                time.sleep(1)

                continue


            # =================================================
            # HTML Parse
            # =================================================

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )


            # =================================================
            # প্রথম Table খোঁজা
            # =================================================

            notice_table = soup.find(
                "table"
            )


            if not notice_table:

                print(
                    f"⚠️ [{name_bn}] "
                    "কোনো table পাওয়া যায়নি।"
                )

                time.sleep(1)

                continue


            # =================================================
            # Table Rows
            # =================================================

            rows = notice_table.find_all(
                "tr"
            )


            notices_found = []


            # =================================================
            # প্রতিটি Row Process
            # =================================================

            for row in rows:

                cells = row.find_all(
                    "td"
                )


                # কমপক্ষে ২টি cell দরকার

                if len(cells) < 2:

                    continue


                title_cell = cells[1]


                link_tag = title_cell.find(
                    "a"
                )


                notice_title = ""

                notice_link = ""

                notice_date = ""


                # =================================================
                # Title + Link
                # =================================================

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
                        link_tag.get(
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


                        if any_link:

                            notice_link = (
                                any_link
                                .get(
                                    "href",
                                    ""
                                )
                                .strip()
                            )


                # =================================================
                # Notice Date
                # =================================================

                if len(cells) >= 3:

                    date_cell = cells[2]

                    notice_date = (
                        date_cell
                        .text
                        .strip()
                    )


                # =================================================
                # Date না পাওয়া গেলে Current Date
                # =================================================

                if not notice_date:

                    notice_date = (
                        datetime.now()
                        .strftime(
                            "%d-%m-%Y"
                        )
                    )


                # =================================================
                # Notice পাওয়া গেলে
                # =================================================

                if notice_title:

                    # ------------------------------------------------
                    # Relative URL → Absolute URL
                    # ------------------------------------------------

                    if notice_link.startswith("/"):

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


                    # ------------------------------------------------
                    # Protocol-relative URL
                    # যেমন //pbs.gov.bd/...
                    # ------------------------------------------------

                    elif notice_link.startswith("//"):

                        if url.startswith("https://"):

                            notice_link = (
                                "https:"
                                +
                                notice_link
                            )

                        else:

                            notice_link = (
                                "http:"
                                +
                                notice_link
                            )


                    # ------------------------------------------------
                    # Notice List-এ যোগ
                    # ------------------------------------------------

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


                    # সর্বোচ্চ ১০টি notice

                    if len(
                        notices_found
                    ) >= 10:

                        break


            # =================================================
            # কোনো Notice পাওয়া যায়নি
            # =================================================

            if not notices_found:

                print(
                    f"⚠️ [{name_bn}] "
                    "টেবিল থেকে কোনো notice পাওয়া যায়নি।"
                )

                time.sleep(1)

                continue


            # =================================================
            # Firebase Reference
            # =================================================

            ref = db.reference(
                f"notices/{source_id}"
            )


            # =================================================
            # আগের সর্বশেষ Notice Title
            # =================================================

            last_saved_title = (
                ref
                .child("last_title")
                .get()
            )


            # =================================================
            # Latest Notice
            # =================================================

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
            # নতুন Notice কিনা আগে নির্ধারণ
            # =================================================

            is_new_notice = (
                notice_title
                !=
                last_saved_title
            )


            # =================================================
            # Firebase Main Node Update
            # =================================================

            ref.child(
                "id"
            ).set(
                source_id
            )


            ref.child(
                "pbs"
            ).set(
                pbs_code
            )


            ref.child(
                "name_bn"
            ).set(
                name_bn
            )


            ref.child(
                "name_en"
            ).set(
                name_en
            )


            ref.child(
                "serial"
            ).set(
                serial
            )


            ref.child(
                "pbs_url"
            ).set(
                url
            )


            ref.child(
                "last_title"
            ).set(
                notice_title
            )


            ref.child(
                "last_pdf"
            ).set(
                notice_link
            )


            # =================================================
            # Notice History
            # =================================================

            history_ref = (
                ref.child(
                    "notices_history"
                )
            )


            existing_history = (
                history_ref.get()
                or {}
            )


            # =================================================
            # Existing Titles
            # =================================================

            existing_titles = []


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

                        old_title = (
                            value.get(
                                "notice_title"
                            )
                        )


                        if old_title:

                            existing_titles.append(
                                old_title
                            )


            # =================================================
            # History-তে নতুন Notice Save
            # =================================================

            new_history_count = 0


            for item in notices_found:

                if (
                    item["title"]
                    not in
                    existing_titles
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
                                item["title"],

                            "notice_link":
                                item["pdf_link"],

                            "notice_date":
                                item["date"],
                        }
                    )


                    new_history_count += 1


            # =================================================
            # NEW NOTICE → FCM
            # =================================================

            if is_new_notice:

                print()
                print(
                    "🚨 ======================================="
                )

                print(
                    f"🆕 [{name_bn}] "
                    "নতুন নোটিশ পাওয়া গেছে!"
                )

                print(
                    f"Title: {notice_title}"
                )

                print(
                    f"Link: {notice_link}"
                )

                print(
                    f"Topic: {topic}"
                )

                print(
                    "🚨 ======================================="
                )


                send_push_notification(

                    name_bn,

                    notice_title,

                    notice_link,

                    topic
                )


            else:

                print(
                    f"✓ [{name_bn}] "
                    "কোনো নতুন notice নেই।"
                )


            # =================================================
            # Summary
            # =================================================

            print(
                f"   Firebase: ✅ Updated"
            )

            print(
                f"   History: "
                f"{new_history_count} নতুন entry"
            )


        except requests.exceptions.Timeout:

            print(
                f"⏱️ [{name_bn}] "
                "Website request timeout."
            )


        except requests.exceptions.RequestException as e:

            print(
                f"🌐 [{name_bn}] "
                f"Website request error: {e}"
            )


        except Exception as e:

            print(
                f"❌ [{name_bn}] "
                f"স্ক্যান করতে গিয়ে সমস্যা হয়েছে: {e}"
            )


        # =================================================
        # প্রতি PBS-এর পরে ১ সেকেন্ড
        # =================================================

        time.sleep(1)


# =========================================================
# DATA-ONLY FCM PUSH NOTIFICATION
# =========================================================
#
# গুরুত্বপূর্ণ:
#
# এখানে notification= ব্যবহার করা হয়নি।
#
# শুধু data পাঠানো হচ্ছে।
#
# Android App-এর
# MyFirebaseMessagingService
# এই data গ্রহণ করে নিজের notification তৈরি করবে।
#
# =========================================================

def send_push_notification(
    name_bn,
    title,
    link,
    topic
):

    # -----------------------------------------------------
    # Topic না থাকলে Notification পাঠাব না
    # -----------------------------------------------------

    if not topic:

        print(
            f"⚠️ [{name_bn}] "
            "FCM Topic পাওয়া যায়নি। "
            "Notification পাঠানো হয়নি।"
        )

        return


    # -----------------------------------------------------
    # Data-only FCM Message
    # -----------------------------------------------------

    message = messaging.Message(

        data={

            "title":
                f"🔔 {name_bn}",

            "body":
                title,

            "url":
                link,

            "source":
                name_bn,

            "click_action":
                "NOTICE_DETAILS"
        },

        topic=topic
    )


    # -----------------------------------------------------
    # Send FCM
    # -----------------------------------------------------

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

    print("=" * 70)

    print()


    # -----------------------------------------------------
    # Main Scanner
    # -----------------------------------------------------

    check_notices()


    # -----------------------------------------------------
    # Finished
    # -----------------------------------------------------

    print()
    print("=" * 70)

    print(
        "✅ সকল PBS ও REB সাইটের "
        "স্ক্যানিং সফলভাবে সম্পন্ন হয়েছে।"
    )

    print("=" * 70)
