from datetime import datetime
import json
import time
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, db, messaging
import requests
import urllib3

# এসএসএল সার্টিফিকেট ওয়ার্নিং বন্ধ করা
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ফায়ারবেস ইনিশিয়ালাইজেশন
try:
  cred = credentials.Certificate("firebase_credentials.json")
  firebase_admin.initialize_app(
      cred,
      {
          "databaseURL": (
              "https://love-lucky-62b3c-default-rtdb.firebaseio.com"
          )
      },
  )
except ValueError:
  pass  # ইতিমধ্যে ইনিশিয়ালাইজড থাকলে এরর এড়াতে

# sources.json ফাইল থেকে পবিসগুলোর লিস্ট লোড করা
try:
  with open("sources.json", "r", encoding="utf-8") as f:
    MASTER_SOURCES = json.load(f)
except Exception as e:
  print(f"sources.json ফাইল পড়তে সমস্যা হয়েছে: {e}")
  MASTER_SOURCES = []


def check_notices():
  print(
      f"[{datetime.now()}] স্ক্যানিং শুরু হয়েছে: মোট {len(MASTER_SOURCES)}"
      " টি অফিস/পবিস..."
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

      response = requests.get(
          url, headers=headers, timeout=60, verify=False
      )

      if response.status_code == 200:
        soup = BeautifulSoup(response.text, "html.parser")
        notice_table = soup.find("table")

        if notice_table:
          rows = notice_table.find_all("tr")
          notice_title = ""
          notice_link = ""

          # টেবিলের হেডার বাদ দিয়ে ডাটা রো থেকে সঠিক শিরোনাম ও লিংক খুঁজে বের করা
          for row in rows:
            cells = row.find_all("td")
            if len(cells) >= 2:
              # দ্বিতীয় কলামে (cells[1]) সাধারণত শিরোনাম থাকে
              title_cell = cells[1]
              link_tag = title_cell.find("a")

              if link_tag and link_tag.text.strip():
                notice_title = link_tag.text.strip()
                notice_link = link_tag.get("href", "")
                break
              else:
                text_val = title_cell.text.strip()
                if text_val:
                  notice_title = text_val
                  # অন্য কোনো কলামে বা পুরো রো তে কোনো পিডিএফ লিংক থাকলে তা নেওয়া
                  any_link = row.find("a")
                  notice_link = any_link.get("href", "") if any_link else ""
                  break

          if notice_title:
            # যদি relative link হয় তবে মূল ডোমেইন যুক্ত করা
            if notice_link.startswith("/"):
              base_domain = "/".join(url.split("/")[:3])
              notice_link = base_domain + notice_link

            ref = db.reference(f"notices/{source_id}")
            last_saved_title = ref.child("last_title").get()

            # নতুন নোটিশ হলে ফায়ারবেসে সেভ করা
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
          else:
            print(f"[{source_name}] টেবিল থেকে কোনো শিরোনাম পাওয়া যায়নি।")
        else:
          print(f"[{source_name}] কোনো টেবিল পাওয়া যায়নি।")

      time.sleep(1)

    except Exception as e:
      print(f"[{source_name}] স্কিপ করা হয়েছে (ত্রুটি): {e}")


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
  print("সকল পবিস ও REB সাইটের স্ক্যানিং সফলভাবে সম্পন্ন হয়েছে।")
  
