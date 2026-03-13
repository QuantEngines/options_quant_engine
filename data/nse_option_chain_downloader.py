"""
NSE Option Chain Downloader

Hardened version for NSE's silent anti-bot behavior:
- handles HTTP 200 with empty JSON {}
- aggressively refreshes cookies/session
- uses legacy endpoint directly
"""

import json
import random
import time

import pandas as pd
import requests


class NSEOptionChainDownloader:
    HOME_PAGE = "https://www.nseindia.com/"
    OPTION_CHAIN_PAGE = "https://www.nseindia.com/option-chain"
    ALT_OPTION_CHAIN_PAGE = "https://www.nseindia.com/market-data/option-chain"

    LEGACY_INDEX_URL = "https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    LEGACY_STOCK_URL = "https://www.nseindia.com/api/option-chain-equities?symbol={symbol}"

    INDEX_SYMBOLS = {
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "NIFTYNXT50",
    }

    def __init__(self, debug=False):
        self.debug = debug
        self.session = None
        self._new_session()

    def _log(self, *args):
        if self.debug:
            print("[NSE DEBUG]", *args)

    def _base_headers(self, referer=None):
        return {
            "user-agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            ),
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "referer": referer or self.OPTION_CHAIN_PAGE,
            "origin": "https://www.nseindia.com",
            "connection": "keep-alive",
        }

    def _new_session(self):
        if self.session is not None:
            try:
                self.session.close()
            except Exception:
                pass

        self.session = requests.Session()
        self._bootstrap_session()

    def _bootstrap_session(self):
        warmup_urls = [
            self.HOME_PAGE,
            self.OPTION_CHAIN_PAGE,
            self.ALT_OPTION_CHAIN_PAGE,
        ]

        for url in warmup_urls:
            try:
                resp = self.session.get(
                    url,
                    headers=self._base_headers(referer=self.HOME_PAGE),
                    timeout=10
                )
                self._log("bootstrap", url, "status=", resp.status_code)
                time.sleep(0.4)
            except Exception as e:
                self._log("bootstrap_failed", url, str(e))

    def _is_index(self, symbol: str) -> bool:
        return symbol.upper().strip() in self.INDEX_SYMBOLS

    def _request_json_once(self, url: str, referer: str):
        try:
            response = self.session.get(
                url,
                headers=self._base_headers(referer=referer),
                timeout=12
            )

            content_type = response.headers.get("content-type", "")
            text_preview = response.text[:250].replace("\n", " ").replace("\r", " ")

            self._log(
                f"url={url}",
                f"status={response.status_code}",
                f"content_type={content_type}",
                f"preview={text_preview}"
            )

            if response.status_code != 200:
                return None, f"http_{response.status_code}"

            try:
                data = response.json()
            except Exception as e:
                return None, f"json_decode_error:{e}"

            if not isinstance(data, dict):
                return None, "response_not_dict"

            if not data:
                return None, "empty_json_dict"

            return data, None

        except Exception as e:
            return None, str(e)

    def _request_json(self, url: str):
        referers = [
            self.OPTION_CHAIN_PAGE,
            self.ALT_OPTION_CHAIN_PAGE,
            self.HOME_PAGE,
        ]

        last_error = None

        for attempt in range(1, 7):
            referer = referers[(attempt - 1) % len(referers)]

            data, err = self._request_json_once(url, referer=referer)
            if data:
                self._log("json_keys", list(data.keys())[:10])
                return data

            last_error = err
            self._log(f"attempt={attempt}", f"error={err}", "refreshing session")

            self._new_session()
            time.sleep(0.8 + random.uniform(0.2, 0.8))

        self._log("request_failed", f"url={url}", f"last_error={last_error}")
        return {}

    def _get_legacy_chain_json(self, symbol: str) -> dict:
        symbol = symbol.upper().strip()

        if self._is_index(symbol):
            url = self.LEGACY_INDEX_URL.format(symbol=symbol)
        else:
            url = self.LEGACY_STOCK_URL.format(symbol=symbol)

        return self._request_json(url)

    def _extract_rows(self, data: dict) -> list:
        if not isinstance(data, dict):
            return []

        if isinstance(data.get("records"), dict) and isinstance(data["records"].get("data"), list):
            return data["records"]["data"]

        if isinstance(data.get("filtered"), dict) and isinstance(data["filtered"].get("data"), list):
            return data["filtered"]["data"]

        if isinstance(data.get("data"), list):
            return data["data"]

        self._log("row_extraction_failed", f"top_level_keys={list(data.keys())[:15]}")
        try:
            self._log("response_json_preview", json.dumps(data)[:500])
        except Exception:
            pass

        return []

    def _extract_expiry_from_item(self, item: dict):
        expiry = item.get("expiryDate")
        if expiry:
            return expiry

        ce = item.get("CE", {})
        pe = item.get("PE", {})

        if isinstance(ce, dict) and ce.get("expiryDate"):
            return ce.get("expiryDate")

        if isinstance(pe, dict) and pe.get("expiryDate"):
            return pe.get("expiryDate")

        return None

    def _extract_nearest_expiry(self, items: list):
        expiries = []

        for item in items:
            if not isinstance(item, dict):
                continue

            expiry = self._extract_expiry_from_item(item)
            if expiry and expiry not in expiries:
                expiries.append(expiry)

        self._log("detected_expiries", expiries[:10])
        return expiries[0] if expiries else None

    def _rows_to_df(self, items: list, expiry_filter=None) -> pd.DataFrame:
        rows = []

        for item in items:
            if not isinstance(item, dict):
                continue

            strike = item.get("strikePrice")
            item_expiry = self._extract_expiry_from_item(item)

            if expiry_filter is not None and item_expiry != expiry_filter:
                continue

            ce = item.get("CE")
            if isinstance(ce, dict):
                rows.append({
                    "strikePrice": strike,
                    "OPTION_TYP": "CE",
                    "lastPrice": ce.get("lastPrice", 0),
                    "openInterest": ce.get("openInterest", 0),
                    "changeinOI": ce.get("changeinOpenInterest", 0),
                    "impliedVolatility": ce.get("impliedVolatility", 0),
                    "totalTradedVolume": ce.get("totalTradedVolume", 0),
                    "IV": ce.get("impliedVolatility", 0),
                    "VOLUME": ce.get("totalTradedVolume", 0),
                    "OPEN_INT": ce.get("openInterest", 0),
                    "STRIKE_PR": strike,
                    "LAST_PRICE": ce.get("lastPrice", 0),
                    "EXPIRY_DT": ce.get("expiryDate", item_expiry),
                })

            pe = item.get("PE")
            if isinstance(pe, dict):
                rows.append({
                    "strikePrice": strike,
                    "OPTION_TYP": "PE",
                    "lastPrice": pe.get("lastPrice", 0),
                    "openInterest": pe.get("openInterest", 0),
                    "changeinOI": pe.get("changeinOpenInterest", 0),
                    "impliedVolatility": pe.get("impliedVolatility", 0),
                    "totalTradedVolume": pe.get("totalTradedVolume", 0),
                    "IV": pe.get("impliedVolatility", 0),
                    "VOLUME": pe.get("totalTradedVolume", 0),
                    "OPEN_INT": pe.get("openInterest", 0),
                    "STRIKE_PR": strike,
                    "LAST_PRICE": pe.get("lastPrice", 0),
                    "EXPIRY_DT": pe.get("expiryDate", item_expiry),
                })

        df = pd.DataFrame(rows)
        self._log("rows_to_df", f"expiry_filter={expiry_filter}", f"row_count={len(df)}")
        return df

    def fetch_option_chain(self, symbol="NIFTY") -> pd.DataFrame:
        symbol = symbol.upper().strip()

        data = self._get_legacy_chain_json(symbol)
        if not data:
            print("Option chain download error: empty or blocked NSE response")
            return pd.DataFrame()

        items = self._extract_rows(data)
        self._log("raw_item_count", len(items))

        if not items:
            print("Option chain download error: could not fetch option chain rows")
            return pd.DataFrame()

        nearest_expiry = self._extract_nearest_expiry(items)

        if nearest_expiry is not None:
            df = self._rows_to_df(items, expiry_filter=nearest_expiry)
            if not df.empty:
                return df

        df = self._rows_to_df(items, expiry_filter=None)
        if not df.empty:
            return df

        print("Option chain download error: could not build option chain dataframe")
        return pd.DataFrame()