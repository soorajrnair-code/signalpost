"""
Client for the Norwegian Business Registry (Brønnøysundregistrene - BRREG) Open REST API.
API Documentation: https://data.brreg.no/enhetsregisteret/api/dokumentasjon
Open Data License: NLOD 2.0 (Free, no API key required)
"""

import time
import json
import logging
from typing import Optional, Dict, Any, List
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("signalpost.registry")

BASE_URL = "https://data.brreg.no/enhetsregisteret/api"
USER_AGENT = "SignalPost-Agent/1.0 (+https://github.com/signalpost-ai/signalpost-agent)"


class BRREGClient:
    def __init__(self, timeout: float = 12.0, max_retries: int = 3):
        self.base_url = BASE_URL
        self.timeout = timeout
        self.session = requests.Session()
        
        retries = Retry(
            total=max_retries,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            raise_on_status=False
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=20)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json"
        })
        self._cache: Dict[str, Any] = {}

    def get_enhet(self, orgnr: str) -> Optional[Dict[str, Any]]:
        """
        Fetches the primary entity data for a given 9-digit Norwegian organization number.
        Returns None if not found (404).
        """
        cache_key = f"enhet:{orgnr}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        url = f"{self.base_url}/enheter/{orgnr}"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                self._cache[cache_key] = data
                return data
            elif resp.status_code == 404:
                logger.info(f"Entity not found in BRREG for orgnr: {orgnr}")
                return None
            elif resp.status_code == 410:
                # Slettet enhet (deleted entity)
                data = resp.json() if resp.content else {"slettet": True, "organisasjonsnummer": orgnr}
                self._cache[cache_key] = data
                return data
            else:
                resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP error fetching enhet {orgnr}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error connecting to BRREG API for {orgnr}: {e}")
            raise
        return None

    def get_roller(self, orgnr: str) -> Optional[Dict[str, Any]]:
        """
        Fetches management, board, and auditor roles for an entity.
        """
        cache_key = f"roller:{orgnr}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        url = f"{self.base_url}/enheter/{orgnr}/roller"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                self._cache[cache_key] = data
                return data
            elif resp.status_code in (404, 204):
                return None
            else:
                resp.raise_for_status()
        except Exception as e:
            logger.debug(f"Could not fetch roller for {orgnr}: {e}")
            return None
        return None

    def get_underenheter(self, orgnr: str, size: int = 15) -> List[Dict[str, Any]]:
        """
        Fetches sub-entities (underenheter/avdelinger) affiliated with the parent organization.
        """
        cache_key = f"underenheter:{orgnr}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        url = f"{self.base_url}/underenheter"
        params = {"overordnetEnhet": orgnr, "size": size}
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("_embedded", {}).get("underenheter", [])
                self._cache[cache_key] = items
                return items
        except Exception as e:
            logger.debug(f"Could not fetch underenheter for {orgnr}: {e}")
        return []

    def search_by_name(self, name: str, size: int = 5) -> List[Dict[str, Any]]:
        """
        Searches BRREG by company name. Used for disambiguation when name is provided instead of orgnr.
        """
        url = f"{self.base_url}/enheter"
        params = {"navn": name, "size": size}
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("_embedded", {}).get("enheter", [])
        except Exception as e:
            logger.warning(f"Error searching enheter by name '{name}': {e}")
        return []
