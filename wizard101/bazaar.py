from wizard101 import util
import time, cv2
import numpy as np
import PIL.Image, PIL.ImageFont, PIL.ImageDraw
import pytesseract
from thefuzz import fuzz
import re
from threading import Thread
from dataclasses import dataclass


class AutoBuyer:
    @dataclass
    class Resources:
        reagents_tab: np.ndarray
        snacks_tab: np.ndarray

        banner: np.ndarray
        selected_bazaar_tab: np.ndarray
        next_page: np.ndarray
        loading_banner: np.ndarray
        ok: np.ndarray

        font: PIL.ImageFont.FreeTypeFont

    def __init__(self, search: str):
        self.resources = AutoBuyer.Resources(
            reagents_tab=util.img_resource("reagents_tab.png"),
            snacks_tab=util.img_resource("snacks_tab.png"),
            banner=util.img_resource("bazaar_banner.png"),
            selected_bazaar_tab=util.img_resource("selected_bazaar_tab.png"),
            next_page=util.img_resource("next_page.png"),
            loading_banner=util.img_resource("loading_banner.png"),
            ok=util.img_resource("ok.png"),
            font=util.font_resource("font.ttf", 48),
        )

        self.da = util.DesktopAutomator()
        self.state = ""
        self.raw_search = search
        self.search = "".join(search.split()).lower()
        self.search_words = [self.generate_text(word.capitalize()) for word in search.split()]

    def change_state(self, new_state: str) -> bool:
        if new_state == self.state:
            return False
        else:
            self.state = new_state
            print(new_state)
            return True

    def generate_text(self, text: str) -> np.ndarray:
        left, top, right, bottom = self.resources.font.getbbox(text, anchor="lt")
        width, height = right - left, bottom - top

        img = PIL.Image.new("RGBA", (width, height), (0, 0, 0, 0))

        drawer = PIL.ImageDraw.Draw(img)
        drawer.text((0, 0), text, (0, 255, 255, 255), font=self.resources.font, anchor="lt")

        img = PIL.Image.fromarray(cv2.erode(np.array(img), np.ones((5, 5), np.uint8), iterations=1))

        img = img.resize((int(img.size[0] * 1.333), img.size[1]))
        r = 13 / img.size[1]
        img = img.resize((int(img.size[0] * r), int(img.size[1] * r)))

        return np.array(img)

    def rate_similarity(self, a: str, b: str) -> int:
        return fuzz.ratio(a, b)

    def threaded_determine_candidate(
        self, index: int, text_image: np.ndarray, output: dict[int, dict[str, int | str]]
    ) -> None:
        text_image = cv2.copyMakeBorder(
            text_image, top=5, bottom=5, left=5, right=5, borderType=cv2.BORDER_CONSTANT, value=(0, 0, 0, 0)
        )
        candidates: list[str | None] = []

        candidates.append(pytesseract.image_to_string(text_image))
        text_image = cv2.erode(text_image, np.ones((1, 1), "uint8"))
        candidates.append(pytesseract.image_to_string(text_image))

        candidates = [re.sub(r"[^a-z]", "", "".join(c.split()).lower()) for c in candidates if c]
        filtered_candidates = [c for c in candidates if c]
        if filtered_candidates:
            score, best_candidate = max(
                (self.rate_similarity(candidate, self.search), candidate) for candidate in filtered_candidates
            )
            if best_candidate:
                print(f"recognized {best_candidate!r} which is a {score:.0f}% match")
                output[index] = {
                    "score": score,
                    "best_candidate": best_candidate,
                }

        output[index] = {
            "score": 0,
            "best_candidate": "unknown",
        }

    def loop(self) -> None:
        fullscreen_image = self.da.grab_fullscreen()
        banner_x, banner_y, banner_match_diff = self.da.find_in_image(fullscreen_image, self.resources.banner)

        if banner_match_diff > 0.01:
            self.change_state("Please open the bazaar")
            return
        else:
            self.change_state("Bazaar located!")

        store_x, store_y = banner_x - 430, banner_y
        store_width, store_height = 740, 550
        store_rect = (store_x, store_y, store_width, store_height)
        store_image = fullscreen_image[store_y : store_y + store_height, store_x : store_x + store_width]

        tab_height, tab_width, *_ = self.resources.selected_bazaar_tab.shape
        tab_x, tab_y, tab_match_diff = self.da.find_in_image(store_image, self.resources.selected_bazaar_tab)
        if tab_match_diff > 0.01:
            self.change_state("Please go to the tab you would like to farm")
            return
        else:
            self.change_state("Tab located!")

        # refresh the page
        self.change_state("Refreshing list...")
        self.da.click(store_x + tab_x + tab_width // 2, store_y + tab_y + tab_height // 2)

        # wait for it to load
        loading_banner_diff = 0
        while loading_banner_diff < 0.01:
            time.sleep(0.5)
            store_image = self.da.grab(*store_rect)
            _, _, loading_banner_diff = self.da.find_in_image(store_image, self.resources.loading_banner)

        self.change_state(f"Looking for {self.raw_search!r}...")

        if self.search[0] > "m":
            # better off sorting back to front
            self.da.click(store_x + 371, store_y + 157)

        while True:
            store_image = self.da.grab(*store_rect)
            name_list_image = store_image[170:440, 246:496]
            name_list_threshold = cv2.inRange(
                name_list_image,
                (0, 200, 200, 0),  # type: ignore
                (255, 255, 255, 255),  # type: ignore
            )
            name_list_image = cv2.bitwise_and(name_list_image, name_list_image, mask=name_list_threshold)

            found_items = {}
            threads = []
            for i in range(10):
                y = i * 27
                text_image = name_list_image[y + 3 : y + 22, :]
                t = Thread(target=self.threaded_determine_candidate, args=(i, text_image, found_items))
                t.start()
                threads.append(t)

            for t in threads:
                t.join()

            best_score, best_index = None, None
            for i, item in found_items.items():
                if best_score is None or item["score"] > best_score:
                    best_score, best_index = item["score"], i

            assert best_index is not None and best_score is not None

            if best_score > 70:
                self.change_state("Found it! Puchasing...")
                self.da.click(store_x + 371, store_y + 170 + int(27 * (best_index + 0.5)))
                self.da.click(store_x + 195, store_y + 495)
                self.da.drag(store_x + 359, store_y + 349, store_x + 530, store_y + 349)
                self.da.click(store_x + 270, store_y + 480)

                ok_x, ok_y, ok_diff = 0, 0, 1
                while ok_diff > 0.05:
                    print(ok_x, ok_y, ok_diff)
                    time.sleep(0.5)
                    store_image = self.da.grab(*store_rect)
                    ok_x, ok_y, ok_diff = self.da.find_in_image(store_image, self.resources.ok)

                ok_height, ok_width, *_ = self.resources.ok.shape
                self.da.click(store_x + ok_x + ok_width // 2, store_y + ok_y + ok_height // 2)
                self.change_state("Purchased!")
                time.sleep(1)
                break
            else:
                next_x, next_y, next_match_diff = self.da.find_in_image(store_image, self.resources.next_page)
                if next_match_diff > 0.01:
                    break

                h, w, *_ = self.resources.next_page.shape
                self.da.click(store_x + next_x + h // 2, store_y + next_y + w // 2)
