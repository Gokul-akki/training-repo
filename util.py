import time
import tempfile
import shutil

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Set up a Selenium Chrome WebDriver with a unique temporary user profile
def setup_driver(logger):
    """
    Set up a Selenium Chrome WebDriver with a unique temporary user profile.
    Returns a tuple of (driver, temp_dir).
    """
    options = Options()

    # Create a unique temporary user data directory for each Chrome session
    temp_dir = tempfile.mkdtemp(prefix="chrome_profile_")
    options.add_argument(f"--user-data-dir={temp_dir}")

    # Headless mode and other recommended options for running in containers
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--remote-debugging-port=0")

    # Custom user agent for scraping
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    try:
        # Selenium Manager auto-handles ChromeDriver location
        driver = webdriver.Chrome(options=options)
        logger.info(f"✅ Chrome WebDriver started with profile: {temp_dir}")
        return driver, temp_dir
    except Exception as e:
        logger.error(f"❌ Failed to initialize Chrome WebDriver: {e}", exc_info=True)
        # Clean up temp directory if driver fails to start
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

# Extract all https links from <a> tags on a web page using Selenium and Chrome
def extract_links(url, logger, scroll_attempts=5, scroll_pause_time=1):
    """
    Extract all http(s) links from <a> tags on a web page using Selenium and Chrome.
    Scrolls the page to load more links if needed.
    Returns a list of unique links found on the page.
    """
    driver = None
    temp_dir = None
    links = []
    try:
        # Set up the Chrome WebDriver and temp profile
        driver, temp_dir = setup_driver(logger)
        logger.info(f"🌐 Opening URL: {url}")
        driver.get(url)

        # Wait until at least one <a> tag is loaded
        WebDriverWait(driver, 40).until(
            EC.presence_of_element_located((By.TAG_NAME, "a"))
        )

        # Scroll the page to load more links
        last_height = driver.execute_script("return document.body.scrollHeight")
        for _ in range(scroll_attempts):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(scroll_pause_time)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        # Extract all <a> href links that start with http or https
        links = list({
            tag.get_attribute("href")
            for tag in driver.find_elements(By.TAG_NAME, "a")
            if tag.get_attribute("href") and tag.get_attribute("href").startswith(("http://", "https://"))
        })

        logger.info(f"🔗 Found {len(links)} links")
    except Exception as e:
        logger.error(f"⚠️ Error during extraction: {e}", exc_info=True)
    finally:
        # Always clean up: close browser and delete temp profile
        if driver:
            driver.quit()
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"🗑 Deleted temporary Chrome profile: {temp_dir}")
    return links


import urllib.parse
import urllib.robotparser
import requests

def get_robots_parser(url: str, logger=None, timeout: int = 10):
    """
    Fetch and parse robots.txt for the site of `url`.
    Returns a configured urllib.robotparser.RobotFileParser or None on failure.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        robots_url = urllib.parse.urljoin(base, "/robots.txt")
        if logger:
            logger.info(f"Fetching robots.txt from {robots_url}")
        resp = requests.get(robots_url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        if resp.status_code == 200:
            # parse() accepts an iterable of lines
            rp.parse(resp.text.splitlines())
            if logger:
                logger.info("robots.txt parsed successfully")
        else:
            # No robots.txt or not accessible -> treat as allow-all by returning parser with no rules
            if logger:
                logger.warning(f"robots.txt returned status {resp.status_code}, treating as allow-all")
            # leave rp as-is (no rules)
        return rp
    except Exception as e:
        if logger:
            logger.error(f"Error fetching robots.txt: {e}", exc_info=True)
        return None

def filter_allowed_links(links, robots_parser, base_url=None, user_agent="*", logger=None):
    """
    Filter `links` and return only those allowed by `robots_parser`.
    - links: iterable of absolute URLs (http/https)
    - robots_parser: RobotFileParser (or None). If None, all links are returned.
    - base_url: optional base site URL; if provided, links from other hosts are excluded.
    """
    if robots_parser is None:
        if logger:
            logger.warning("No robots parser available — returning input links unchanged")
        return list(links)

    allowed = []
    for href in links:
        try:
            parsed = urllib.parse.urlparse(href)
            # Optionally enforce same-origin if base_url provided
            if base_url:
                base_netloc = urllib.parse.urlparse(base_url).netloc
                if parsed.netloc and parsed.netloc != base_netloc:
                    # skip external links
                    if logger:
                        logger.debug(f"Skipping external link {href}")
                    continue

            path = parsed.path or "/"
            if parsed.query:
                path = path + "?" + parsed.query

            if robots_parser.can_fetch(user_agent, path):
                allowed.append(href)
            else:
                if logger:
                    logger.debug(f"Disallowed by robots.txt: {href}")
        except Exception as e:
            if logger:
                logger.error(f"Error checking robots for {href}: {e}", exc_info=True)
            # skip link on error
    if logger:
        logger.info(f"Filtered links: {len(allowed)} allowed / {len(links)} total")
    return allowed

def extract_allowed_links(url: str, logger, scroll_attempts: int = 5, scroll_pause_time: int = 1):
    """
    High-level helper:
    - uses extract_links(...) to gather links from the page
    - fetches robots.txt for the site
    - returns only links allowed by robots.txt (and same-origin)
    """
    # get all links from page (extract_links should return absolute http(s) links)
    all_links = extract_links(url, logger, scroll_attempts=scroll_attempts, scroll_pause_time=scroll_pause_time)

    # get robots parser for the site's base URL
    rp = get_robots_parser(url, logger=logger)

    # filter links: only same-origin and allowed by robots.txt
    allowed = filter_allowed_links(all_links, rp, base_url=url, user_agent="*", logger=logger)

    return allowed