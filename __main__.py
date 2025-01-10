from datetime import datetime, timedelta
import discord
import os
from typing import List
from decouple import config
from functools import cached_property
from gtts import gTTS
import os
import pygame
import requests
import sys
from time import sleep
from typing import List


ENABLE_DISCORD = config("ENABLE_DISCORD", default=False, cast=bool)
DISCORD_CHANNEL_ID = config("DISCORD_CHANNEL_ID", cast=int, default=0)
DISCORD_PRIVATE_KEY = config("DISCORD_PRIVATE_KEY", default="")

COINALYZE_SECRET_API_KEY = config("SECRET_API_KEY")
COINALYZE_LIQUIDATION_URL = config(
    "LIQUIDATION_URL", default="https://api.coinalyze.net/v1/liquidation-history"
)
FUTURE_MARKETS_URL = config(
    "FUTURES_MARKETS_URL", default="https://api.coinalyze.net/v1/future-markets"
)
N_MINUTES_TIMEDELTA = config("N_MINUTES_TIMEDELTA", default=6, cast=int)
MINIMAL_LIQUIDATION = config("MINIMAL_LIQUIDATION", default=10_000, cast=int)
SLEEP_INTERVAL = config("SLEEP_INTERVAL", default=60, cast=int)
INTERVAL = config("INTERVAL", default="5min")
TMP_MP3_DIR = config("SPEECH_MP3_DIR", default="/tmp")
ENABLE_SPEECH = config("ENABLE_SPEECH", default=True, cast=bool)

pygame.mixer.init()


def print_there(x: int, y: int, text: str) -> None:
    """Print text at the bottom on the terminal"""
    sys.stdout.write("\x1b7\x1b[%d;%df%s\x1b8" % (x, y, text))
    sys.stdout.flush()


def post_to_discord(message: str) -> None:
    """Post a message to discord

    Args:
        message (str): message to post to discord
    """
    # setup discord
    intents = discord.Intents.default()
    intents.messages = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        channel = client.get_channel(DISCORD_CHANNEL_ID)
        await channel.send(f"@everyone {message}")
        await client.close()

    client.run(token=DISCORD_PRIVATE_KEY)


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
        for market in self.handle_url(FUTURE_MARKETS_URL, False, True):
            if (symbol := market.get("symbol", "").upper()).startswith("BTCUSD"):
                symbols.append(symbol)
        print(f"Lenght of symbols: {len(symbols)}")
        return ",".join(symbols[:20])

    def handle_liquidation_set(self, symbols: list) -> None:
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
                liquidation_message = f"{direction} liquidation with value ${liquidation_amount:,}- detected"
                if ENABLE_DISCORD:
                    post_to_discord(liquidation_message)
                if ENABLE_SPEECH:
                    convert_speech_to_text(
                        title=f"{l_time}-{direction}-{liquidation_amount}",
                        text=liquidation_message,
                    )
                self.scanned_data.add(liquidation_tuple)

        total_long, total_short = 0, 0
        l_time = symbols[0].get("t") if len(symbols) else 0
        for history in symbols:
            total_long += round(history.get("l"), 0)
            total_short += round(history.get("s"), 0)
        if total_long > MINIMAL_LIQUIDATION:
            _handle_liquidation(total_long, "long")
        if total_short > MINIMAL_LIQUIDATION:
            _handle_liquidation(total_short, "short")

    def handle_url(
        self, url: str, include_params: bool = True, symbols: bool = False
    ) -> List[dict]:
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
        except Exception as e:
            print(str(e))
            return []

        if not len(response_json):
            return []

        if symbols:
            return response_json

        return [
            symbol.get("history")[0]
            for symbol in response_json
            if symbol.get("history")
        ]


def main() -> None:
    print("Starting the Coinalyze scanner")

    scanner = CoinalyzeScanner()

    while True:

        # print the current time at the bottom of the terminal
        print_there(100, 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        scanner.handle_liquidation_set(scanner.handle_url(COINALYZE_LIQUIDATION_URL))

        # sleep for preferred interval
        sleep(SLEEP_INTERVAL)


if __name__ == "__main__":
    main()
