import re
import traceback
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from typing import Optional, TypeVar

from bs4 import BeautifulSoup, NavigableString, Tag
from fuzzywuzzy import fuzz

from . import database as db
from .constants import *


class Failed(Exception):
    pass


def identify_stats_section(previous_sections: list[str], element: Tag) -> tuple[None | str, list[Tag]]:
    children: list[Tag] = element.find_all(recursive=False)
    elements: list[Tag] = []

    for child in children:
        if child.name == "img":
            elements.append(child)
        elif child.name == "a" and isinstance(img_child := child.find("img"), Tag):
            elements.append(img_child)
        else:
            elements.clear()
            break
    else:
        return "img_modifiers", elements

    if len(children) == 1:
        text = element.text.lower()
        if "level required" in text:  # also sometimes includes a pvp rank requirement but who cares
            return "level_requirement", children
        elif fuzz.ratio("bonuses", text) > 75:
            return "bonuses_label", children
        elif fuzz.ratio("sockets", text) > 75:
            return "sockets_label", children

    if previous_sections and previous_sections[-1] == "bonuses_label" and all(child.name == "dl" for child in children):
        return "bonuses", children

    if previous_sections and previous_sections[-1] == "sockets_label" and all(child.name == "dl" for child in children):
        return "sockets", children

    return None, elements


def identify_image_modifier(element: Tag) -> tuple[str | None, str | None]:
    if element.has_attr("alt") and isinstance(element["alt"], str):
        alt = str(element["alt"])

        if "icon" in alt.lower():
            match = re.search(rf"\b{'|'.join(SCHOOLS)}|global\b", alt, re.IGNORECASE)
            if match is not None:
                school = match.group(0).lower()
                return "school_lock", None if school == "global" else school

            match = re.search(rf"\b{'|'.join(db.CATEGORIES_IGNORE_PLURALITY)}\b", alt, re.IGNORECASE)
            if match is not None and match.group(0).lower() in CATEGORY_LOOKUP:
                return "category", CATEGORY_LOOKUP[match.group(0).lower()]

    return None, None


def parse_level_requirement(element: Tag) -> int | None:
    if "any level" in element.text.lower():
        return None

    return int(must(re.search(r"\d+", element.text)).group())


T = TypeVar("T")


def must(x: Optional[T]) -> T:
    if x is None:
        raise Failed("called `must(None)`")

    return x


class ParsingResult:
    value: db.WearableItem | db.Jewel | db.PetAbility

    def __init__(self, value):
        self.value = value


def parse_numeric_school_based_stat_row(elements: list[NavigableString | Tag], name: str) -> dict[str, float]:
    results: dict[str, float] = {}
    value = None
    set_schools = 0
    found_terminating_image = False
    for part in elements:
        if isinstance(part, NavigableString):
            part = str(part).replace(",", "").strip()
            if found_terminating_image or not part:
                continue

            value = re.search(r"\d+", part)
            if not value:
                raise Failed(f"Unexpected (non-numeric) symbol while parsing {name!r} row - {part!r}")
            value = float(value.group())
        else:
            assert isinstance(part, Tag)

            if found_terminating_image:
                raise Failed(f"Found more data after {name!r} terminating image {part!r}")

            imgs: list[Tag] = part.find_all("img")
            if len(imgs) != 1:
                raise Failed(f"Found {len(imgs)} images within a single child of the {name!r} row")

            img = imgs[0]
            if name.lower() in str(img["alt"]).lower():
                found_terminating_image = True
                continue

            if value is None:
                raise Failed(f"Found school image before numeric value while parsing {name!r} row")

            school = must(re.search(rf"\b{'|'.join(SCHOOLS)}|global\b", str(img["alt"]).lower())).group(0)
            results[school] = value
            set_schools += 1

    if value is None and not results:
        raise Failed(f"didn't find any data in {name} row")
    elif not results:
        assert value is not None
        results["universal"] = value

    if "global" in results:
        results["universal"] = results.pop("global")

    return results


def parse_wearable(site_data: db.RawSiteData) -> ParsingResult:
    wearable = db.WearableItem()
    assert site_data.page_source is not None, "bruh how am i supposed to parse this -_-"
    soup = BeautifulSoup(site_data.page_source, "html.parser")

    wearable.page_url = site_data.page_url
    wearable.category = site_data.category

    wearable.name = re.sub(
        r"^\s*\S*\s?\S*:\s*",
        "",
        must(soup.select_one("#firstHeading")).text,
        flags=re.IGNORECASE,
    )

    item_stats_sections = soup.select(
        "#mw-content-text > table#ItemInfobox-Display-Table > tbody > tr:nth-child(1) > td > table > tbody > tr > td:nth-child(1) > table > tbody > tr > td"
    )
    # _, _, images_section = soup.select("#mw-content-text > table#ItemInfobox-Display-Table > tbody > tr")

    identified_stats_sections: list[str] = []
    for stats_section in item_stats_sections:
        t, elements = identify_stats_section(identified_stats_sections, stats_section)
        if t:
            identified_stats_sections.append(t)

        match t:
            case "level_requirement":
                wearable.level_requirement = parse_level_requirement(elements[0])
            case "img_modifiers":
                for modifier in elements:
                    t, p = identify_image_modifier(modifier)
                    if t == "school_lock":
                        if p != "global":
                            wearable.school_lock = p
                    elif t == "category":
                        if p != site_data.category:
                            raise Failed(f"expected to find category {site_data.category!r} but actually found {p!r}")
                    else:
                        raise Failed(f"Couldn't parse modifier image: {modifier!r} {site_data!r}")
            case "bonuses_label":
                pass
            case "bonuses":
                next_element_is_sockets = False
                for element in elements:
                    children: list[Tag] = element.find_all(recursive=False)
                    text = re.sub(r"\s+", " ", element.text.lower()).strip()

                    # stats
                    if all(child.name == "dd" for child in children) and len(children) > 3:
                        for child in children:
                            text = re.sub(r"\s+", " ", child.text.lower()).strip()
                            children = child.find_all(recursive=False)
                            images: list[Tag] = child.find_all("img")
                            image_alts = [
                                re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]", " ", str(img["alt"]).lower())).strip()
                                for img in images
                            ]
                            school_alts = []
                            non_school_alts = []

                            for alt in image_alts:
                                match = re.search(rf"\b{'|'.join(SCHOOLS)}|global\b", alt)
                                if match:
                                    school_alts.append(match.group())
                                else:
                                    non_school_alts.append(alt)

                            # health
                            if len(image_alts) == 1 and "health" in image_alts[0]:
                                wearable.stats.health = int(
                                    must(re.search(r"\+\s*(\d+)\s*max", text.replace(",", ""))).group(1)
                                )
                                continue

                            # energy
                            if len(image_alts) == 1 and "energy" in image_alts[0]:
                                # TODO: energy
                                # wearable.stats.energy = int(
                                #     must(re.search(r"\+\s*(\d+)\s*max", text.replace(",", ""))).group(1)
                                # )
                                continue

                            # mana
                            if len(image_alts) == 1 and "mana" in image_alts[0]:
                                # TODO: mana
                                continue

                            # healing outgoing/incoming percent
                            if (
                                len(non_school_alts) == 2
                                and "healing" in non_school_alts[1]
                                and ("incoming" in non_school_alts[0] or "outgoing" in non_school_alts[0])
                            ):
                                direction = "incoming" if "incoming" in non_school_alts[0] else "outgoing"
                                number = float(must(re.search(r"\+\s*(\d+)\s*%?", text.replace(",", ""))).group(1))

                                setattr(wearable.stats, f"{direction}_healing_percent", number)
                                continue

                            # fishing luck
                            if len(image_alts) == 1 and "fishing luck" in image_alts[0]:
                                # TODO: fishing luck
                                # wearable.stats.fishing_luck = int(
                                #     must(re.search(r"\+\s*(\d+)", text.replace(",", ""))).group(1)
                                # )
                                continue

                            # power pip
                            if len(image_alts) == 1 and "power pip" in image_alts[0]:
                                wearable.stats.power_pip_percent = int(
                                    must(re.search(r"\+\s*(\d+)", text.replace(",", ""))).group(1)
                                )
                                continue

                            # shadow pip
                            if len(image_alts) == 1 and "shadow pip" in image_alts[0]:
                                wearable.stats.shadow_pip_rating = int(
                                    must(re.search(r"\+\s*(\d+)", text.replace(",", ""))).group(1)
                                )
                                continue

                            # pierce
                            if len(non_school_alts) == 1 and "armor piercing" in non_school_alts[0]:
                                contents: list[Tag | NavigableString] = child.contents  # type: ignore
                                for school, value in parse_numeric_school_based_stat_row(
                                    contents, "armor piercing"
                                ).items():
                                    setattr(wearable.stats.pierce_percent, school, value)
                                continue

                            # accuracy
                            if len(non_school_alts) == 1 and "accuracy" in non_school_alts[0]:
                                contents: list[Tag | NavigableString] = child.contents  # type: ignore
                                for school, value in parse_numeric_school_based_stat_row(contents, "accuracy").items():
                                    setattr(wearable.stats.accuracy_percent, school, value)
                                continue

                            # critical block
                            if len(non_school_alts) == 1 and "critical block" in non_school_alts[0]:
                                contents: list[Tag | NavigableString] = child.contents  # type: ignore
                                for school, value in parse_numeric_school_based_stat_row(
                                    contents, "critical block"
                                ).items():
                                    setattr(wearable.stats.critical_block_rating, school, value)
                                continue

                            # critical
                            if len(non_school_alts) == 1 and "critical" in non_school_alts[0]:
                                contents: list[Tag | NavigableString] = child.contents  # type: ignore
                                for school, value in parse_numeric_school_based_stat_row(contents, "critical").items():
                                    setattr(wearable.stats.critical_rating, school, value)
                                continue

                            # damage percent
                            if len(non_school_alts) == 1 and "damage alternate" in non_school_alts[0]:
                                contents: list[Tag | NavigableString] = child.contents  # type: ignore
                                for school, value in parse_numeric_school_based_stat_row(contents, "damage").items():
                                    setattr(wearable.stats.damage_percent, school, value)
                                continue

                            # damage flat
                            if len(non_school_alts) == 1 and "flat damage" in non_school_alts[0]:
                                contents: list[Tag | NavigableString] = child.contents  # type: ignore
                                for school, value in parse_numeric_school_based_stat_row(contents, "damage").items():
                                    setattr(wearable.stats.damage_flat, school, value)
                                continue

                            # resistance
                            if len(non_school_alts) == 1 and "resistance" in non_school_alts[0]:
                                contents: list[Tag | NavigableString] = child.contents  # type: ignore
                                for school, value in parse_numeric_school_based_stat_row(
                                    contents, "resistance"
                                ).items():
                                    setattr(wearable.stats.resist_percent, school, value)
                                continue

                            # item card
                            if "item card" in child.text.lower():
                                # TODO: item cards
                                continue

                            # empty
                            if not text and not re.search(r"\w{5,}", repr(child)):
                                continue

                            raise Failed(f"Unknown bonuses section has content: {child!r}")
                        continue

                    # "Sockets" Label
                    if text == "sockets":
                        # the next element will contain sockets/pins
                        next_element_is_sockets = True
                        continue

                    # sockets
                    if next_element_is_sockets:
                        # TODO: PINS/SOCKETS
                        continue

                    # tradeable/auctionable
                    if text == "not tradeable" or text == "no trade" or text == "unknown trade status":
                        wearable.tradeable = False
                        continue
                    elif text == "tradeable":
                        wearable.tradeable = True
                        continue
                    elif text == "no auction" or text == "unknown auction status":
                        wearable.auctionable = False
                        continue
                    elif text == "auctionable":
                        wearable.auctionable = True
                        continue
                    elif text == "no sell":
                        # TODO: sellable?
                        continue

                    # empty
                    if not text and not re.search(r"\w{5,}", repr(element)):
                        continue

                    raise Failed(f"Unknown section has content: {element!r}")
            case "sockets_label":
                pass
            case "sockets":
                # TODO: SOCKETS
                pass
            case _:
                raise Failed(f"Unknown Stats Section! {t!r} {stats_section}")

    if not {"img_modifiers"}.issubset(set(identified_stats_sections)):
        raise Failed(f"Missing some required categories (found: {tuple(identified_stats_sections)!r})")

    return ParsingResult(value=wearable)


def main():
    # raw_site_data = db.RawSiteData.where(category__in=set(db.WearableItem.CATEGORIES) - {"mounts"}, _limit=256)
    raw_site_data = db.RawSiteData.where(category="robes")
    with ProcessPoolExecutor(max_workers=12) as executor:
        futures: dict[Future[ParsingResult], db.RawSiteData] = {}

        for i, site_data in enumerate(raw_site_data):
            if site_data.category in db.WearableItem.CATEGORIES:
                futures[executor.submit(parse_wearable, site_data)] = site_data
                print("submitted future", i + 1)

        x = list(futures.keys())
        for future in as_completed(x):
            site_data = futures.pop(future)
            try:
                result = future.result().value
            except Exception as e:
                print("ERROR WITHIN URL:", site_data.page_url)
                traceback.print_exception(e)
                break
            except:
                executor.shutdown(wait=False, cancel_futures=True)
                raise

            # if isinstance(result, db.WearableItem):
            print(f"[{len(futures)}] {result}")
