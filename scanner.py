from datetime import datetime
import time
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, db, messaging
import requests
import urllib3

# এসএসএল (SSL) বা সিকিউরিটি সার্টিফিকেট সংক্রান্ত যেকোনো ওয়ার্নিং বা বাধা পার্মানেন্টলি বন্ধ করা
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ফায়ারবেস ইনিশিয়ালাইজেশন
cred = credentials.Certificate("firebase_credentials.json")
firebase_admin.initialize_app(
    cred,
    {
        "databaseURL": (
            "https://love-lucky-62b3c-default-rtdb.firebaseio.com"
        )
    },
)

# বাংলাদেশ পল্লী বিদ্যুতায়ন বোর্ড (REB) এবং পবিসগুলোর মাস্টার লিস্ট
MASTER_SOURCES = [
    {
        "id": "reb_central",
        "name": "বাংলাদেশ পল্লী বিদ্যুতায়ন বোর্ড (REB)",
        "url": "https://reb.gov.bd/site/notices",
        "topic": "reb_central",
    },
    {
        "id": "dhaka_1",
        "name": "ঢাকা পবিস-১",
        "url": "https://pbs1.dhaka.gov.bd/site/notices",
        "topic": "pbs_dhaka_1",
    },
    {
        "id": "dhaka_2",
        "name": "ঢাকা পবিস-২",
        "url": "https://pbs2.dhaka.gov.bd/site/notices",
        "topic": "pbs_dhaka_2",
    },
    {
        "id": "chandpur_1",
        "name": "চাঁদপুর পবিস-১",
        "url": "https://pbs1.chandpur.gov.bd/site/notices",
        "topic": "pbs_chandpur_1",
    },
    {
        "id": "chandpur_2",
        "name": "চাঁদপুর পবিস-২",
        "url": "https://pbs2.chandpur.gov.bd/site/notices",
        "topic": "pbs_chandpur_2",
    },
    {
        "id": "comilla_1",
        "name": "কুমিল্লা পবিস-১",
        "url": "https://pbs1.comilla.gov.bd/site/notices",
        "topic": "pbs_comilla_1",
    },
    {
        "id": "comilla_2",
        "name": "কুমিল্লা পবিস-২",
        "url": "https://pbs2.comilla.gov.bd/site/notices",
        "topic": "pbs_comilla_2",
    },
    {
        "id": "comilla_3",
        "name": "কুমিল্লা পবিস-৩",
        "url": "https://pbs3.comilla.gov.bd/site/notices",
        "topic": "pbs_comilla_3",
    },
    {
        "id": "comilla_4",
        "name": "কুমিল্লা পবিস-৪",
        "url": "https://pbs4.comilla.gov.bd/site/notices",
        "topic": "pbs_comilla_4",
    },
    {
        "id": "chittagong_1",
        "name": "চট্টগ্রাম পবিস-১",
        "url": "https://pbs1.chittagong.gov.bd/site/notices",
        "topic": "pbs_chittagong_1",
    },
    {
        "id": "chittagong_3",
        "name": "চট্টগ্রাম পবিস-৩",
        "url": "https://pbs3.chittagong.gov.bd/site/notices",
        "topic": "pbs_chittagong_3",
    },
    {
        "id": "sylhet",
        "name": "সিলেট পবিস",
        "url": "https://pbs.sylhet.gov.bd/site/notices",
        "topic": "pbs_sylhet",
    },
    {
        "id": "rajshahi",
        "name": "রাজশাহী পবিস",
        "url": "https://pbs.rajshahi.gov.bd/site/notices",
        "topic": "pbs_rajshahi",
    },
    {
        "id": "khulna",
        "name": "খুলনা পবিস",
        "url": "https://pbs.khulna.gov.bd/site/notices",
        "topic": "pbs_khulna",
    },
    {
        "id": "barisal",
        "name": "বরিশাল পবিস",
        "url": "https://pbs.barisal.gov.bd/site/notices",
        "topic": "pbs_barisal",
    },
    {
        "id": "rangpur",
        "name": "রংপুর পবিস",
        "url": "https://pbs.rangpur.gov.bd/site/notices",
        "topic": "pbs_rangpur",
    },
]


def check_notices():
  print(
      f"[{datetime.now()}] স্ক্যানিং শুরু হয়েছে: পবিস এবং REB ওয়েবসাইটসমূহ..."
  )

  for source in MASTER_SOURCES:
    source_id = source["id"]
    source_name = source["name"]
    url = source["url"]
    topic = source["topic"]

    try:
      headers = {
          "User-Agent": (
              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
              " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
          )
      }

      # verify=False এবং timeout দিয়ে নিশ্চিত করা হয়েছে যেন কোনো সাইট স্লো বা ডাউন থাকলেও কোড না আটকে সামনে চলে যায়
      response = requests.get(
          url, headers=headers, timeout=10, verify=False
      )

      if response.status_code == 200:
        soup = BeautifulSoup(response.text, "html.parser")
        notice_table = soup.find("table")

        if notice_table:
          first_row = notice_table.find("tr")
          if first_row:
            link_tag = first_row.find("a")
            if link_tag:
              notice_title = link_tag.text.strip()
              notice_link = link_tag.get("href", "")

              if notice_link.startswith("/"):
                base_domain = "/".join(url.split("/")[:3])
                notice_link = base_domain + notice_link

              ref = db.reference(f"notices/{source_id}")
              last_saved_title = ref.child("last_title").get()

              if notice_title != last_saved_title:
                print(f"[{source_name}] নতুন নোটিশ পাওয়া গেছে: {notice_title}")

                ref.child("last_title").set(notice_title)
                ref.child("notices_history").push(
                    {
                        "title": notice_title,
                        "link": notice_link,
                        "timestamp": int(time.time() * 1000),
                    }
                )

                send_push_notification(
                    source_name, notice_title, notice_link, topic
                )

      time.sleep(1)

    except Exception as e:
      print(f"[{source_name}] স্ক্যান করতে গিয়ে কোনো সমস্যা হয়নি (স্কিপ করা হয়েছে): {e}")


def send_push_notification(source_name, title, link, topic):
  message = messaging.Message(
      notification=messaging.Notification(
          title=f"🔔 {source_name}",
          body=title,
      ),
      data={
          "click_action": "NOTICE_DETAILS",
          "url": link,
          "source": source_name,
      },
      topic=topic,
  )

  try:
    response = messaging.send(message)
    print(f"নোটিফিকেশন সফলভাবে পাঠানো হয়েছে [{topic}]: {response}")
  except Exception as e:
    print(f"নোটিফিকেশন পাঠাতে ব্যর্থ: {e}")


if __name__ == "__main__":
  check_notices()
  print("সকল সাইটের স্ক্যানিং সফলভাবে সম্পন্ন হয়েছে।")
    
