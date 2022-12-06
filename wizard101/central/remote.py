import time
import typing
import re
from functools import cache
import sys

from selenium import webdriver
from selenium.webdriver.common.by import By
import undetected_chromedriver as uc

from . import models

API_ROOT = "https://www.wizard101central.com"


@cache
def driver() -> webdriver.Chrome:
    return uc.Chrome()


T = typing.TypeVar("T")
P = typing.ParamSpec("P")


def resolve_print_progress(use_cache: bool | None = None, print_progress: bool | None = None) -> bool:
    if print_progress is None:
        return use_cache is not True
    return print_progress


def wait_for(timeout: float, func: typing.Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """
    Repeatedly calls the function until it doesn't error.
    If the duration is exhausted, the a TimeoutError will be raised from the function's error.
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
    print_progress = resolve_print_progress(use_cache, print_progress)

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
                if print_progress:
                    print(f"It is! Skipping further fetches and pulling from the database instead.")
                return cached_item_urls
            elif cached_item_urls and print_progress:
                print(f"It is not. There are {total_items_in_category} total urls available. Updating index...")
        first_page = False

        duplicate_count = len(item_urls) - len(set(item_urls))
        duplicates = "" if duplicate_count == 0 else f"(found {duplicate_count} duplicate(s))"

        if print_progress:
            print(f"Fetched {len(item_urls)} / {total_items_in_category} {duplicates}".strip())

    cursor = models.database.cursor()

    cursor.execute(
        f"DELETE FROM raw_item_data WHERE category = ? AND url NOT IN ({', '.join(['?'] * len(item_urls))})",
        (category, *item_urls),
    )

    for item_url in item_urls:
        cursor.execute("INSERT OR IGNORE INTO raw_item_data (url, category) VALUES (?, ?)", (item_url, category))

    models.database.commit()

    if print_progress:
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
        lambda: driver().find_element(By.CSS_SELECTOR, "div#content > h1#firstHeading"),
    )

    page_source = driver().page_source

    models.database.execute("UPDATE raw_item_data SET page_source = ? WHERE url = ?", (page_source, url))
    models.database.commit()

    return page_source


def get_item_page_sources(
    log_file: typing.IO = sys.stdout, use_cache: bool | None = None, print_progress: bool | None = None
) -> typing.Generator[tuple[str, str | None], None, None]:
    print_progress = resolve_print_progress(use_cache, print_progress)
    item_urls = get_all_item_urls(use_cache=use_cache, print_progress=print_progress)

    for i, (url, category) in enumerate(item_urls):
        try:
            if print_progress:
                print(f"({i+1}/{len(item_urls)}) [{category}, {url}] FETCHED", file=log_file, flush=True)

            yield url, get_item_page_source(url, use_cache=use_cache)
        except Exception as e:
            if print_progress:
                print(
                    f"({i+1}/{len(item_urls)}) [{category}, {url}] FAILED - {e!r}",
                    file=log_file,
                    flush=True,
                )


def refresh_item_index(print_progress: bool = True):
    for _ in get_item_page_sources(print_progress=print_progress):
        pass
