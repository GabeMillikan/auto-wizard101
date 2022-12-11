from concurrent.futures import ProcessPoolExecutor, Future, as_completed
import re
import traceback

from bs4 import BeautifulSoup, Tag

from . import models


class Failed(Exception):
    pass


def parse_stats_section(element: Tag) -> tuple[None | str, list[Tag]]:
    children: list[Tag] = element.find_all(recursive=False)
    elements: list[Tag] = []

    for child in children:
        if child.name == "img":
            elements.append(child)
        elif child.name == "a" and isinstance(img_child := child.find("img"), Tag):
            elements.append(img_child)
        else:
            break
    else:
        return "img_modifiers", elements

    elements.clear()

    return None, elements


def identify_image_modifier(element: Tag) -> tuple[str | None, str | None]:
    if element.has_attr("alt") and isinstance(element["alt"], str):
        alt = element["alt"]
        assert isinstance(alt, str)

        if "icon" in alt.lower():
            match = re.search(rf"\b{'|'.join(models.SCHOOLS)}|global\b", alt, re.IGNORECASE)
            if match is not None:
                return "school_lock", match.group(0).lower()

            match = re.search(rf"\b{'|'.join(models.CATEGORIES_IGNORE_PLURALITY)}\b", alt, re.IGNORECASE)
            if match is not None and match.group(0).lower() in models.CATEGORY_LOOKUP:
                return "category", models.CATEGORY_LOOKUP[match.group(0).lower()]

    return None, None


def parse_site_data(url: str, category: str, page_source: str) -> tuple[str, str | None]:
    soup = BeautifulSoup(page_source, "html.parser")

    item_info_sections = soup.select(
        "#mw-content-text > table#ItemInfobox-Display-Table > tbody > tr:nth-child(1) > td > table > tbody > tr > td"
    )
    item_stats_elements = soup.select(
        "#mw-content-text > table#ItemInfobox-Display-Table > tbody > tr:nth-child(1) > td > table > tbody > tr > td:nth-child(1) > table > tbody > tr > td"
    )
    _, _, images_section = soup.select("#mw-content-text > table#ItemInfobox-Display-Table > tbody > tr")

    school_lock: str | None = None

    for stats_element in item_stats_elements:
        t, elements = parse_stats_section(stats_element)

        match t:
            case "img_modifiers":
                for modifier in elements:
                    t, p = identify_image_modifier(modifier)
                    if t == "school_lock":
                        school_lock = p
                    elif t == "category":
                        if p != category:
                            raise Failed(f"expected to find category {category!r} but actually found {p!r}")
                    else:
                        raise Failed(f"Couldn't parse modifier image: {modifier!r}", url)

    return category, school_lock


def main():
    raw_site_data = models.database.execute(
        f"SELECT url, category, page_source FROM raw_site_data WHERE category IN ({','.join('?'*len(models.WearableItem.CATEGORIES))})",
        models.WearableItem.CATEGORIES,
    )

    with ProcessPoolExecutor(max_workers=12) as executor:
        futures: dict[Future[tuple[str, str | None]], tuple[str, str, str]] = {}
        for site_data in raw_site_data:
            if site_data[0] != "https://www.wizard101central.com/wiki/Item:Dragoon%27s_Fiery_Helm":
                pass  # continue
            futures[executor.submit(parse_site_data, *site_data)] = site_data
            # break

        for future in as_completed(list(futures.keys())):
            url, category, page_source = futures.pop(future)
            try:
                _category, school_lock = future.result()
                print(f"[{len(futures)} - {url}]: {school_lock}")
            except Exception as e:
                print("ERROR WITHIN URL:", url)
                traceback.print_exception(e)
            except:
                executor.shutdown(wait=False, cancel_futures=True)
                raise
