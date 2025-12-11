# Params
csv_path = "/Users/cooperfoster/Desktop/hoops/brk_repl2.csv"          # CSV with column 'game_id'
out_dir   = "/Users/cooperfoster/Desktop/hoops/brk dirty"        # folder for *.txt
max_per_minute = 6                          # hard cap

# ---- Code ----
import pandas as pd
from pathlib import Path
from time import sleep, monotonic

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

URL_TPL = "https://www.basketball-reference.com/boxscores/shot-chart/{gid}.html"
DELAY = 60.0 / max_per_minute  # seconds between requests

# I/O
ids = pd.read_csv(csv_path)["game_id"].astype(str).tolist()
Path(out_dir).mkdir(parents=True, exist_ok=True)

# Selenium
opts = Options()
opts.add_argument("--headless=new")
opts.add_argument("--disable-gpu")
opts.add_argument("--no-sandbox")
opts.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
opts.add_experimental_option("excludeSwitches", ["enable-automation"])
opts.add_experimental_option("useAutomationExtension", False)
driver = webdriver.Chrome(options=opts)

start = monotonic()
last_req = start
done = 0
skipped = 0

try:
    for gid in ids:
        out_file = Path(out_dir) / f"{gid}.txt"
        if out_file.exists():
            skipped += 1
            continue

        # rate limit
        elapsed = monotonic() - last_req
        if elapsed < DELAY:
            sleep(DELAY - elapsed)

        url = URL_TPL.format(gid=gid)
        try:
            driver.get(url)
            html = driver.page_source
            out_file.write_text(html, encoding="utf-8")
            done += 1
            last_req = monotonic()
            print(f"saved {gid}")
        except Exception as e:
            # simple retry once after delay
            sleep(DELAY)
            try:
                driver.get(url)
                html = driver.page_source
                out_file.write_text(html, encoding="utf-8")
                done += 1
                last_req = monotonic()
                print(f"saved {gid} (retry)")
            except Exception as e2:
                print(f"failed {gid}: {e2}")

finally:
    driver.quit()
    total_s = monotonic() - start
    print(f"completed. saved={done}, skipped_existing={skipped}, time_sec={int(total_s)}")