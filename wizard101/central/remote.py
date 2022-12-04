import time
import typing
import re
from functools import cache
import sys


from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement

from . import models

API_ROOT = "https://www.wizard101central.com"


@cache
def driver() -> webdriver.Firefox:
    options = webdriver.FirefoxOptions()
    options.set_capability("pageLoadStrategy", "eager")

    options.profile = webdriver.FirefoxProfile()
    options.profile.set_preference("network.cookie.cookieBehavior", 2)

    return webdriver.Firefox(options=options)


T = typing.TypeVar("T")
P = typing.ParamSpec("P")


def wait_for(timeout: float, func: typing.Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """
    Repeatedly calls the function until it doesn't error.
    If the duration is exhausted, the function will be called one last time and any errors will be propagated.
    """
    start = time.time()
    while True:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if time.time() - start >= timeout:
                raise TimeoutError(
                    f"`{func!r}(*{args!r}, **{kwargs!r})` did not succeed within {timeout} seconds"
                ) from e

            time.sleep(timeout / 100)


def page_must_be_loaded():
    ready_state = driver().execute_script("return document.readyState;")
    if ready_state != "complete":
        raise Exception(f"Page is not loaded. document.readyState = {ready_state!r}")


def driver_close_extra_tabs():
    for window_handle in driver().window_handles[1:]:
        driver().switch_to.window(window_handle)
        driver().close()


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
    cursor = models.database.execute("SELECT url FROM raw_item_data WHERE category = ?", (category,))
    return [url for url, in cursor.fetchall()]


def get_all_category_item_urls(
    category: str, use_cache: bool | None = None, print_progress: bool | None = None
) -> list[str]:
    if print_progress is None:
        print_progress = use_cache is not True

    cached_item_urls = get_all_category_item_urls_cached(category)
    if use_cache is True:
        if print_progress:
            print(f"Using cached items in {category!r}. Skipping validations.")
        return cached_item_urls

    item_urls = []
    url = f"{API_ROOT}/wiki/Category:{category}"

    if print_progress:
        print(f"Fetching item urls for {category!r}...")

    if cached_item_urls and use_cache is not False:
        print(
            f"There are already {len(cached_item_urls)} urls cached in the database. Checking if that is still up to date..."
        )

    first_page = True
    while url:
        section_item_urls, total_items_in_category, url = get_single_category_page(url)
        item_urls += section_item_urls

        if first_page and use_cache is not False:
            if total_items_in_category == len(cached_item_urls):
                print(f"It is! Skipping further fetches and pulling from the database instead.")
                return cached_item_urls
            elif cached_item_urls:
                print(
                    f"It is not. There are {total_items_in_category} total urls available. Clearing cache and reloading..."
                )
        first_page = False

        duplicate_count = len(item_urls) - len(set(item_urls))
        duplicates = "" if duplicate_count == 0 else f"(found {duplicate_count} duplicate(s))"
        print(f"Fetched {len(item_urls)} / {total_items_in_category} {duplicates}".strip())

    models.database.execute("DELETE FROM raw_item_data WHERE category = ?", (category,))

    cursor = models.database.cursor()
    for item_url in item_urls:
        cursor.execute("INSERT INTO raw_item_data (url, category) VALUES (?, ?)", (item_url, category))
    models.database.commit()
    print(f"Cached {len(item_urls)} urls for later reuse")

    return item_urls


def get_all_item_urls(**options) -> list[tuple[str, str]]:
    return sorted(
        [
            (url, category)
            for category in models.Item.CATEGORIES
            for url in get_all_category_item_urls(category, **options)
        ]
    )


def get_item_page_source_cached(url: str) -> str | None:
    cursor = models.database.execute("SELECT page_source FROM raw_item_data WHERE url = ?", (url,))
    row = cursor.fetchone()
    if row:
        (page_source,) = row
        return page_source

    return None


def get_item_page_source(url: str, use_cache: bool | None = None, load_timeout: float = 10) -> str | None:
    cached_page_source = get_item_page_source_cached(url)

    if use_cache is True:
        return cached_page_source
    elif cached_page_source is not None and use_cache is not False:
        return cached_page_source

    driver().get(url)

    wait_for(
        load_timeout,
        lambda: (page_must_be_loaded(), driver().find_element(By.CSS_SELECTOR, "div#content > h1#firstHeading")),
    )

    page_source = driver().page_source

    models.database.execute("UPDATE raw_item_data SET page_source = ? WHERE url = ?", (page_source, url))
    models.database.commit()

    return page_source


def load_item_page_sources(log_file: typing.IO = sys.stdout):
    for url, category in get_all_item_urls(use_cache=True):
        try:
            get_item_page_source(url)
            print(f"[{category}, {url}] DONE", file=log_file)
        except Exception as e:
            print(f"[{category}, {url}] FAILED - {e!r} - {driver().page_source!r}", file=log_file)
