import os

from dotenv import load_dotenv

from collector.poller import run

load_dotenv()

if __name__ == "__main__":
    interval = int(os.getenv("POLL_INTERVAL_SECONDS", "7"))
    run(interval)
