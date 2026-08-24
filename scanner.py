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
  pass

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
          notices_found = []

          # টেবিল থেকে প্রথম ৫-১০টি নোটিশ সংগ্রহ করা
          for row in rows:
            cells = row.find_all("td")
            if len(cells) >= 2:
              title_cell = cells[1]
              link_tag = title_cell.find("a")

              notice_title = ""
              notice_link = ""

              if link_tag and link_tag.text.strip():
                notice_title = link_tag.text.strip()
                notice_link = link_tag.get("href", "")
              else:
                text_val = title_cell.text.strip()
                if text_val:
                  notice_title = text_val
                  any_link = row.find("a")
                  notice_link = any_link.get("href", "") if any_link else ""

              if notice_title:
                if notice_link.startswith("/"):
                  base_domain = "/".join(url.split("/")[:3])
                  notice_link = base_domain + notice_link

                notices_found.append(
                    {"title": notice_title, "link": notice_link}
                )

                # সর্বোচ্চ ১০টি নোটিশ নেব
                if len(notices_found) >= 10:
                  break

          if notices_found:
            ref = db.reference(f"notices/{source_id}")
            last_saved_title = ref.child("last_title").get()

            # একদম লেটেস্ট নোটিশটি নিয়ে কাজ শুরু
            latest_notice = notices_found[0]
            notice_title = latest_notice["title"]
            notice_link = latest_notice["link"]

            # ফরম্যাটেড ডেট ও টাইম তৈরি (যেমন: 24-08-2026 Mon, 06:32:55 PM)
            current_time = datetime.now()
            formatted_time = current_time.strftime("%d-%m-%Y %a, %I:%M:%S %p")
            timestamp_ms = int(time.time() * 1000)

            # যদি নতুন নোটিশ হয়, তবে পুরো হিস্ট্রি আপডেট করা এবং নোটিফিকেশন পাঠানো
            if notice_title != last_saved_title:
              print(f"[{source_name}] নতুন নোটিশ পাওয়া গেছে: {notice_title}")

              # পবিসের মূল নোডে লেটেস্ট তথ্যগুলো সেভ করা (অ্যাপের হোম পেইজের লিস্টের জন্য)
              ref.child("last_title").set(notice_title)
              ref.child("last_link").set(notice_link)
              ref.child("source_name").set(source_name)
              ref.child("formatted_time").set(formatted_time)
              ref.child("timestamp").set(timestamp_ms)

              # ভেতরের ডিটেইলস লিস্টের জন্য হিস্ট্রি নোড ফ্রেশ করে বা পুশ করে সাজানো
              history_ref = ref.child("notices_history")
              history_ref.delete()  # পুরানো লিস্ট মুছে নতুন ৫-১০ টা ফ্রেশ লিস্ট দেওয়ার জন্য

              for item in notices_found:
                history_ref.push(
                    {
                        "source_name": source_name,
                        "title": item["title"],
                        "link": item["link"],
                        "formatted_time": formatted_time,
                        "timestamp": timestamp_ms,
                    }
                )

              send_push_notification(
                  source_name, notice_title, notice_link, topic
              )
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
  
