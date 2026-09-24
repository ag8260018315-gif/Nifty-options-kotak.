import os
from typing import Literal

from pydantic import BaseModel


class NeoSettings(BaseModel):
    mode: Literal["DEMO", "LIVE"] = "DEMO"
    access_token: str = ""
    mobile_number: str = ""
    ucc: str = ""
    mpin: str = ""
    totp_secret: str = ""
    neo_fin_key: str = "neotradeapi"
    vault_key: str = ""
    option_chain_path: str = "/market-data/1.0/watchlist/option-chain"
    nifty_index_token: str = "26000"
    scrip_master_path: str = "/script-details/1.0/masterscrip/file-paths"

    @classmethod
    def from_env(cls) -> "NeoSettings":
        raw_mode = os.environ.get("KOTAK_MODE", "DEMO").upper()
        mode = raw_mode if raw_mode in {"DEMO", "LIVE"} else "DEMO"
        return cls(
            mode=mode,
            access_token=os.environ.get("KOTAK_ACCESS_TOKEN", ""),
            mobile_number=os.environ.get("KOTAK_MOBILE_NUMBER", ""),
            ucc=os.environ.get("KOTAK_UCC", ""),
            mpin=os.environ.get("KOTAK_MPIN", ""),
            totp_secret=os.environ.get("KOTAK_TOTP_SECRET", ""),
            neo_fin_key=os.environ.get("KOTAK_NEO_FIN_KEY", "neotradeapi"),
            vault_key=os.environ.get("KOTAK_VAULT_KEY", ""),
            option_chain_path=os.environ.get("KOTAK_OPTION_CHAIN_PATH", "/market-data/1.0/watchlist/option-chain"),
            nifty_index_token=os.environ.get("KOTAK_NIFTY_INDEX_TOKEN", "26000"),
            scrip_master_path=os.environ.get("KOTAK_SCRIP_MASTER_PATH", "/script-details/1.0/masterscrip/file-paths"),
        )

    @property
    def live_configured(self) -> bool:
        return all(
            [
                self.access_token,
                self.mobile_number,
                self.ucc,
                self.mpin,
                self.totp_secret,
                self.vault_key,
            ]
        )


settings = NeoSettings.from_env()