from datetime import datetime, timedelta
from decouple import config
from functools import cached_property
from gtts import gTTS
import os
import pygame
import requests
import sys
from time import sleep
from typing import List


SECRET_API_KEY = config("SECRET_API_KEY")
LIQUIDATION_URL = config(
    "LIQUIDATION_URL", default="https://api.coinalyze.net/v1/liquidation-history"
)
OPEN_INTEREST_URL = config(
    "OPEN_INTEREST_URL", default="https://api.coinalyze.net/v1/open-interest-history"
)
FUTURE_MARKETS_URL = config(
    "FUTURES_MARKETS_URL", default="https://api.coinalyze.net/v1/future-markets"
)
N_MINUTES_TIMEDELTA = config("N_MINUTES_TIMEDELTA", default=6, cast=int)
MINIMAL_LIQUIDATION = config("MINIMAL_LIQUIDATION", default=10_000, cast=int)
MINIMAL_OPEN_INTEREST = config("MINIMAL_OPEN_INTEREST", default=10_000_000, cast=int)
ROUNDED_DIFFERENCE_OPEN_INTEREST = config(
    "ROUNDED_DIFFERENCE_OPEN_INTEREST", default=-6, cast=int
)
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
    pygame.mixer.music.set_volume(0.5)
    pygame.mixer.music.play()

    # wait for the mp3 to finish
    while pygame.mixer.music.get_busy():
        sleep(1)

    # unload the mp3 file
    pygame.mixer.music.unload()

    # remove the mp3 file
    os.remove(f"{TMP_MP3_DIR}/{title}.mp3")


class CoinalyzeScanner:
    """Scans coinalyze to notify for changes in open interest and liquidations through
    text to speech"""

    def __init__(self):
        self.scanned_data = set()

    @property
    def params(self) -> dict:
        """Returns the parameters for the request to the API"""
        return {
            "symbols": self.symbols,
            "from": int(
                datetime.timestamp(
                    datetime.now() - timedelta(minutes=N_MINUTES_TIMEDELTA)
                )
            ),
            "to": int(datetime.timestamp(datetime.now())),
            "interval": INTERVAL,
        }

    @cached_property
    def symbols(self) -> str:
        """Returns the symbols for the request to the API"""
        symbols = []
        for market in self.handle_url(FUTURE_MARKETS_URL, False):
            if (symbol := market.get("symbol", "").upper()).startswith("BTC"): 
                symbols.append(symbol)
        return ",".join(symbols)

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
        rounded_difference = round(difference, ROUNDED_DIFFERENCE_OPEN_INTEREST)
        open_interest_tuple = (candle_time, rounded_difference)
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
                text=f"Change in open interest with value {difference} detected",
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
                    text=f"{direction} liquidation with value {liquidation_amount} detected",
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

    def handle_url(self, url: str, include_params: bool = True) -> List[dict]:
        """Handle the url and check for liquidations

        Args:
            url (str): url to check for liquidations
        """
        try:
            response = requests.get(
                url,
                headers={"api_key": SECRET_API_KEY},
                params=self.params if include_params else {},
            )
            response.raise_for_status()
            response_json = response.json()
        # except Exception:
        except Exception as e:
            print(str(e))
            return []

        if not len(response_json):
            return []

        # TODO: return response_json
        return response_json[0].get("history", [])


def main() -> None:
    print("Starting the Coinalyze scanner")

    scanner = CoinalyzeScanner()

    while True:

        # print the current time at the bottom of the terminal
        print_there(100, 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        # check for liquidations
        # TODO: remove loop and look into list
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
