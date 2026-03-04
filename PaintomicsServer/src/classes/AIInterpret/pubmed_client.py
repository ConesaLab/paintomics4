import threading
import time
import requests
import xml.etree.ElementTree as ET
import logging
import re
from src.conf.serverconf import (
    AI_PUBMED_EMAIL, AI_PUBMED_API_KEY,
    AI_MAX_SECTION_CHARS, AI_EUROPEPMC_DELAY,
)

logger = logging.getLogger(__name__)

# GLOBAL rate limiter — shared across ALL threads
_pubmed_lock = threading.Lock()
_pubmed_last_request = 0.0

# Section classification keywords
_SECTION_KEYWORDS = {
    "introduction": {"introduction", "background"},
    "results": {"result", "finding", "observation"},
    "discussion": {"discussion", "conclusion"},
}
_SKIP_SECTIONS = {"method", "material", "experimental", "supplementary", "supplement", "appendix"}


class PubMedClient:
    ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    IDCONV_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
    PMC_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    EUROPEPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"

    def __init__(self):
        self.rate_limit = 0.11 if AI_PUBMED_API_KEY else 0.34  # 10/s or 3/s

    def _throttle(self):
        global _pubmed_last_request
        with _pubmed_lock:
            elapsed = time.time() - _pubmed_last_request
            if elapsed < self.rate_limit:
                time.sleep(self.rate_limit - elapsed)
            _pubmed_last_request = time.time()

    def _base_params(self):
        params = {"tool": "paintomics4", "email": AI_PUBMED_EMAIL}
        if AI_PUBMED_API_KEY:
            params["api_key"] = AI_PUBMED_API_KEY
        return params

    def search(self, query, max_results=5):
        """ESearch: returns list of PMIDs."""
        self._throttle()
        params = {**self._base_params(), "db": "pubmed", "term": query,
                  "retmax": max_results, "retmode": "json"}
        r = requests.get(self.ESEARCH_URL, params=params, timeout=15)
        r.raise_for_status()
        return r.json().get("esearchresult", {}).get("idlist", [])

    def fetch_abstracts(self, pmids):
        """EFetch: returns list of {pmid, title, abstract, authors, year, journal}."""
        if not pmids:
            return []
        self._throttle()
        params = {**self._base_params(), "db": "pubmed", "id": ",".join(pmids),
                  "retmode": "xml", "rettype": "abstract"}
        r = requests.get(self.EFETCH_URL, params=params, timeout=15)
        r.raise_for_status()
        return self._parse_xml(r.text)

    def _parse_xml(self, xml_text):
        papers = []
        root = ET.fromstring(xml_text)
        for article in root.findall(".//PubmedArticle"):
            pmid = article.findtext(".//PMID", "")
            title = article.findtext(".//ArticleTitle", "")
            abstract_parts = article.findall(".//AbstractText")
            abstract = " ".join(el.text or "" for el in abstract_parts) if abstract_parts else ""
            year = article.findtext(".//PubDate/Year", "")
            journal = article.findtext(".//Journal/Title", "")
            authors_el = article.findall(".//Author")
            first_author = ""
            if authors_el:
                ln = authors_el[0].findtext("LastName", "")
                fn = authors_el[0].findtext("ForeName", "")
                first_author = f"{fn} {ln}".strip()
            papers.append({"pmid": pmid, "title": title, "abstract": abstract or "",
                          "year": year, "journal": journal, "first_author": first_author})
        return papers

    # ------------------------------------------------------------------
    # Multi-tier full-text fetching
    # ------------------------------------------------------------------

    def convert_pmids_to_pmcids(self, pmids):
        """Batch PMID -> PMCID via NCBI ID Converter API. Returns {pmid: pmcid_or_None}."""
        result = {p: None for p in pmids}
        if not pmids:
            return result

        # Batch up to 200 per request
        for i in range(0, len(pmids), 200):
            batch = pmids[i:i + 200]
            self._throttle()
            try:
                r = requests.get(self.IDCONV_URL, params={
                    "tool": "paintomics4", "email": AI_PUBMED_EMAIL,
                    "ids": ",".join(batch), "format": "json",
                }, timeout=15)
                r.raise_for_status()
                data = r.json()
                for rec in data.get("records", []):
                    pmid = rec.get("pmid", "")
                    pmcid = rec.get("pmcid")
                    if pmid and pmcid:
                        result[pmid] = pmcid
            except Exception as e:
                logger.warning(f"PMID->PMCID conversion failed for batch: {e}")
        return result

    def fetch_pmc_full_text(self, pmcid):
        """Fetch full text XML from PMC EFetch, parse into sections. Returns dict or None."""
        self._throttle()
        try:
            params = {**self._base_params(), "db": "pmc", "id": pmcid, "retmode": "xml"}
            r = requests.get(self.PMC_EFETCH_URL, params=params, timeout=30)
            r.raise_for_status()
            return self._parse_pmc_xml(r.text)
        except Exception as e:
            logger.warning(f"PMC full-text fetch failed for {pmcid}: {e}")
            return None

    def _parse_pmc_xml(self, xml_text):
        """Parse PMC JATS XML into sections dict. Returns {section_name: text} or None on failure."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.warning(f"PMC XML parse error: {e}")
            return None

        sections = {}

        # Try to find <body> sections
        body = root.find(".//body")
        if body is None:
            return None

        for sec in body.findall(".//sec"):
            title_el = sec.find("title")
            if title_el is None:
                continue
            title_text = (title_el.text or "").strip().lower()

            # Classify section by title keywords
            section_key = self._classify_section(title_text)
            if section_key is None:
                continue  # skip methods and unrecognized sections

            # Extract all text recursively, strip tags
            text = self._extract_element_text(sec)
            if not text:
                continue

            # Truncate to max chars
            text = text[:AI_MAX_SECTION_CHARS]

            # Merge into existing section (multiple sub-sections may map to same key)
            if section_key in sections:
                remaining = AI_MAX_SECTION_CHARS - len(sections[section_key])
                if remaining > 100:
                    sections[section_key] += "\n\n" + text[:remaining]
            else:
                sections[section_key] = text

        return sections if sections else None

    @staticmethod
    def _classify_section(title_lower):
        """Map a section title to a section key, or None to skip."""
        for skip_kw in _SKIP_SECTIONS:
            if skip_kw in title_lower:
                return None
        for key, keywords in _SECTION_KEYWORDS.items():
            for kw in keywords:
                if kw in title_lower:
                    return key
        return None  # unrecognized → skip

    @staticmethod
    def _extract_element_text(element):
        """Recursively join all text content from an XML element, stripping tags."""
        parts = []
        for text in element.itertext():
            stripped = text.strip()
            if stripped:
                parts.append(stripped)
        return " ".join(parts)

    def fetch_europepmc_full_text(self, pmid):
        """Tier 2 fallback: fetch full text XML from Europe PMC. Returns sections dict or None."""
        time.sleep(AI_EUROPEPMC_DELAY)
        try:
            url = f"{self.EUROPEPMC_URL}/{pmid}/fullTextXML"
            r = requests.get(url, timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return self._parse_pmc_xml(r.text)
        except Exception as e:
            logger.warning(f"Europe PMC full-text fetch failed for PMID {pmid}: {e}")
            return None

    def fetch_papers(self, pmids):
        """Multi-tier paper fetching: abstracts + full text (PMC -> Europe PMC -> abstract only).

        Returns list of enhanced paper dicts with sections and metadata.
        """
        if not pmids:
            return []

        # Step 1: Fetch base metadata via PubMed abstracts
        base_papers = self.fetch_abstracts(pmids)
        if not base_papers:
            return []

        # Build pmid -> paper lookup
        paper_map = {}
        for p in base_papers:
            p["pmcid"] = None
            p["full_text_available"] = False
            p["fetch_tier"] = "abstract_only"
            p["sections"] = {"abstract": p.get("abstract", "")}
            p["full_text_char_count"] = len(p.get("abstract", ""))
            p["authors_short"] = _format_authors_short(p.get("first_author", ""))
            p["pathways"] = []
            paper_map[p["pmid"]] = p

        # Step 2: Batch convert PMIDs to PMCIDs
        pmcid_map = self.convert_pmids_to_pmcids(pmids)

        # Step 3: Try to fetch full text for each paper
        for pmid, paper in paper_map.items():
            pmcid = pmcid_map.get(pmid)
            if pmcid:
                paper["pmcid"] = pmcid

            # Tier 1: PMC EFetch
            if pmcid:
                sections = self.fetch_pmc_full_text(pmcid)
                if sections:
                    paper["sections"].update(sections)
                    paper["full_text_available"] = True
                    paper["fetch_tier"] = "pmc"
                    paper["full_text_char_count"] = sum(len(v) for v in paper["sections"].values())
                    continue

            # Tier 2: Europe PMC
            sections = self.fetch_europepmc_full_text(pmid)
            if sections:
                paper["sections"].update(sections)
                paper["full_text_available"] = True
                paper["fetch_tier"] = "europepmc"
                paper["full_text_char_count"] = sum(len(v) for v in paper["sections"].values())
                continue

            # Tier 3: abstract only (already set as default)

        return list(paper_map.values())


def _format_authors_short(first_author):
    """'John Smith' -> 'Smith, J. et al.' or pass-through on failure."""
    if not first_author:
        return "Unknown"
    parts = first_author.strip().split()
    if len(parts) >= 2:
        last = parts[-1]
        initials = ".".join(p[0].upper() for p in parts[:-1] if p) + "."
        return f"{last}, {initials} et al."
    return f"{first_author} et al."
