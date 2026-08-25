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

# sources.json (বা targets.json) ফাইল থেকে পবিসগুলোর লিস্ট লোড করা
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
    source_id = source.get("id")          # যেমন: pbs1_bogra
    pbs_code = source.get("pbs", "")      # যেমন: bogra_1
    name_bn = source.get("name_bn")       # যেমন: বগুড়া পবিস-১
    name_en = source.get("name_en")       # যেমন: Bogra PBS-1
    serial = source.get("serial", "")     # যেমন: 77
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
              notice_date = ""

              if link_tag and link_tag.text.strip():
                notice_title = link_tag.text.strip()
                notice_link = link_tag.get("href", "")
              else:
                text_val = title_cell.text.strip()
                if text_val:
                  notice_title = text_val
                  any_link = row.find("a")
                  notice_link = any_link.get("href", "") if any_link else ""

              # যদি টেবিলে ডেট বা সময় থাকে তা সংগ্রহ করা
              if len(cells) >= 3:
                date_cell = cells[2] # সাধারণত ৩য় কলামে ডেট থাকে
                notice_date = date_cell.text.strip()

              if notice_title:
                if notice_link.startswith("/"):
                  base_domain = "/".join(url.split("/")[:3])
                  notice_link = base_domain + notice_link

                notices_found.append(
                    {
                        "title": notice_title,
                        "pdf_link": notice_link,
                        "date": notice_date,
                    }
                )

                if len(notices_found) >= 10:
                  break

          if notices_found:
            ref = db.reference(f"notices/{source_id}")
            last_saved_title = ref.child("last_title").get()

            latest_notice = notices_found[0]
            notice_title = latest_notice["title"]
            notice_link = latest_notice["pdf_link"]
            notice_date = latest_notice["date"]

            # ১. পবিসের মূল নোড আপডেট করা (যা দিয়ে অ্যাপের নোটিফিকেশন ট্রিগার হবে)
            ref.child("id").set(source_id)
            ref.child("pbs").set(pbs_code)
            ref.child("name_bn").set(name_bn)
            ref.child("name_en").set(name_en)
            ref.child("serial").set(serial)
            ref.child("pbs_url").set(url)
            ref.child("last_title").set(notice_title)
            ref.child("last_pdf").set(notice_link)

            # ২. হিস্ট্রি আপডেট করা (পুরনো ইতিহাস মুছে ফেলা হবে না, বরং নতুনগুলো চেক করে যুক্ত করা হবে)
            history_ref = ref.child("notices_history")
            existing_history = history_ref.get() or {}
            existing_titles = [
                val.get("notice_title")
                for val in existing_history.values()
                if isinstance(val, dict)
            ]

            for item in notices_found:
              if item["title"] not in existing_titles:
                history_ref.push(
                    {
                        "id": source_id,
                        "pbs": pbs_code,
                        "name_bn": name_bn,
                        "name_en": name_en,
                        "serial": serial,
                        "notice_title": item["title"],
                        "notice_link": item["pdf_link"],
                        "notice_date": item["date"],
                    }
                )

            # ৩. যদি নতুন নোটিশ হয় তবেই ফায়ারবেস কি আপডেট হবে এবং নোটিফিকেশন যাবে
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
  
