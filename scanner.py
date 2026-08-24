from datetime import datetime
import time
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, db, messaging
import requests

# ফায়ারবেস ইনিশিয়ালাইজেশন
cred = credentials.Certificate("firebase_credentials.json")
firebase_admin.initialize_app(
    cred,
    {
        "databaseURL": (
            "https://your-firebase-database-url.firebaseio.com"  # তোমার ফায়ারবেস URL
        )
    },
)

# ৮০টি পবিস এবং REB-এর মাস্টার লিস্ট (ধাপে ধাপে এখানে সবগুলোর ডেটা যুক্ত হবে)
MASTER_SOURCES = [
    {
        "id": "reb_central",
        "name": "বাংলাদেশ পল্লী বিদ্যুতায়ন বোর্ড (REB)",
        "url": "http://reb.gov.bd/site/notices",
        "topic": "reb_central",
    },
    {
        "id": "chandpur_2",
        "name": "চাঁদপুর পবিস-২",
        "url": "http://pbs2.chandpur.gov.bd/site/notices",
        "topic": "pbs_chandpur_2",
    },
    {
        "id": "dhaka_1",
        "name": "ঢাকা পবিস-১",
        "url": "http://pbs1.dhaka.gov.bd/site/notices",
        "topic": "pbs_dhaka_1",
    },
    # এভাবে বাকি পবিসগুলোর তথ্য এখানে যোগ করা হবে
]


def check_notices():
  print(
      f"[{datetime.now()}] স্ক্যানিং শুরু হয়েছে: সকল পবিস এবং REB ওয়েবসাইট..."
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
          )
      }
      response = requests.get(url, headers=headers, timeout=15)

      if response.status_code == 200:
        soup = BeautifulSoup(response.text, "html.parser")

        # gov.bd সাইটগুলোর সাধারণ নোটিশ টেবিল স্ট্রাকচার
        notice_table = soup.find("table")
        if notice_table:
          first_row = notice_table.find("tr")
          if first_row:
            link_tag = first_row.find("a")
            if link_tag:
              notice_title = link_tag.text.strip()
              notice_link = link_tag.get("href", "")

              # যদি relative link হয়, তবে মূল ডোমেইন যুক্ত করতে হবে
              if notice_link.startswith("/"):
                base_domain = "/".join(url.split("/")[:3])
                notice_link = base_domain + notice_link

              # ফায়ারবেস থেকে আগের সর্বশেষ নোটিশের টাইটেল চেক করা
              ref = db.reference(f"notices/{source_id}")
              last_saved_title = ref.child("last_title").get()

              if notice_title != last_saved_title:
                print(f"[{source_name}] নতুন নোটিশ পাওয়া গেছে: {notice_title}")

                # ১. ফায়ারবেস ডাটাবেসে আপডেট সেভ করা
                ref.child("last_title").set(notice_title)
                ref.child("notices_history").push(
                    {
                        "title": notice_title,
                        "link": notice_link,
                        "timestamp": int(time.time() * 1000),
                    }
                )

                # ২. নির্দিষ্ট FCM টপিকে পুশ নোটিফিকেশন পাঠানো
                send_push_notification(source_name, notice_title, notice_link, topic)

      time.sleep(2)  # সার্ভারের ওপর অতিরিক্ত চাপ এড়াতে সামান্য বিরতি

    except Exception as e:
      print(f"[{source_name}] স্ক্যান করতে গিয়ে সমস্যা হয়েছে: {e}")


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


# ব্যাকগ্রাউন্ড লুপ (প্রতি ৩০ মিনিট পর পর সব সাইট চেক করবে)
if __name__ == "__main__":
  while True:
    check_notices()
    print("পরবর্তী স্ক্যানের জন্য ৩০ মিনিট অপেক্ষা করা হচ্ছে...\n")
    time.sleep(1800)  # ১৮০০ সেকেন্ড = ৩০ মিনিট
      
