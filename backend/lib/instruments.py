import csv
import io
import logging
from dataclasses import dataclass
from datetime import date, datetime

import httpx

from lib.kotak_client import kotak_client
from lib.settings import settings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OptionContract:
    token: str
    trading_symbol: str
    option_type: str
    strike: int
    expiry: date


class InstrumentRepository:
    def __init__(self) -> None:
        self._contracts: list[OptionContract] = []
        self._loaded_on: date | None = None

    async def active_nifty_contracts(self) -> list[OptionContract]:
        today = datetime.now().date()
        if self._loaded_on != today or not self._contracts:
            await self._refresh(today)
        future_expiries = sorted({contract.expiry for contract in self._contracts if contract.expiry >= today})
        if not future_expiries:
            raise RuntimeError("NIFTY scrip master has no future option expiry")
        expiry = future_expiries[0]
        return [contract for contract in self._contracts if contract.expiry == expiry]

    async def _refresh(self, today: date) -> None:
        response = await kotak_client.authenticated_get(settings.scrip_master_path)
        payload = response.get("data", response)
        paths = payload.get("filesPaths", []) if isinstance(payload, dict) else []
        nse_fo_url = next((path for path in paths if isinstance(path, str) and path.rsplit("/", 1)[-1].startswith("nse_fo")), None)
        if not nse_fo_url:
            raise RuntimeError("Kotak scrip master response did not include nse_fo CSV")
        async with httpx.AsyncClient(timeout=45) as client:
            csv_response = await client.get(nse_fo_url)
            csv_response.raise_for_status()
        contracts: list[OptionContract] = []
        for raw in csv.DictReader(io.StringIO(csv_response.text)):
            row = {key.strip().rstrip(";"): (value or "").strip() for key, value in raw.items() if key}
            if row.get("pSymbolName") != "NIFTY" or row.get("pInstType") != "OPTIDX":
                continue
            option_type = row.get("pOptionType")
            ref = row.get("pScripRefKey", "")
            if option_type not in {"CE", "PE"} or not ref.startswith("NIFTY") or not ref.endswith(option_type) or len(ref) < 15:
                continue
            try:
                expiry = datetime.strptime(ref[5:12].upper(), "%d%b%y").date()
                strike = int(round(float(ref[12:-2])))
            except (ValueError, TypeError):
                continue
            token = row.get("pSymbol", "")
            if token:
                contracts.append(
                    OptionContract(
                        token=token,
                        trading_symbol=row.get("pTrdSymbol", ""),
                        option_type=option_type,
                        strike=strike,
                        expiry=expiry,
                    )
                )
        if not contracts:
            raise RuntimeError("Kotak nse_fo master contained no parseable NIFTY option contracts")
        self._contracts = contracts
        self._loaded_on = today
        logger.info("Loaded %s current NIFTY option contracts", len(contracts))

    async def select_atm_window(self, atm: int, wings: int = 10) -> tuple[list[OptionContract], int]:
        contracts = await self.active_nifty_contracts()
        strikes = sorted({contract.strike for contract in contracts})
        steps = [right - left for left, right in zip(strikes, strikes[1:]) if 0 < right - left <= 500]
        step = min(steps) if steps else 50
        selected = [contract for contract in contracts if abs(contract.strike - atm) <= wings * step]
        return selected, step


instrument_repository = InstrumentRepository()