"""
ICICI Breeze Option Chain Loader

SDK-based version only.
- Uses breeze.get_option_chain_quotes(...)
- Tries configured expiry candidates one by one
- Normalizes data into the engine's standard option-chain format
- Protects against the local `config` package colliding with Breeze SDK imports
"""

import importlib
import json
import sys
from pathlib import Path

import pandas as pd

from config.settings import (
    ICICI_BREEZE_API_KEY,
    ICICI_BREEZE_SECRET_KEY,
    ICICI_BREEZE_SESSION_TOKEN,
    ICICI_SYMBOL_EXPIRY_CANDIDATES,
    ICICI_DEFAULT_EXPIRY_DATE,
    ICICI_DEBUG,
)


def _load_breeze_connect_class():
    """
    Lazily import BreezeConnect while shielding the import from this project's
    local `config` package collision.
    """
    project_root = str(Path(__file__).resolve().parents[1])

    original_sys_path = list(sys.path)
    original_config_module = sys.modules.get("config")

    try:
        filtered_path = []
        for p in sys.path:
            normalized = str(Path(p).resolve()) if p not in ("", ".") else project_root
            if normalized == project_root:
                continue
            filtered_path.append(p)

        sys.path = filtered_path

        if "config" in sys.modules:
            del sys.modules["config"]

        breeze_module = importlib.import_module("breeze_connect")
        return getattr(breeze_module, "BreezeConnect", None)

    finally:
        sys.path = original_sys_path

        if original_config_module is not None:
            sys.modules["config"] = original_config_module


class ICICIBreezeOptionChain:
    def __init__(self, debug=None):
        self.debug = ICICI_DEBUG if debug is None else debug
        self.breeze = None
        self._init_client()

    def _log(self, *args):
        if self.debug:
            print("[ICICI DEBUG]", *args)

    def _init_client(self):
        BreezeConnect = _load_breeze_connect_class()

        if BreezeConnect is None:
            raise ImportError(
                "breeze-connect is not installed correctly. Run: pip install --upgrade breeze-connect"
            )

        if not ICICI_BREEZE_API_KEY or str(ICICI_BREEZE_API_KEY).startswith("YOUR_"):
            raise ValueError("ICICI_BREEZE_API_KEY is not configured in settings.py")

        if not ICICI_BREEZE_SECRET_KEY or str(ICICI_BREEZE_SECRET_KEY).startswith("YOUR_"):
            raise ValueError("ICICI_BREEZE_SECRET_KEY is not configured in settings.py")

        if not ICICI_BREEZE_SESSION_TOKEN or str(ICICI_BREEZE_SESSION_TOKEN).startswith("YOUR_"):
            raise ValueError("ICICI_BREEZE_SESSION_TOKEN is not configured in settings.py")

        self.breeze = BreezeConnect(api_key=ICICI_BREEZE_API_KEY)
        self.breeze.generate_session(
            api_secret=ICICI_BREEZE_SECRET_KEY,
            session_token=str(ICICI_BREEZE_SESSION_TOKEN)
        )
        self._log("Breeze session initialized")

    def _resolve_expiry_candidates(self, symbol: str):
        symbol = symbol.upper().strip()

        candidates = ICICI_SYMBOL_EXPIRY_CANDIDATES.get(symbol, [])
        cleaned = []

        for expiry in candidates:
            if expiry and expiry not in cleaned:
                cleaned.append(expiry)

        if not cleaned:
            cleaned = [ICICI_DEFAULT_EXPIRY_DATE]

        self._log("resolved_expiry_candidates", f"symbol={symbol}", f"candidates={cleaned}")
        return cleaned

    def _preview_response(self, response, label):
        if not self.debug:
            return

        try:
            if isinstance(response, dict):
                keys = list(response.keys())
                preview = json.dumps(response)[:800]
                self._log(f"{label}_keys", keys)
                self._log(f"{label}_preview", preview)
            else:
                self._log(f"{label}_type", type(response).__name__)
                self._log(f"{label}_preview", str(response)[:800])
        except Exception as e:
            self._log(f"{label}_preview_failed", str(e))

    def _extract_success_rows(self, response, label="resp"):
        self._preview_response(response, label)

        if response is None:
            return []

        if isinstance(response, dict):
            success = response.get("Success")
            if isinstance(success, list):
                return success

            if isinstance(response.get("success"), list):
                return response.get("success")

            for key in ["Error", "error", "Status", "status", "message", "Message"]:
                if key in response:
                    self._log(f"{label}_{key}", response.get(key))

        return []

    def _normalize_side(self, side: str) -> str:
        side = str(side).strip().lower()
        if side == "call":
            return "CE"
        if side == "put":
            return "PE"
        if side == "ce":
            return "CE"
        if side == "pe":
            return "PE"
        return side.upper()

    def _safe_float(self, value, default=0.0):
        try:
            if value in [None, ""]:
                return default
            return float(value)
        except Exception:
            return default

    def _normalize_rows(self, rows):
        normalized = []

        for row in rows:
            try:
                strike = row.get("strike_price", row.get("strike"))
                option_typ = self._normalize_side(
                    row.get("right", row.get("option_type", ""))
                )

                if strike in [None, ""] or option_typ not in ["CE", "PE"]:
                    continue

                ltp = row.get("ltp", row.get("last_traded_price", row.get("lastPrice", 0)))
                oi = row.get("open_interest", row.get("openInterest", 0))
                chg_oi = row.get("chnge_oi", row.get("changeinOI", row.get("change_in_oi", 0)))
                iv = row.get("implied_volatility", row.get("iv", row.get("impliedVolatility", 0)))
                volume = row.get(
                    "total_quantity_traded",
                    row.get("total_traded_volume", row.get("totalTradedVolume", 0))
                )
                expiry_dt = row.get("expiry_date", row.get("expiryDate"))

                strike_val = self._safe_float(strike, None)
                if strike_val is None:
                    continue

                ltp_val = self._safe_float(ltp, 0.0)
                oi_val = self._safe_float(oi, 0.0)
                chg_oi_val = self._safe_float(chg_oi, 0.0)
                iv_val = self._safe_float(iv, 0.0)
                volume_val = self._safe_float(volume, 0.0)

                normalized.append({
                    "strikePrice": strike_val,
                    "OPTION_TYP": option_typ,
                    "lastPrice": ltp_val,
                    "openInterest": oi_val,
                    "changeinOI": chg_oi_val,
                    "impliedVolatility": iv_val,
                    "totalTradedVolume": volume_val,
                    "IV": iv_val,
                    "VOLUME": volume_val,
                    "OPEN_INT": oi_val,
                    "STRIKE_PR": strike_val,
                    "LAST_PRICE": ltp_val,
                    "EXPIRY_DT": expiry_dt,
                })
            except Exception as e:
                self._log("row_normalization_failed", str(e), row)

        df = pd.DataFrame(normalized)
        if not df.empty:
            df = df.dropna(subset=["strikePrice"])
            df = df.sort_values(["strikePrice", "OPTION_TYP"]).reset_index(drop=True)
        return df

    def _fetch_for_expiry(self, symbol: str, expiry_date: str):
        self._log("fetching option chain", f"symbol={symbol}", f"expiry={expiry_date}")

        call_resp = self.breeze.get_option_chain_quotes(
            stock_code=symbol,
            exchange_code="NFO",
            product_type="options",
            expiry_date=expiry_date,
            right="call",
            strike_price="",
        )

        put_resp = self.breeze.get_option_chain_quotes(
            stock_code=symbol,
            exchange_code="NFO",
            product_type="options",
            expiry_date=expiry_date,
            right="put",
            strike_price="",
        )

        call_rows = self._extract_success_rows(call_resp, label=f"call_{expiry_date}")
        put_rows = self._extract_success_rows(put_resp, label=f"put_{expiry_date}")

        self._log(
            "expiry_result",
            expiry_date,
            f"call_rows={len(call_rows)}",
            f"put_rows={len(put_rows)}"
        )

        all_rows = call_rows + put_rows
        if not all_rows:
            return pd.DataFrame()

        df = self._normalize_rows(all_rows)
        self._log("normalized_rows", len(df), f"expiry={expiry_date}")
        return df

    def fetch_option_chain(self, symbol="NIFTY"):
        symbol = symbol.upper().strip()
        expiry_candidates = self._resolve_expiry_candidates(symbol)

        last_errors = []

        for expiry_date in expiry_candidates:
            try:
                df = self._fetch_for_expiry(symbol=symbol, expiry_date=expiry_date)
                if df is not None and not df.empty:
                    self._log("selected_expiry", expiry_date, f"rows={len(df)}")
                    return df
                last_errors.append(f"{expiry_date}:no_data")
            except Exception as e:
                self._log("expiry_fetch_exception", expiry_date, str(e))
                last_errors.append(f"{expiry_date}:{e}")

        self._log("all_expiry_attempts_failed", last_errors)
        print("Option chain download error: ICICI returned no option chain rows for any configured expiry")
        return pd.DataFrame()

    def close(self):
        return