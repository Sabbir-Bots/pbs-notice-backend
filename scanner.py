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
            "databaseURL":
                "https://love-lucky-62b3c-default-rtdb.firebaseio.com"
        },
    )

except ValueError:
    pass


# =========================================================
# sources.json থেকে PBS List Load
# =========================================================

try:

    with open(
        "sources.json",
        "r",
        encoding="utf-8"
    ) as f:

        MASTER_SOURCES = json.load(f)

except Exception as e:

    print(
        f"sources.json ফাইল পড়তে সমস্যা হয়েছে: {e}"
    )

    MASTER_SOURCES = []


# =========================================================
# TEST FCM NOTIFICATION
# =========================================================
#
# এটা শুধুমাত্র আমাদের FCM Data-only notification
# পরীক্ষা করার জন্য।
#
# Topic:
# test_notification_topic
#
# এই message-এ notification payload নেই।
# শুধু data payload আছে।
#
# =========================================================

def send_test_notification():

    print()
    print("=" * 60)
    print("FCM DATA-ONLY TEST STARTED")
    print("=" * 60)

    message = messaging.Message(

        data={
            "title": "🔔 PBS Notice Alert TEST",

            "body":
                "FCM Data-only notification সফলভাবে এসেছে!",

            "url":
                "https://example.com",

            "source":
                "TEST"
        },

        topic="test_notification_topic",
    )

    try:

        response = messaging.send(message)

        print()
        print("FCM TEST SENT SUCCESSFULLY!")
        print(f"Message ID: {response}")

        print()
        print(
            "Topic: test_notification_topic"
        )

        print()
        print(
            "এখন ফোনে notification আসার কথা।"
        )

        print("=" * 60)

    except Exception as e:

        print()
        print("FCM TEST FAILED!")
        print(f"Error: {e}")

        print("=" * 60)


# =========================================================
# MAIN PBS SCANNER
# =========================================================

def check_notices():

    print(
        f"[{datetime.now()}] স্ক্যানিং শুরু হয়েছে: "
        f"মোট {len(MASTER_SOURCES)} টি অফিস/পবিস..."
    )

    for source in MASTER_SOURCES:

        # -------------------------------------------------
        # sources.json থেকে Data নেওয়া
        # -------------------------------------------------

        source_id = source.get("id")

        pbs_code = source.get(
            "pbs",
            ""
        )

        name_bn = source.get(
            "name_bn"
        )

        name_en = source.get(
            "name_en"
        )

        serial = source.get(
            "serial",
            ""
        )

        url = source.get(
            "url"
        )

        topic = source.get(
            "topic"
        )


        # -------------------------------------------------
        # PBS Code না থাকলে ID ব্যবহার
        # -------------------------------------------------

        if not pbs_code:

            pbs_code = source_id


        print(
            f"[{name_bn}] স্ক্যান করা হচ্ছে..."
        )


        try:

            # -------------------------------------------------
            # Request Headers
            # -------------------------------------------------

            headers = {

                "User-Agent":
                    (
                        "Mozilla/5.0 "
                        "(Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 "
                        "(KHTML, like Gecko) "
                        "Chrome/120.0.0.0 "
                        "Safari/537.36"
                    )
            }


            # -------------------------------------------------
            # Website Request
            # -------------------------------------------------

            response = requests.get(

                url,

                headers=headers,

                timeout=30,

                verify=False
            )


            # -------------------------------------------------
            # HTTP 200
            # -------------------------------------------------

            if response.status_code == 200:

                soup = BeautifulSoup(
                    response.text,
                    "html.parser"
                )


                notice_table = soup.find(
                    "table"
                )


                # -------------------------------------------------
                # Table পাওয়া গেছে
                # -------------------------------------------------

                if notice_table:

                    rows = notice_table.find_all(
                        "tr"
                    )

                    notices_found = []


                    # -------------------------------------------------
                    # প্রতিটি Row Scan
                    # -------------------------------------------------

                    for row in rows:

                        cells = row.find_all(
                            "td"
                        )


                        if len(cells) >= 2:

                            title_cell = cells[1]

                            link_tag = title_cell.find(
                                "a"
                            )


                            notice_title = ""

                            notice_link = ""

                            notice_date = ""


                            # -------------------------------------------------
                            # Title + Link
                            # -------------------------------------------------

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
                                        row.find(
                                            "a"
                                        )
                                    )


                                    notice_link = (
                                        any_link
                                        .get(
                                            "href",
                                            ""
                                        )
                                        if any_link
                                        else ""
                                    )


                            # -------------------------------------------------
                            # Date
                            # -------------------------------------------------

                            if len(cells) >= 3:

                                date_cell = cells[2]

                                notice_date = (
                                    date_cell
                                    .text
                                    .strip()
                                )


                            # -------------------------------------------------
                            # Date না থাকলে আজকের Date
                            # -------------------------------------------------

                            if not notice_date:

                                notice_date = (
                                    datetime.now()
                                    .strftime(
                                        "%d-%m-%Y"
                                    )
                                )


                            # -------------------------------------------------
                            # Notice পাওয়া গেলে
                            # -------------------------------------------------

                            if notice_title:

                                # Relative URL → Absolute URL

                                if notice_link.startswith(
                                    "/"
                                ):

                                    base_domain = (
                                        "/".join(
                                            url
                                            .split("/")[:3]
                                        )
                                    )

                                    notice_link = (
                                        base_domain
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


                                # সর্বোচ্চ ১০টি Notice

                                if len(
                                    notices_found
                                ) >= 10:

                                    break


                    # -------------------------------------------------
                    # Notice পাওয়া গেছে
                    # -------------------------------------------------

                    if notices_found:

                        ref = db.reference(
                            f"notices/{source_id}"
                        )


                        last_saved_title = (
                            ref
                            .child(
                                "last_title"
                            )
                            .get()
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


                        # -------------------------------------------------
                        # PBS Main Node Update
                        # -------------------------------------------------

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


                        # -------------------------------------------------
                        # Notice History
                        # -------------------------------------------------

                        history_ref = (
                            ref.child(
                                "notices_history"
                            )
                        )


                        existing_history = (
                            history_ref.get()
                            or {}
                        )


                        existing_titles = [

                            val.get(
                                "notice_title"
                            )

                            for val
                            in existing_history.values()

                            if isinstance(
                                val,
                                dict
                            )
                        ]


                        # -------------------------------------------------
                        # নতুন Notice History-তে Save
                        # -------------------------------------------------

                        for item in notices_found:

                            if (
                                item["title"]
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
                                            item["title"],

                                        "notice_link":
                                            item["pdf_link"],

                                        "notice_date":
                                            item["date"],
                                    }
                                )


                        # -------------------------------------------------
                        # নতুন Notice হলে Notification
                        # -------------------------------------------------

                        if (
                            notice_title
                            !=
                            last_saved_title
                        ):

                            print(
                                f"[{name_bn}] "
                                f"নতুন নোটিশ পাওয়া গেছে: "
                                f"{notice_title}"
                            )


                            send_push_notification(

                                name_bn,

                                notice_title,

                                notice_link,

                                topic
                            )


                    else:

                        print(
                            f"[{name_bn}] "
                            "টেবিল থেকে কোনো "
                            "শিরোনাম পাওয়া যায়নি।"
                        )


                else:

                    print(
                        f"[{name_bn}] "
                        "কোনো টেবিল পাওয়া যায়নি।"
                    )


            else:

                print(
                    f"[{name_bn}] "
                    "সাইট রেসপন্স করেনি। "
                    f"স্ট্যাটাস কোড: "
                    f"{response.status_code}"
                )


        except Exception as e:

            print(
                f"[{name_bn}] "
                f"স্ক্যান করতে গিয়ে সমস্যা হয়েছে: "
                f"{e}"
            )


        # -------------------------------------------------
        # প্রতি PBS-এর পরে ১ সেকেন্ড অপেক্ষা
        # -------------------------------------------------

        time.sleep(1)


# =========================================================
# PRODUCTION PUSH NOTIFICATION
# =========================================================

def send_push_notification(
    name_bn,
    title,
    link,
    topic
):

    if not topic:

        return


    message = messaging.Message(

        notification=messaging.Notification(

            title=f"🔔 {name_bn}",

            body=title,
        ),


        data={

            "click_action":
                "NOTICE_DETAILS",

            "url":
                link,

            "source":
                name_bn,
        },


        topic=topic,
    )


    try:

        response = messaging.send(
            message
        )

        print(
            f"নোটিফিকেশন সফলভাবে পাঠানো হয়েছে "
            f"[{topic}]: {response}"
        )


    except Exception as e:

        print(
            f"নোটিফিকেশন পাঠাতে ব্যর্থ: {e}"
        )


# =========================================================
# PROGRAM START
# =========================================================
#
# ⚠️ এখন শুধুমাত্র FCM TEST চলবে।
#
# PBS Scanner এখন চলবে না।
#
# Test সফল হলে এই অংশ আবার:
#
#     check_notices()
#
# করা হবে।
#
# =========================================================

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("PBS NOTICE SCANNER - FCM TEST MODE")
    print("=" * 60)

    send_test_notification()

    print()
    print(
        "FCM test শেষ হয়েছে।"
    )

    print("=" * 60)
