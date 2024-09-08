from dataclasses import dataclass
from datetime import datetime, timedelta
import os
from typing import List
from decouple import config
from gtts import gTTS
import pygame
import requests
import sys
from time import sleep


SECRET_API_KEY = config("SECRET_API_KEY")
LIQUIDATION_URL = config(
    "LIQUIDATION_URL", default="https://api.coinalyze.net/v1/liquidation-history"
)
OPEN_INTEREST_URL = config(
    "OPEN_INTEREST_URL", default="https://api.coinalyze.net/v1/open-interest-history"
)
N_MINUTES_TIMEDELTA = config("N_MINUTES_TIMEDELTA", default=6, cast=int)
MINIMAL_LIQUIDATION = config("MINIMAL_LIQUIDATION", default=10_000, cast=int)
MINIMAL_OPEN_INTEREST = config("MINIMAL_OPEN_INTEREST", default=1_000_000, cast=int)
SLEEP_INTERVAL = config("SLEEP_INTERVAL", default=2, cast=int)
INTERVAL = config("INTERVAL", default="5min")
TMP_MP3_DIR = config("SPEECH_MP3_DIR", default="/tmp")


pygame.mixer.init()


def print_there(x: int, y: int, text: str) -> None:
    """Print text at the bottom on the terminal"""
    sys.stdout.write("\x1b7\x1b[%d;%df%s\x1b8" % (x, y, text))
    sys.stdout.flush()


def convert_speech_to_text(title: str, text: str) -> None:
    """Convert text to speech and play the speech

    Args:
        title (str): title of the speech for the temporary mp3 file
        text (str): text to convert to speech
    """
    # save speech to an mp3 file
    tts = gTTS(text=text, lang="en", slow=False)
    tts.save(f"{TMP_MP3_DIR}/{title}.mp3")

    # play the mp3 file
    pygame.mixer.music.load(f"/tmp/{title}.mp3")
    pygame.mixer.music.play()

    # wait for the mp3 to finish
    while pygame.mixer.music.get_busy():
        sleep(1)

    # unload the mp3 file
    pygame.mixer.music.unload()

    # remove the mp3 file
    os.remove(f"{TMP_MP3_DIR}/{title}.mp3")


@dataclass
class CoinalyzeScanner:
    """Scans coinalyze to notify for changes in open interest and liquidations through
    text to speech"""

    scanned_data: set

    @property
    def params(self) -> dict:
        """Returns the parameters for the request to the API"""
        return {
            "symbols": "BTCUSD.6",
            "from": int(
                datetime.timestamp(
                    datetime.now() - timedelta(minutes=N_MINUTES_TIMEDELTA)
                )
            ),
            "to": int(datetime.timestamp(datetime.now())),
            "interval": INTERVAL,
        }

    def handle_open_interest(self, history: dict) -> None:
        """Handle the open interest fluctuations

        Args:
            history (dict): history of the open interest
        """

        candle_time, candle_open, candle_high, candle_low = (
            history.get("t"),
            history.get("o"),
            history.get("h"),
            history.get("l"),
        )
        difference = abs(int(candle_high) - int(candle_low))
        open_interest_tuple = (candle_time, difference)
        if (
            difference >= MINIMAL_OPEN_INTEREST
            and open_interest_tuple not in self.scanned_data
        ):
            print(
                "Open interest changed:"
                + "\t\t"
                + f"${difference:>9}.-"
                + f"\t at {datetime.fromtimestamp(candle_time)}"
            )
            convert_speech_to_text(
                title=f"{candle_time}-{candle_open}-{difference}",
                text=f"Open interest changed by {difference}",
            )
            self.scanned_data.add(open_interest_tuple)

    def handle_liquidation_set(self, history: dict) -> None:
        """Handle the liquidation set and check for liquidations

        Args:
            history (dict): history of the liquidation
        """

        def _handle_liquidation(liquidation_amount: int, direction: str):
            """Internal function to handle the liquidation

            Args:
                liquidation_amount (int): amount of the liquidation
                direction (str): direction of the liquidation
            """
            liquidation_tuple = l_time, direction, liquidation_amount
            if liquidation_tuple not in self.scanned_data:
                print(
                    "Liquidation detected:"
                    + f"\t{direction}\t"
                    + f"${liquidation_amount:>9}.-"
                    + f"\t at {datetime.fromtimestamp(l_time)}"
                )
                convert_speech_to_text(
                    title=f"{l_time}-{direction}-{liquidation_amount}",
                    text=f"{liquidation_amount} {direction} liquidation detected",
                )
                self.scanned_data.add(liquidation_tuple)

        l_time, l_long, l_short = (
            history.get("t"),
            history.get("l"),
            history.get("s"),
        )
        if l_long > MINIMAL_LIQUIDATION:
            _handle_liquidation(l_long, "long")
        if l_short > MINIMAL_LIQUIDATION:
            _handle_liquidation(l_short, "short")

    def handle_url(self, url: str) -> List[dict]:
        """Handle the url and check for liquidations

        Args:
            url (str): url to check for liquidations
        """
        response = requests.get(
            url, headers={"api_key": SECRET_API_KEY}, params=self.params
        )
        response.raise_for_status()
        response_json = response.json()

        if not len(response_json):
            return []

        return response_json[0].get("history", [])


def main() -> None:
    print("Starting the liquidation detector")

    scanner = CoinalyzeScanner(set())

    while True:

        # print the current time at the bottom of the terminal
        print_there(100, 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        # check for liquidations
        for history in scanner.handle_url(LIQUIDATION_URL):
            scanner.handle_liquidation_set(history)

        # sleep for preferred interval
        sleep(SLEEP_INTERVAL)

        for history in scanner.handle_url(OPEN_INTEREST_URL):
            scanner.handle_open_interest(history)

        # sleep for preferred interval
        sleep(SLEEP_INTERVAL)


if __name__ == "__main__":
    main()
