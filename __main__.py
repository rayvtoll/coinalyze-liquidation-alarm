from dataclasses import dataclass
from datetime import datetime, timedelta
from decouple import config
import numpy as np
import requests
import sounddevice as sd
import sys
from time import sleep


SECRET_API_KEY = config("SECRET_API_KEY")
URL = config("URL", default="https://api.coinalyze.net/v1/liquidation-history")
N_MINUTES_TIMEDELTA = config("N_MINUTES_TIMEDELTA", default=6, cast=int)
MINIMAL_LIQUIDATION = config("MINIMAL_LIQUIDATION", default=10_000, cast=int)
SLEEP_INTERVAL = config("SLEEP_INTERVAL", default=2, cast=int)
INTERVAL = config("INTERVAL", default="5min")


def print_there(x, y, text) -> None:
    """Print text at the bottom on the terminal"""
    sys.stdout.write("\x1b7\x1b[%d;%df%s\x1b8" % (x, y, text))
    sys.stdout.flush()


def play_sound() -> None:
    """Play a sound"""
    # Parameters for the sine wave
    duration = 0.05  # Duration in seconds
    sample_rate = 44100  # Sample rate in Hz
    waveform = np.sin(
        np.pi
        * 880  # Frequency in Hz (A5 note)
        * np.linspace(0, duration, int(duration * sample_rate), endpoint=False)
    )

    # Play the sine wave
    sd.play(waveform, sample_rate)
    sleep(1)
    sd.stop()
    sd.wait()


@dataclass
class LiquidationScanner:
    liquidations: set

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

    def handle_liquidation_set(self, history: dict) -> None:
        """Handle the liquidation set and check for liquidations

        Args:
            liquidations (set): set of liquidations
            history (dict): history of the liquidation
        """

        def _handle_liquidation(liquidation_amount: int, direction: str):
            """Internal function to handle the liquidation
            
            Args:
                liquidation_amount (int): amount of the liquidation
                direction (str): direction of the liquidation
            """
            liquidation_tuple = l_time, direction, liquidation_amount
            if liquidation_tuple not in self.liquidations:
                print(
                    "Liquidation detected:"
                    + f"\t{direction}\t$"
                    + str(liquidation_amount)
                    + f"\t at {datetime.fromtimestamp(l_time)}"
                )
                play_sound()
                self.liquidations.add(liquidation_tuple)

        l_time, l_long, l_short = (
            history.get("t"),
            history.get("l"),
            history.get("s"),
        )
        if l_long > MINIMAL_LIQUIDATION:
            _handle_liquidation(l_long, "long")
        if l_short > MINIMAL_LIQUIDATION:
            _handle_liquidation(l_short, "short")

    def handle_url(self, url: str) -> None:
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
            return

        all_history = response_json[0].get("history", [])
        for history in all_history:
            self.handle_liquidation_set(history)


def main() -> None:
    print("Starting the liquidation detector")

    liquidation_scanner = LiquidationScanner(set())

    while True:

        # print the current time at the bottom of the terminal
        print_there(100, 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        # check for liquidations
        liquidation_scanner.handle_url(URL)

        # sleep for preferred interval
        sleep(SLEEP_INTERVAL)


if __name__ == "__main__":
    main()
