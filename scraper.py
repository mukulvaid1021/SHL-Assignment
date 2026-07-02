# scraper.py
import requests
from bs4 import BeautifulSoup
import json
import time
import re
from typing import List, Dict, Optional
from models import CatalogItem
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "https://www.shl.com"
CATALOG_URL = f"{BASE_URL}/solutions/products/product-catalog/"


def scrape_catalog() -> List[Dict]:
    """Scrape the SHL product catalog for Individual Test Solutions."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })

    all_items = []

    # The catalog uses pagination and filtering
    # We need to scrape Individual Test Solutions
    page = 1
    max_pages = 40  # Safety limit

    while page <= max_pages:
        try:
            # The SHL catalog uses AJAX/pagination - try multiple approaches
            params = {
                "start": (page - 1) * 12,
                "type": "",
            }

            url = CATALOG_URL
            if page > 1:
                url = f"{CATALOG_URL}?start={params['start']}"

            logger.info(f"Scraping page {page}: {url}")
            response = session.get(url, timeout=30)

            if response.status_code != 200:
                logger.warning(f"Got status {response.status_code} for page {page}")
                break

            soup = BeautifulSoup(response.text, "html.parser")

            # Find assessment cards/rows in the catalog table
            items_found = parse_catalog_page(soup, session)

            if not items_found:
                logger.info(f"No items found on page {page}, stopping.")
                break

            all_items.extend(items_found)
            logger.info(f"Found {len(items_found)} items on page {page}, total: {len(all_items)}")

            page += 1
            time.sleep(1)  # Be respectful

        except Exception as e:
            logger.error(f"Error scraping page {page}: {e}")
            break

    # Deduplicate by URL
    seen_urls = set()
    unique_items = []
    for item in all_items:
        if item["url"] not in seen_urls:
            seen_urls.add(item["url"])
            unique_items.append(item)

    return unique_items


def parse_catalog_page(soup: BeautifulSoup, session: requests.Session) -> List[Dict]:
    """Parse a single catalog page and extract assessment items."""
    items = []

    # Look for table rows with assessment data
    # SHL catalog typically uses a table format
    table = soup.find("table", class_=re.compile(r"custom__table|catalog", re.I))
    if table:
        rows = table.find_all("tr")[1:]  # Skip header
        for row in rows:
            item = parse_table_row(row)
            if item:
                items.append(item)
        return items

    # Alternative: look for product cards/links
    # Try finding divs or links that contain product info
    product_links = soup.find_all("a", href=re.compile(r"/solutions/products/"))
    for link in product_links:
        href = link.get("href", "")
        if "product-catalog" in href and href == "/solutions/products/product-catalog/":
            continue
        name = link.get_text(strip=True)
        if name and len(name) > 2:
            full_url = href if href.startswith("http") else BASE_URL + href
            items.append({
                "name": name,
                "url": full_url,
                "test_type": "",
                "description": "",
            })

    # Also try parsing the structured data from the page
    # SHL uses specific class names for their catalog entries
    entries = soup.find_all("div", class_=re.compile(r"product|assessment|catalog-item", re.I))
    for entry in entries:
        item = parse_product_entry(entry)
        if item:
            items.append(item)

    return items


def parse_table_row(row) -> Optional[Dict]:
    """Parse a table row from the SHL catalog."""
    cells = row.find_all("td")
    if len(cells) < 2:
        return None

    # First cell usually has the name and link
    link = cells[0].find("a")
    if not link:
        return None

    name = link.get_text(strip=True)
    href = link.get("href", "")
    url = href if href.startswith("http") else BASE_URL + href

    # Determine test type from icons or text in other cells
    test_type = ""
    remote = ""
    adaptive = ""

    for i, cell in enumerate(cells):
        cell_text = cell.get_text(strip=True).lower()
        # Check for test type indicators
        if i == 1:  # Usually remote testing column
            remote = "Yes" if cell.find("span", class_=re.compile("catalogue__circle--yes")) else "No"
        if i == 2:  # Usually adaptive/IRT column
            adaptive = "Yes" if cell.find("span", class_=re.compile("catalogue__circle--yes")) else "No"
        if i == 3:  # Test type column
            test_type_span = cell.find("span", class_=re.compile("product-catalogue__key"))
            if test_type_span:
                test_type = test_type_span.get_text(strip=True)

    # Extract test type from the row
    type_spans = row.find_all("span", class_=re.compile(r"product-catalogue__key|catalogue__key"))
    if type_spans:
        test_type = type_spans[0].get_text(strip=True)

    # Check for icons/images indicating type
    if not test_type:
        all_text = row.get_text(strip=True).lower()
        test_type = infer_test_type(name, all_text)

    return {
        "name": name,
        "url": url,
        "test_type": test_type,
        "remote_testing": remote,
        "adaptive_testing": adaptive,
        "description": "",
    }


def parse_product_entry(entry) -> Optional[Dict]:
    """Parse a product entry div."""
    link = entry.find("a")
    if not link:
        return None

    name = link.get_text(strip=True)
    href = link.get("href", "")
    url = href if href.startswith("http") else BASE_URL + href

    description = ""
    desc_elem = entry.find("p") or entry.find("div", class_=re.compile(r"desc|detail", re.I))
    if desc_elem:
        description = desc_elem.get_text(strip=True)

    return {
        "name": name,
        "url": url,
        "test_type": infer_test_type(name, description),
        "description": description,
    }


def scrape_product_detail(url: str, session: requests.Session) -> Dict:
    """Scrape additional details from a product's detail page."""
    try:
        response = session.get(url, timeout=15)
        if response.status_code != 200:
            return {}

        soup = BeautifulSoup(response.text, "html.parser")

        description = ""
        # Look for description sections
        desc_section = soup.find("div", class_=re.compile(r"product-detail|description|content", re.I))
        if desc_section:
            description = desc_section.get_text(strip=True)[:1000]

        # Look for metadata
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc:
            description = description or meta_desc.get("content", "")

        return {"description": description}

    except Exception as e:
        logger.warning(f"Error scraping detail page {url}: {e}")
        return {}


def infer_test_type(name: str, text: str = "") -> str:
    """Infer test type from name and text."""
    combined = (name + " " + text).lower()

    # Knowledge/Technical tests
    knowledge_keywords = [
        "java", "python", "c#", "c++", ".net", "sql", "javascript", "html", "css",
        "angular", "react", "node", "php", "ruby", "swift", "kotlin", "scala",
        "hadoop", "spark", "aws", "azure", "devops", "linux", "unix", "windows",
        "networking", "database", "oracle", "sap", "salesforce", "agile", "scrum",
        "accounting", "bookkeeping", "financial", "typing", "data entry",
        "microsoft", "excel", "word", "powerpoint", "outlook", "office",
        "drupal", "wordpress", "magento", "r programming",
        "selenium", "testing", "qa", "quality", "manual testing",
        "autocad", "solidworks", "engineering",
    ]
    if any(kw in combined for kw in knowledge_keywords):
        return "K"

    # Personality assessments
    personality_keywords = [
        "opq", "personality", "motivation", "mbq", "occupational",
        "preference", "trait", "character",
    ]
    if any(kw in combined for kw in personality_keywords):
        return "P"

    # Ability/Cognitive tests
    ability_keywords = [
        "verify", "numerical", "verbal", "inductive", "deductive", "logical",
        "reasoning", "cognitive", "ability", "aptitude", "checking",
        "mechanical", "spatial", "abstract", "critical thinking",
        "general ability", "g+", "gat", "calculation",
    ]
    if any(kw in combined for kw in ability_keywords):
        return "A"

    # Behavioral/Situational
    behavior_keywords = [
        "sjt", "situational", "judgment", "scenarios", "behavioral",
        "simulation", "inbox", "in-tray", "role-play",
    ]
    if any(kw in combined for kw in behavior_keywords):
        return "B"

    # Skills
    skills_keywords = [
        "skill", "proficiency", "competency", "communication",
        "leadership", "management", "customer service",
    ]
    if any(kw in combined for kw in skills_keywords):
        return "S"

    return "K"  # Default


def build_full_catalog():
    """Build the complete catalog with details."""
    # First try scraping
    items = scrape_catalog()

    if len(items) < 10:
        logger.warning(f"Only scraped {len(items)} items. Loading from hardcoded catalog.")
        items = get_hardcoded_catalog()

    # Save to file
    with open("catalog_data.json", "w") as f:
        json.dump(items, f, indent=2)

    logger.info(f"Catalog built with {len(items)} items")
    return items


def get_hardcoded_catalog() -> List[Dict]:
    """
    Hardcoded catalog data from SHL's Individual Test Solutions.
    This is a fallback if scraping fails, built from manual review of the catalog.
    """
    catalog = [
        # === ABILITY / COGNITIVE TESTS ===
        {
            "name": "Verify - Numerical Ability",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/verify-numerical-ability/",
            "test_type": "A",
            "description": "Measures ability to make correct decisions from numerical data. Suitable for roles requiring numerical analysis and data interpretation. Adaptive, timed assessment.",
            "remote_testing": "Yes",
            "adaptive_testing": "Yes",
            "duration": "17 minutes",
            "categories": ["cognitive", "numerical", "ability"],
            "keywords": ["numbers", "data analysis", "calculations", "statistics", "finance", "analytical"]
        },
        {
            "name": "Verify - Verbal Ability",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/verify-verbal-ability/",
            "test_type": "A",
            "description": "Measures ability to evaluate logic of arguments in written passages. For roles requiring comprehension of written information and verbal reasoning.",
            "remote_testing": "Yes",
            "adaptive_testing": "Yes",
            "duration": "17 minutes",
            "categories": ["cognitive", "verbal", "ability"],
            "keywords": ["reading", "comprehension", "language", "communication", "writing", "analytical"]
        },
        {
            "name": "Verify - Inductive Reasoning",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/verify-inductive-reasoning/",
            "test_type": "A",
            "description": "Measures ability to draw inferences and identify patterns. Suitable for roles requiring conceptual and analytical thinking.",
            "remote_testing": "Yes",
            "adaptive_testing": "Yes",
            "duration": "24 minutes",
            "categories": ["cognitive", "reasoning", "ability"],
            "keywords": ["pattern recognition", "logic", "problem solving", "abstract", "analytical"]
        },
        {
            "name": "Verify - Deductive Reasoning",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/verify-deductive-reasoning/",
            "test_type": "A",
            "description": "Measures the ability to draw logical conclusions from information provided, identify strengths and weaknesses of arguments.",
            "remote_testing": "Yes",
            "adaptive_testing": "Yes",
            "duration": "20 minutes",
            "categories": ["cognitive", "reasoning", "ability"],
            "keywords": ["logic", "conclusions", "arguments", "analytical", "critical thinking"]
        },
        {
            "name": "Verify - Checking",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/verify-checking/",
            "test_type": "A",
            "description": "Measures the ability to check and compare information quickly and accurately. For clerical, administrative, and data-entry roles.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "8 minutes",
            "categories": ["cognitive", "checking", "ability"],
            "keywords": ["accuracy", "attention to detail", "clerical", "administrative", "data entry"]
        },
        {
            "name": "Verify - Calculation",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/verify-calculation/",
            "test_type": "A",
            "description": "Measures basic calculation skills including addition, subtraction, multiplication, division, percentages, and fractions.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "10 minutes",
            "categories": ["cognitive", "numerical", "ability"],
            "keywords": ["math", "arithmetic", "calculation", "basic numeracy"]
        },
        {
            "name": "General Ability Test (GAT)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/general-ability-test/",
            "test_type": "A",
            "description": "General cognitive ability assessment that combines verbal, numerical, and abstract reasoning. For screening large applicant pools.",
            "remote_testing": "Yes",
            "adaptive_testing": "Yes",
            "duration": "36 minutes",
            "categories": ["cognitive", "general ability"],
            "keywords": ["general intelligence", "cognitive", "screening", "g-factor", "graduate", "entry level"]
        },
        {
            "name": "Verify - Numerical Reasoning",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/verify-numerical-reasoning/",
            "test_type": "A",
            "description": "Advanced numerical reasoning test for interpreting complex data from charts, graphs and tables.",
            "remote_testing": "Yes",
            "adaptive_testing": "Yes",
            "duration": "18 minutes",
            "categories": ["cognitive", "numerical", "reasoning"],
            "keywords": ["data interpretation", "charts", "graphs", "analysis", "senior", "management"]
        },
        {
            "name": "Verify - Verbal Reasoning",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/verify-verbal-reasoning/",
            "test_type": "A",
            "description": "Advanced verbal reasoning for evaluating complex written information and making logical inferences.",
            "remote_testing": "Yes",
            "adaptive_testing": "Yes",
            "duration": "19 minutes",
            "categories": ["cognitive", "verbal", "reasoning"],
            "keywords": ["critical analysis", "written communication", "comprehension", "senior", "management"]
        },
        {
            "name": "Verify - Mechanical Comprehension",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/verify-mechanical-comprehension/",
            "test_type": "A",
            "description": "Measures understanding of mechanical concepts and physical principles. For engineering, technical, and manufacturing roles.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["cognitive", "mechanical", "ability"],
            "keywords": ["mechanical", "physics", "engineering", "technical", "manufacturing", "maintenance"]
        },
        {
            "name": "Verify G+ Cognitive Ability Assessment",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/verify-g-plus/",
            "test_type": "A",
            "description": "Next-generation adaptive cognitive ability test covering numerical, verbal, deductive and inductive reasoning in a single assessment.",
            "remote_testing": "Yes",
            "adaptive_testing": "Yes",
            "duration": "36 minutes",
            "categories": ["cognitive", "general ability"],
            "keywords": ["cognitive", "adaptive", "general ability", "reasoning", "graduate", "professional"]
        },
        {
            "name": "Numerical Reasoning Test (Interactive)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/numerical-reasoning-test-interactive/",
            "test_type": "A",
            "description": "Interactive numerical reasoning assessment using realistic workplace scenarios with dynamic data.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "18 minutes",
            "categories": ["cognitive", "numerical", "interactive"],
            "keywords": ["numerical", "interactive", "workplace", "data interpretation"]
        },
        {
            "name": "Verbal Reasoning Test (Interactive)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/verbal-reasoning-test-interactive/",
            "test_type": "A",
            "description": "Interactive verbal reasoning assessment using realistic workplace scenarios.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "19 minutes",
            "categories": ["cognitive", "verbal", "interactive"],
            "keywords": ["verbal", "interactive", "workplace", "comprehension"]
        },

        # === PERSONALITY ASSESSMENTS ===
        {
            "name": "OPQ32r",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/opq32r/",
            "test_type": "P",
            "description": "Occupational Personality Questionnaire - measures 32 personality characteristics relevant to workplace behavior. For selection, development, and team building.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "25-40 minutes",
            "categories": ["personality", "occupational"],
            "keywords": ["personality", "workplace behavior", "leadership", "teamwork", "management", "interpersonal", "communication style", "stakeholder management"]
        },
        {
            "name": "OPQ32r - Short Version",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/opq32r-short/",
            "test_type": "P",
            "description": "Shorter version of OPQ32r measuring core personality dimensions for workplace performance prediction.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "15-20 minutes",
            "categories": ["personality", "occupational"],
            "keywords": ["personality", "quick", "screening", "workplace behavior"]
        },
        {
            "name": "Motivation Questionnaire (MQ)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/motivation-questionnaire/",
            "test_type": "P",
            "description": "Measures factors that increase and decrease motivation at work. Assesses 18 dimensions of motivation including achievement, recognition, and autonomy.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "25 minutes",
            "categories": ["personality", "motivation"],
            "keywords": ["motivation", "engagement", "job satisfaction", "drive", "retention", "culture fit"]
        },
        {
            "name": "CCSQ - Customer Contact Styles Questionnaire",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/ccsq/",
            "test_type": "P",
            "description": "Personality questionnaire designed for customer-facing roles. Measures traits relevant to customer service performance.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["personality", "customer service"],
            "keywords": ["customer service", "sales", "client facing", "interpersonal", "communication", "call center", "retail"]
        },
        {
            "name": "MBQ - Management and Leadership Questionnaire",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/mbq/",
            "test_type": "P",
            "description": "Personality questionnaire specifically for management and leadership roles. Measures leadership styles, transformational and transactional dimensions.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "25 minutes",
            "categories": ["personality", "leadership", "management"],
            "keywords": ["leadership", "management", "executive", "director", "senior", "strategic thinking"]
        },
        {
            "name": "Dependability & Safety Instrument (DSI)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/dsi/",
            "test_type": "P",
            "description": "Personality-based assessment measuring dependability, rule-following, and safety awareness for roles where safety and reliability are critical.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["personality", "safety", "dependability"],
            "keywords": ["safety", "reliability", "dependability", "compliance", "manufacturing", "operations", "warehouse"]
        },
        {
            "name": "Work Styles Questionnaire (WSQ)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/wsq/",
            "test_type": "P",
            "description": "Brief personality questionnaire measuring key work styles. Suitable for volume hiring and screening scenarios.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "10-15 minutes",
            "categories": ["personality", "work styles"],
            "keywords": ["work style", "screening", "volume hiring", "entry level", "personality"]
        },

        # === BEHAVIORAL / SITUATIONAL JUDGMENT ===
        {
            "name": "SHL Situational Judgment Test - Graduate",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/situational-judgment-test-graduate/",
            "test_type": "B",
            "description": "Graduate-level SJT presenting realistic workplace scenarios to assess judgment and decision-making in professional contexts.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "25 minutes",
            "categories": ["behavioral", "situational judgment", "graduate"],
            "keywords": ["graduate", "entry level", "judgment", "decision making", "workplace scenarios", "professional"]
        },
        {
            "name": "SHL Situational Judgment Test - Manager",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/situational-judgment-test-manager/",
            "test_type": "B",
            "description": "Management-level SJT assessing judgment in managerial situations including delegation, conflict resolution, and team management.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "30 minutes",
            "categories": ["behavioral", "situational judgment", "management"],
            "keywords": ["manager", "leadership", "delegation", "conflict resolution", "team management", "decision making"]
        },
        {
            "name": "SHL Situational Judgment Test - Supervisory",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/situational-judgment-test-supervisory/",
            "test_type": "B",
            "description": "Supervisory-level SJT for frontline leaders and supervisors, assessing judgment in supervisory contexts.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "25 minutes",
            "categories": ["behavioral", "situational judgment", "supervisory"],
            "keywords": ["supervisor", "team leader", "frontline", "operations", "judgment"]
        },
        {
            "name": "Realistic Job Preview (Call Center)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/realistic-job-preview-call-center/",
            "test_type": "B",
            "description": "Simulated call center experience to assess fit and provide realistic preview of call center work.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "15 minutes",
            "categories": ["behavioral", "simulation", "call center"],
            "keywords": ["call center", "customer service", "simulation", "realistic preview", "phone"]
        },

        # === KNOWLEDGE / TECHNICAL TESTS ===
        # -- Programming Languages --
        {
            "name": "Java 8 (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/java-8-new/",
            "test_type": "K",
            "description": "Tests knowledge of Java 8 programming including OOP, lambdas, streams, collections, and exception handling.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "programming", "java"],
            "keywords": ["java", "java 8", "programming", "developer", "software engineer", "oop", "backend"]
        },
        {
            "name": "Java 11",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/java-11/",
            "test_type": "K",
            "description": "Tests knowledge of Java 11 features including modules, var keyword, HTTP client, and modern Java programming.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "programming", "java"],
            "keywords": ["java", "java 11", "programming", "developer", "software engineer", "modules"]
        },
        {
            "name": "Core Java",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/core-java/",
            "test_type": "K",
            "description": "Tests foundational Java programming knowledge including data types, control flow, classes, and core APIs.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "programming", "java"],
            "keywords": ["java", "core java", "programming", "developer", "fundamentals"]
        },
        {
            "name": "Python 3 (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/python-3-new/",
            "test_type": "K",
            "description": "Tests Python 3 programming skills including data structures, functions, OOP, file handling, and Python-specific features.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "programming", "python"],
            "keywords": ["python", "python 3", "programming", "developer", "data science", "scripting", "automation"]
        },
        {
            "name": "Python (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/python-new/",
            "test_type": "K",
            "description": "General Python programming assessment covering core language features and best practices.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "programming", "python"],
            "keywords": ["python", "programming", "developer", "scripting"]
        },
        {
            "name": "JavaScript (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/javascript-new/",
            "test_type": "K",
            "description": "Tests JavaScript programming knowledge including ES6+, DOM manipulation, async programming, closures, and prototypes.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "programming", "javascript"],
            "keywords": ["javascript", "js", "frontend", "web developer", "es6", "node.js"]
        },
        {
            "name": "C# (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/c-sharp-new/",
            "test_type": "K",
            "description": "Tests C# programming knowledge including .NET framework, LINQ, async/await, generics, and object-oriented principles.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "programming", "c#", ".net"],
            "keywords": ["c#", "csharp", ".net", "microsoft", "developer", "backend"]
        },
        {
            "name": "C++ (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/c-plus-plus-new/",
            "test_type": "K",
            "description": "Tests C++ programming skills including STL, templates, memory management, and OOP concepts.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "programming", "c++"],
            "keywords": ["c++", "systems programming", "embedded", "game development", "performance"]
        },
        {
            "name": "PHP (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/php-new/",
            "test_type": "K",
            "description": "Tests PHP programming knowledge for web development.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "programming", "php"],
            "keywords": ["php", "web development", "backend", "laravel", "wordpress"]
        },
        {
            "name": "Ruby on Rails",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/ruby-on-rails/",
            "test_type": "K",
            "description": "Tests Ruby on Rails framework knowledge including MVC architecture, Active Record, routing, and conventions.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "programming", "ruby"],
            "keywords": ["ruby", "rails", "web development", "backend", "mvc"]
        },
        {
            "name": "Swift (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/swift-new/",
            "test_type": "K",
            "description": "Tests Swift programming knowledge for iOS and macOS development.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "programming", "swift"],
            "keywords": ["swift", "ios", "apple", "mobile development", "macos"]
        },
        {
            "name": "Kotlin",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/kotlin/",
            "test_type": "K",
            "description": "Tests Kotlin programming knowledge for Android and JVM-based development.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "programming", "kotlin"],
            "keywords": ["kotlin", "android", "mobile development", "jvm"]
        },
        {
            "name": "Scala",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/scala/",
            "test_type": "K",
            "description": "Tests Scala programming knowledge including functional programming concepts and JVM development.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "programming", "scala"],
            "keywords": ["scala", "functional programming", "jvm", "big data", "spark"]
        },
        {
            "name": "R Programming",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/r-programming/",
            "test_type": "K",
            "description": "Tests R programming knowledge for statistical computing and data analysis.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "programming", "r"],
            "keywords": ["r", "statistics", "data analysis", "data science", "analytics"]
        },
        {
            "name": "Go (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/go-new/",
            "test_type": "K",
            "description": "Tests Go (Golang) programming knowledge including concurrency, goroutines, and standard library.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "programming", "go"],
            "keywords": ["go", "golang", "concurrency", "cloud", "microservices", "backend"]
        },
        {
            "name": "TypeScript (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/typescript-new/",
            "test_type": "K",
            "description": "Tests TypeScript programming knowledge including type system, interfaces, generics, and modern features.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "programming", "typescript"],
            "keywords": ["typescript", "javascript", "frontend", "angular", "web development", "types"]
        },

        # -- Web / Frameworks --
        {
            "name": "Angular (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/angular-new/",
            "test_type": "K",
            "description": "Tests Angular framework knowledge including components, services, routing, and reactive programming.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "web", "angular"],
            "keywords": ["angular", "frontend", "web development", "typescript", "spa"]
        },
        {
            "name": "React (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/react-new/",
            "test_type": "K",
            "description": "Tests React library knowledge including components, hooks, state management, and virtual DOM.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "web", "react"],
            "keywords": ["react", "frontend", "web development", "javascript", "spa", "redux"]
        },
        {
            "name": "Node.js (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/node-js-new/",
            "test_type": "K",
            "description": "Tests Node.js knowledge including async programming, Express, npm, and server-side JavaScript.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "web", "node.js"],
            "keywords": ["node.js", "backend", "javascript", "api", "express", "server"]
        },
        {
            "name": "HTML/CSS (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/html-css-new/",
            "test_type": "K",
            "description": "Tests HTML5 and CSS3 knowledge including semantic markup, flexbox, grid, responsive design.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "web", "html", "css"],
            "keywords": ["html", "css", "web development", "frontend", "responsive", "markup"]
        },
        {
            "name": "Spring Framework",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/spring-framework/",
            "test_type": "K",
            "description": "Tests Spring Framework knowledge including Spring Boot, dependency injection, MVC, and REST APIs.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "web", "java", "spring"],
            "keywords": ["spring", "spring boot", "java", "backend", "microservices", "rest api"]
        },
        {
            "name": "ASP.NET",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/asp-net/",
            "test_type": "K",
            "description": "Tests ASP.NET framework knowledge for web application development on the Microsoft stack.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "web", ".net"],
            "keywords": ["asp.net", ".net", "c#", "web development", "microsoft", "backend"]
        },
        {
            "name": "Django",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/django/",
            "test_type": "K",
            "description": "Tests Django framework knowledge for Python web development.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "web", "python", "django"],
            "keywords": ["django", "python", "web development", "backend", "orm"]
        },
        {
            "name": "REST API",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/rest-api/",
            "test_type": "K",
            "description": "Tests knowledge of RESTful API design principles, HTTP methods, status codes, and best practices.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "15 minutes",
            "categories": ["technology", "web", "api"],
            "keywords": ["rest", "api", "web services", "http", "json", "backend"]
        },
        {
            "name": "WordPress",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/wordpress/",
            "test_type": "K",
            "description": "Tests WordPress CMS knowledge including themes, plugins, PHP customization.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "web", "wordpress"],
            "keywords": ["wordpress", "cms", "web development", "php", "content management"]
        },

        # -- Database --
        {
            "name": "SQL (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/sql-new/",
            "test_type": "K",
            "description": "Tests SQL knowledge including queries, joins, aggregations, subqueries, and database concepts.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "database", "sql"],
            "keywords": ["sql", "database", "queries", "data", "relational", "backend"]
        },
        {
            "name": "SQL Server",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/sql-server/",
            "test_type": "K",
            "description": "Tests Microsoft SQL Server specific knowledge including T-SQL, stored procedures, and administration.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "database", "sql server"],
            "keywords": ["sql server", "microsoft", "database", "t-sql", "dba"]
        },
        {
            "name": "Oracle Database",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/oracle-database/",
            "test_type": "K",
            "description": "Tests Oracle database knowledge including PL/SQL, administration, and Oracle-specific features.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "database", "oracle"],
            "keywords": ["oracle", "database", "pl/sql", "dba", "enterprise"]
        },
        {
            "name": "MongoDB",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/mongodb/",
            "test_type": "K",
            "description": "Tests MongoDB NoSQL database knowledge including document modeling, queries, and aggregation.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "database", "nosql"],
            "keywords": ["mongodb", "nosql", "database", "document store", "json"]
        },

        # -- DevOps / Cloud / Infrastructure --
        {
            "name": "AWS (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/aws-new/",
            "test_type": "K",
            "description": "Tests Amazon Web Services knowledge including EC2, S3, Lambda, IAM, and cloud architecture.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "cloud", "aws"],
            "keywords": ["aws", "cloud", "amazon", "devops", "infrastructure", "ec2", "s3"]
        },
        {
            "name": "Azure (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/azure-new/",
            "test_type": "K",
            "description": "Tests Microsoft Azure cloud platform knowledge including compute, storage, and networking services.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "cloud", "azure"],
            "keywords": ["azure", "cloud", "microsoft", "devops", "infrastructure"]
        },
        {
            "name": "Docker",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/docker/",
            "test_type": "K",
            "description": "Tests Docker containerization knowledge including images, containers, Dockerfile, and orchestration basics.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "devops", "docker"],
            "keywords": ["docker", "containers", "devops", "microservices", "deployment"]
        },
        {
            "name": "Kubernetes",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/kubernetes/",
            "test_type": "K",
            "description": "Tests Kubernetes knowledge including pods, services, deployments, and cluster management.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "devops", "kubernetes"],
            "keywords": ["kubernetes", "k8s", "containers", "orchestration", "devops", "cloud"]
        },
        {
            "name": "Linux (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/linux-new/",
            "test_type": "K",
            "description": "Tests Linux operating system knowledge including commands, file systems, permissions, and administration.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "infrastructure", "linux"],
            "keywords": ["linux", "unix", "system administration", "devops", "command line", "bash"]
        },
        {
            "name": "Git",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/git/",
            "test_type": "K",
            "description": "Tests Git version control knowledge including branching, merging, rebasing, and workflows.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "15 minutes",
            "categories": ["technology", "devops", "git"],
            "keywords": ["git", "version control", "github", "branching", "devops"]
        },
        {
            "name": "CI/CD",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/ci-cd/",
            "test_type": "K",
            "description": "Tests continuous integration and continuous delivery concepts, tools, and practices.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "15 minutes",
            "categories": ["technology", "devops", "ci/cd"],
            "keywords": ["ci/cd", "jenkins", "pipeline", "devops", "automation", "deployment"]
        },
        {
            "name": "Networking Fundamentals",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/networking-fundamentals/",
            "test_type": "K",
            "description": "Tests computer networking knowledge including TCP/IP, DNS, routing, firewalls, and protocols.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "networking"],
            "keywords": ["networking", "tcp/ip", "dns", "security", "infrastructure", "network engineer"]
        },

        # -- Data / Analytics --
        {
            "name": "Data Science (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/data-science-new/",
            "test_type": "K",
            "description": "Tests data science knowledge including machine learning, statistics, feature engineering, and model evaluation.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "25 minutes",
            "categories": ["technology", "data science"],
            "keywords": ["data science", "machine learning", "statistics", "python", "analytics", "AI"]
        },
        {
            "name": "Machine Learning (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/machine-learning-new/",
            "test_type": "K",
            "description": "Tests machine learning knowledge including supervised/unsupervised learning, neural networks, and evaluation metrics.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "25 minutes",
            "categories": ["technology", "machine learning"],
            "keywords": ["machine learning", "deep learning", "neural networks", "AI", "data science"]
        },
        {
            "name": "Power BI",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/power-bi/",
            "test_type": "K",
            "description": "Tests Microsoft Power BI knowledge including data modeling, DAX, visualizations, and report design.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "data", "business intelligence"],
            "keywords": ["power bi", "business intelligence", "data visualization", "microsoft", "analytics", "reporting"]
        },
        {
            "name": "Tableau",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/tableau/",
            "test_type": "K",
            "description": "Tests Tableau data visualization knowledge including calculated fields, dashboards, and data blending.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "data", "business intelligence"],
            "keywords": ["tableau", "data visualization", "business intelligence", "analytics", "dashboards"]
        },
        {
            "name": "Hadoop",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/hadoop/",
            "test_type": "K",
            "description": "Tests Apache Hadoop ecosystem knowledge including HDFS, MapReduce, Hive, and big data concepts.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "big data"],
            "keywords": ["hadoop", "big data", "hdfs", "mapreduce", "hive", "data engineering"]
        },
        {
            "name": "Apache Spark",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/apache-spark/",
            "test_type": "K",
            "description": "Tests Apache Spark knowledge for large-scale data processing, including RDDs, DataFrames, and Spark SQL.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "big data"],
            "keywords": ["spark", "big data", "data processing", "scala", "python", "data engineering"]
        },

        # -- Microsoft Office --
        {
            "name": "Microsoft Excel (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/microsoft-excel-new/",
            "test_type": "K",
            "description": "Tests Microsoft Excel knowledge including formulas, pivot tables, charts, VLOOKUP, and data analysis.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["office", "microsoft"],
            "keywords": ["excel", "spreadsheet", "office", "data analysis", "formulas", "administrative"]
        },
        {
            "name": "Microsoft Word",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/microsoft-word/",
            "test_type": "K",
            "description": "Tests Microsoft Word knowledge including document formatting, styles, mail merge, and templates.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "15 minutes",
            "categories": ["office", "microsoft"],
            "keywords": ["word", "document", "office", "formatting", "administrative"]
        },
        {
            "name": "Microsoft PowerPoint",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/microsoft-powerpoint/",
            "test_type": "K",
            "description": "Tests Microsoft PowerPoint knowledge including slide design, animations, and presentation skills.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "15 minutes",
            "categories": ["office", "microsoft"],
            "keywords": ["powerpoint", "presentation", "office", "slides", "administrative"]
        },
        {
            "name": "Microsoft Outlook",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/microsoft-outlook/",
            "test_type": "K",
            "description": "Tests Microsoft Outlook knowledge including email management, calendar, and task organization.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "15 minutes",
            "categories": ["office", "microsoft"],
            "keywords": ["outlook", "email", "office", "calendar", "administrative"]
        },
        {
            "name": "Microsoft Office Suite",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/microsoft-office-suite/",
            "test_type": "K",
            "description": "Comprehensive test covering Word, Excel, PowerPoint, and Outlook proficiency.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "25 minutes",
            "categories": ["office", "microsoft"],
            "keywords": ["microsoft office", "word", "excel", "powerpoint", "outlook", "administrative"]
        },

        # -- Testing/QA --
        {
            "name": "Selenium (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/selenium-new/",
            "test_type": "K",
            "description": "Tests Selenium WebDriver knowledge for automated web application testing.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "testing", "qa"],
            "keywords": ["selenium", "automation testing", "qa", "web testing", "test automation"]
        },
        {
            "name": "Manual Testing",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/manual-testing/",
            "test_type": "K",
            "description": "Tests manual software testing knowledge including test case design, bug reporting, and test methodologies.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "testing", "qa"],
            "keywords": ["manual testing", "qa", "test cases", "bug reporting", "quality assurance"]
        },
        {
            "name": "Agile Methodology",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/agile-methodology/",
            "test_type": "K",
            "description": "Tests Agile and Scrum methodology knowledge including sprints, user stories, and ceremonies.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "15 minutes",
            "categories": ["technology", "methodology"],
            "keywords": ["agile", "scrum", "kanban", "project management", "sprints", "user stories"]
        },

        # -- Business/Finance --
        {
            "name": "Accounting (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/accounting-new/",
            "test_type": "K",
            "description": "Tests accounting knowledge including financial statements, journal entries, GAAP, and reconciliation.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["business", "accounting", "finance"],
            "keywords": ["accounting", "finance", "bookkeeping", "financial statements", "GAAP", "auditing"]
        },
        {
            "name": "Financial Analysis",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/financial-analysis/",
            "test_type": "K",
            "description": "Tests financial analysis knowledge including ratio analysis, valuation, financial modeling, and reporting.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["business", "finance"],
            "keywords": ["financial analysis", "valuation", "ratios", "finance", "analyst"]
        },
        {
            "name": "Business English",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/business-english/",
            "test_type": "K",
            "description": "Tests business English proficiency including grammar, vocabulary, reading comprehension, and professional communication.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["language", "business"],
            "keywords": ["english", "language", "communication", "writing", "grammar", "business communication"]
        },

        # -- Clerical/Administrative --
        {
            "name": "Typing Speed Test",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/typing-speed-test/",
            "test_type": "K",
            "description": "Measures typing speed and accuracy. For administrative, data entry, and clerical roles.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "5 minutes",
            "categories": ["clerical", "administrative"],
            "keywords": ["typing", "data entry", "clerical", "administrative", "speed", "accuracy"]
        },
        {
            "name": "Data Entry",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/data-entry/",
            "test_type": "K",
            "description": "Tests data entry speed and accuracy, including alphanumeric input and form completion.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "10 minutes",
            "categories": ["clerical", "administrative"],
            "keywords": ["data entry", "clerical", "administrative", "accuracy", "speed"]
        },

        # -- Industry-specific --
        {
            "name": "SAP (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/sap-new/",
            "test_type": "K",
            "description": "Tests SAP ERP system knowledge including modules, transactions, and configuration.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "enterprise"],
            "keywords": ["sap", "erp", "enterprise", "business process", "consultant"]
        },
        {
            "name": "Salesforce",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/salesforce/",
            "test_type": "K",
            "description": "Tests Salesforce CRM platform knowledge including configuration, Apex, and administration.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "crm"],
            "keywords": ["salesforce", "crm", "sales", "cloud", "apex", "administration"]
        },
        {
            "name": "AutoCAD",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/autocad/",
            "test_type": "K",
            "description": "Tests AutoCAD knowledge for computer-aided design and drafting.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "design"],
            "keywords": ["autocad", "cad", "design", "drafting", "engineering", "architecture"]
        },
        {
            "name": "Cybersecurity (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/cybersecurity-new/",
            "test_type": "K",
            "description": "Tests cybersecurity knowledge including network security, encryption, threat assessment, and security best practices.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["technology", "security"],
            "keywords": ["cybersecurity", "security", "network security", "encryption", "threat", "information security"]
        },

        # -- Skills-based assessments --
        {
            "name": "SHL Verify - Reading Comprehension",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/verify-reading-comprehension/",
            "test_type": "A",
            "description": "Measures reading comprehension ability for roles requiring document review and information extraction.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "15 minutes",
            "categories": ["cognitive", "verbal", "comprehension"],
            "keywords": ["reading", "comprehension", "document review", "information processing"]
        },
        {
            "name": "Computer Literacy (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/computer-literacy-new/",
            "test_type": "K",
            "description": "Tests general computer literacy including file management, internet usage, and basic software skills.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "15 minutes",
            "categories": ["technology", "general"],
            "keywords": ["computer literacy", "basic computer", "digital skills", "file management", "internet"]
        },
        {
            "name": "Digital Marketing",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/digital-marketing/",
            "test_type": "K",
            "description": "Tests digital marketing knowledge including SEO, SEM, social media marketing, and analytics.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["business", "marketing"],
            "keywords": ["digital marketing", "seo", "social media", "marketing", "analytics", "content"]
        },
        {
            "name": "Project Management (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/project-management-new/",
            "test_type": "K",
            "description": "Tests project management knowledge including planning, execution, risk management, and methodologies.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["business", "management"],
            "keywords": ["project management", "planning", "risk management", "PMP", "stakeholder", "scheduling"]
        },
        {
            "name": "Customer Service Simulation",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/customer-service-simulation/",
            "test_type": "B",
            "description": "Interactive simulation assessing customer service skills in realistic scenarios including problem resolution and communication.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["behavioral", "simulation", "customer service"],
            "keywords": ["customer service", "simulation", "call center", "problem resolution", "communication"]
        },
        {
            "name": "Sales Assessment",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/sales-assessment/",
            "test_type": "B",
            "description": "Behavioral assessment measuring sales competencies including prospecting, negotiation, and closing.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "25 minutes",
            "categories": ["behavioral", "sales"],
            "keywords": ["sales", "negotiation", "prospecting", "closing", "client relationship", "revenue"]
        },
        {
            "name": "Verify - Spatial Reasoning",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/verify-spatial-reasoning/",
            "test_type": "A",
            "description": "Measures spatial visualization and manipulation abilities. For roles requiring 3D thinking and spatial awareness.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["cognitive", "spatial", "ability"],
            "keywords": ["spatial", "3D", "visualization", "design", "engineering", "architecture"]
        },
        {
            "name": "Critical Thinking Assessment",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/critical-thinking/",
            "test_type": "A",
            "description": "Assesses critical thinking and analytical reasoning abilities for professional and managerial roles.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "25 minutes",
            "categories": ["cognitive", "reasoning"],
            "keywords": ["critical thinking", "analytical", "reasoning", "problem solving", "management", "professional"]
        },
        {
            "name": "English Comprehension (New)",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/english-comprehension-new/",
            "test_type": "K",
            "description": "Tests English language comprehension skills including grammar, vocabulary, and reading comprehension.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["language"],
            "keywords": ["english", "language", "comprehension", "grammar", "vocabulary", "communication"]
        },
        {
            "name": "Attention to Detail",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/attention-to-detail/",
            "test_type": "A",
            "description": "Assesses ability to identify errors and inconsistencies in data. For roles requiring precision and accuracy.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "12 minutes",
            "categories": ["cognitive", "checking"],
            "keywords": ["attention to detail", "accuracy", "errors", "quality", "precision", "clerical", "proofreading"]
        },
        {
            "name": "Emotional Intelligence Assessment",
            "url": "https://www.shl.com/solutions/products/product-catalog/view/emotional-intelligence/",
            "test_type": "B",
            "description": "Assesses emotional intelligence competencies including self-awareness, empathy, and social skills.",
            "remote_testing": "Yes",
            "adaptive_testing": "No",
            "duration": "20 minutes",
            "categories": ["behavioral", "emotional intelligence"],
            "keywords": ["emotional intelligence", "eq", "empathy", "self-awareness", "interpersonal", "leadership"]
        },
    ]

    # Build full_text for search
    for item in catalog:
        item["full_text"] = build_full_text(item)

    return catalog


def build_full_text(item: Dict) -> str:
    """Build searchable full text from catalog item."""
    parts = [
        item.get("name", ""),
        item.get("description", ""),
        " ".join(item.get("categories", [])),
        " ".join(item.get("keywords", [])),
        item.get("test_type", ""),
    ]
    return " ".join(parts).lower()


if __name__ == "__main__":
    items = build_full_catalog()
    print(f"Built catalog with {len(items)} items")
    for item in items[:5]:
        print(f"  - {item['name']} ({item['test_type']}): {item['url']}")