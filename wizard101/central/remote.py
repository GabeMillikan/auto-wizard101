import time
import typing
import re
from functools import cache

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement

from . import models

API_ROOT = "https://www.wizard101central.com"


@cache
def driver() -> webdriver.Chrome:
    return webdriver.Chrome()


T = typing.TypeVar("T")
P = typing.ParamSpec("P")


def wait_for(timeout: float, func: typing.Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """
    Repeatedly calls the function until it doesn't error.
    If the duration is exhausted, the function will be called one last time and any errors will be propagated.
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            return func(*args, **kwargs)
        except:
            time.sleep(timeout / 100)

    return func(*args, **kwargs)


def get_single_category_page(url: str) -> tuple[list[str], int, str | None]:
    driver().get(url)

    section_element = wait_for(10, driver().find_element, By.ID, "mw-pages")
    top_level_link_elements = section_element.find_elements(By.CSS_SELECTOR, "* > a")
    short_description_element = section_element.find_element(By.CSS_SELECTOR, "* > p")
    item_container_element = section_element.find_element(By.CSS_SELECTOR, "* > .mw-content-ltr")
    item_link_elements = item_container_element.find_elements(By.TAG_NAME, "a")

    item_urls = [item_link_element.get_attribute("href") for item_link_element in item_link_elements]

    total_items_in_category_string = re.search(
        r"(\d+)\D*total", short_description_element.text.replace(",", "").replace(".", "")
    )
    total_items_in_category = int(total_items_in_category_string.group(1)) if total_items_in_category_string else -1

    next_page_url = None
    for top_level_link_element in top_level_link_elements:
        if top_level_link_element.text.startswith("next"):
            next_page_url = top_level_link_element.get_attribute("href")
            break

    return item_urls, total_items_in_category, next_page_url


def get_all_category_item_urls_cached(category: str) -> list[str]:
    cursor = models.database.execute("SELECT url FROM cached_item_url WHERE category = ?", (category,))
    return [url for url, in cursor.fetchall()]


def get_all_category_item_urls(category: str, print_progress: bool = True) -> list[str]:
    cached_item_urls = get_all_category_item_urls_cached(category)
    item_urls = []
    url = f"{API_ROOT}/wiki/Category:{category}"

    if print_progress:
        print(f"Fetching item urls for {category!r}...")

    if cached_item_urls:
        print(
            f"There are already {len(cached_item_urls)} urls cached in the database. Checking if that is still up to date..."
        )

    first_run = True
    while url:
        driver().delete_all_cookies()
        section_item_urls, total_items_in_category, url = get_single_category_page(url)
        item_urls += section_item_urls

        if first_run:
            if total_items_in_category == len(cached_item_urls):
                print(f"It is! Skipping further fetches and pulling from the database instead.")
                return cached_item_urls
            elif cached_item_urls:
                print(
                    f"It is not. There are {total_items_in_category} total urls available. Clearing cache and reloading..."
                )
            first_run = False

        duplicate_count = len(item_urls) - len(set(item_urls))
        duplicates = "" if duplicate_count == 0 else f"(found {duplicate_count} duplicate(s))"
        print(f"Fetched {len(item_urls)} / {total_items_in_category} {duplicates}".strip())

    models.database.execute("DELETE FROM cached_item_url WHERE category = ?", (category,))

    cursor = models.database.cursor()
    for item_url in item_urls:
        cursor.execute("INSERT INTO cached_item_url (url, category) VALUES (?, ?)", (item_url, category))
    models.database.commit()
    print(f"Cached {len(item_urls)} urls for later reuse")

    return item_urls


for category in models.Item.CATEGORIES:
    item_urls = get_all_category_item_urls(category)
    print(f"Found {len(item_urls)} URLs in the {category!r} category")
