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
    # sources.json থেকে প্রয়োজনীয় ফিল্ডগুলো সঠিকভাবে তুলে নেওয়া
    source_id = source.get("id")  # যেমন: pbs1_bogra বা bogra_1
    name_bn = source.get("name_bn")  # যেমন: বগুড়া পবিস-১
    name_en = source.get("name_en")  # যেমন: Bogra PBS-1
    url = source.get("url")
    topic = source.get("topic")

    print(f"[{name_bn}] স্ক্যান করা হচ্ছে...")

    try:
      headers = {
          "User-Agent": (
              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
              " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
          )
      }

      response = requests.get(
          url, headers=headers, timeout=30, verify=False
      )

      if response.status_code == 200:
        soup = BeautifulSoup(response.text, "html.parser")
        notice_table = soup.find("table")

        if notice_table:
          rows = notice_table.find_all("tr")
          notices_found = []

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
                    {"title": notice_title, "pdf_link": notice_link}
                )

                if len(notices_found) >= 10:
                  break

          if notices_found:
            ref = db.reference(f"notices/{source_id}")
            last_saved_title = ref.child("last_title").get()

            latest_notice = notices_found[0]
            notice_title = latest_notice["title"]
            notice_link = latest_notice["pdf_link"]

            current_time = datetime.now()
            formatted_time = current_time.strftime("%d-%m-%Y %a, %I:%M:%S %p")

            # নতুন নোটিশ হোক বা না হোক, অথবা প্রথমবার রান করার সময় ডাটা সিঙ্ক নিশ্চিত করতে
            # পবিসের বেস ইনফো সবসময় আপডেট থাকবে
            ref.child("id").set(source_id)
            ref.child("name_bn").set(name_bn)
            ref.child("name_en").set(name_en)
            ref.child("last_title").set(notice_title)
            ref.child("last_link").set(notice_link)
            ref.child("formatted_time").set(formatted_time)

            # হিস্ট্রি আপডেট করা
            history_ref = ref.child("notices_history")
            history_ref.delete()

            for item in notices_found:
              history_ref.push(
                  {
                      "id": source_id,
                      "name_bn": name_bn,
                      "name_en": name_en,
                      "title": item["title"],
                      "pdf_link": item["pdf_link"],
                      "formatted_time": formatted_time,
                  }
              )

            # যদি নতুন নোটিশ হয় তবেই নোটিফিকেশন যাবে
            if notice_title != last_saved_title:
              print(f"[{name_bn}] নতুন নোটিশ পাওয়া গেছে: {notice_title}")
              send_push_notification(
                  name_bn, notice_title, notice_link, topic
              )
          else:
            print(f"[{name_bn}] টেবিল থেকে কোনো শিরোনাম পাওয়া যায়নি।")
        else:
          print(f"[{name_bn}] কোনো টেবিল পাওয়া যায়নি।")
      else:
        print(
            f"[{name_bn}] সাইট রেসপন্স করেনি। স্ট্যাটাস কোড:"
            f" {response.status_code}"
        )

    except Exception as e:
      # কোনো পবিসে এরর আসলেও যেন লুপ ভেঙে না গিয়ে পরের পবিসে চলে যায়
      print(f"[{name_bn}] স্ক্যান করতে গিয়ে সমস্যা হয়েছে: {e}")

    time.sleep(1)


def send_push_notification(name_bn, title, link, topic):
  if not topic:
    return
  message = messaging.Message(
      notification=messaging.Notification(
          title=f"🔔 {name_bn}",
          body=title,
      ),
      data={
          "click_action": "NOTICE_DETAILS",
          "url": link,
          "source": name_bn,
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
  
