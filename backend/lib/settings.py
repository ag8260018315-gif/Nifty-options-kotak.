import os
from typing import Literal

from pydantic import BaseModel


class NeoSettings(BaseModel):
    mode: Literal["DEMO", "LIVE"] = "DEMO"
    consumer_key: str = ""
    consumer_secret: str = ""
    mobile: str = ""
    mpin: str = ""
    totp_secret: str = ""

    @classmethod
    def from_env(cls) -> "NeoSettings":
        raw_mode = os.environ.get("KOTAK_MODE", "DEMO").upper()
        mode = raw_mode if raw_mode in {"DEMO", "LIVE"} else "DEMO"
        return cls(
            mode=mode,
            consumer_key=os.environ.get("KOTAK_CONSUMER_KEY", ""),
            consumer_secret=os.environ.get("KOTAK_CONSUMER_SECRET", ""),
            mobile=os.environ.get("KOTAK_MOBILE", ""),
            mpin=os.environ.get("KOTAK_MPIN", ""),
            totp_secret=os.environ.get("KOTAK_TOTP_SECRET", ""),
        )

    @property
    def live_configured(self) -> bool:
        return all(
            [
                self.consumer_key,
                self.consumer_secret,
                self.mobile,
                self.mpin,
                self.totp_secret,
            ]
        )


settings = NeoSettings.from_env()