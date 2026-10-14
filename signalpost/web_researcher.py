"""
Web Intelligence & First-Party Scraping for Norwegian Companies.
Extracts live website presence, meta descriptions, contact info, and social links.
"""

import re
import logging
from typing import Dict, Any, Optional, Set
import requests

logger = logging.getLogger("signalpost.web")

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
URL_CLEAN_REGEX = re.compile(r'^(?:https?:\/\/)?(?:www\.)?', re.IGNORECASE)


def normalize_website_url(raw_url: str) -> Optional[str]:
    """Ensures valid http/https protocol prefix."""
    if not raw_url:
        return None
    url = raw_url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url


class WebResearcher:
    def __init__(self, timeout: float = 6.0):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        })

    def fetch_company_web_presence(self, website_url: str) -> Dict[str, Any]:
        """
        Fetches first-party company homepage and extracts metadata and contacts.
        """
        normalized_url = normalize_website_url(website_url)
        if not normalized_url:
            return {"status": "no_website_provided"}

        result: Dict[str, Any] = {
            "source_url": normalized_url,
            "status": "unreachable",
            "title": "",
            "meta_description": "",
            "contact_emails": [],
            "social_links": {},
            "raw_snippet": ""
        }

        try:
            resp = self.session.get(normalized_url, timeout=self.timeout, allow_redirects=True)
            if resp.status_code == 200:
                result["status"] = "reachable"
                html = resp.text
                
                # Title
                title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
                if title_match:
                    result["title"] = " ".join(title_match.group(1).split()).strip()

                # Meta Description
                meta_match = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE | re.DOTALL)
                if not meta_match:
                    meta_match = re.search(r'<meta[^>]*property=["\']og:description["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE | re.DOTALL)
                if meta_match:
                    result["meta_description"] = " ".join(meta_match.group(1).split()).strip()

                # Extract emails
                found_emails: Set[str] = set(EMAIL_REGEX.findall(html))
                valid_emails = [
                    e for e in found_emails 
                    if not any(ext in e.lower() for ext in [".png", ".jpg", ".webp", ".svg", ".js", ".css"])
                ]
                result["contact_emails"] = sorted(list(valid_emails))[:5]

                # Extract Social Links
                social_patterns = {
                    "linkedin": r'https?:\/\/(?:www\.)?linkedin\.com\/(?:company|in)\/[a-zA-Z0-9_\-\.\/]+',
                    "twitter": r'https?:\/\/(?:www\.)?(?:twitter|x)\.com\/[a-zA-Z0-9_]+',
                    "github": r'https?:\/\/(?:www\.)?github\.com\/[a-zA-Z0-9_\-]+',
                    "facebook": r'https?:\/\/(?:www\.)?facebook\.com\/[a-zA-Z0-9_\-\.]+',
                    "instagram": r'https?:\/\/(?:www\.)?instagram\.com\/[a-zA-Z0-9_\-\.]+'
                }
                for platform, pattern in social_patterns.items():
                    sm = re.search(pattern, html, re.IGNORECASE)
                    if sm:
                        result["social_links"][platform] = sm.group(0)

                # Body text summary snippet
                text_clean = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
                text_clean = re.sub(r'<style[^>]*>.*?</style>', ' ', text_clean, flags=re.DOTALL | re.IGNORECASE)
                text_clean = re.sub(r'<[^>]+>', ' ', text_clean)
                tokens = " ".join(text_clean.split())
                result["raw_snippet"] = tokens[:600]

        except requests.exceptions.RequestException as e:
            logger.debug(f"Failed to fetch website {normalized_url}: {e}")
            result["status"] = "failed_or_timeout"
        except Exception as e:
            logger.debug(f"Unexpected error parsing website {normalized_url}: {e}")
            result["status"] = "parsing_error"

        return result
