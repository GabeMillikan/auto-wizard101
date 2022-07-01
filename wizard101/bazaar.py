from wizard101 import util
import time, cv2
import numpy as np
import PIL.Image, PIL.ImageFont, PIL.ImageDraw
import pytesseract
from thefuzz import fuzz
import re

class AutoBuyer:
    def __init__(self, search):
        self.templates = {
            "tabs": {
                "reagents": util.img_resource("reagents_tab.png"),
                "snacks": util.img_resource("snacks_tab.png"),
            },
            "banner": util.img_resource("bazaar_banner.png"),
            "selected_bazaar_tab": util.img_resource("selected_bazaar_tab.png"),
            "next_page": util.img_resource("next_page.png"),
            "loading_banner": util.img_resource("loading_banner.png"),
            "ok": util.img_resource("ok.png"),
            "font": util.font_resource("font.ttf", 48),
        }
        
        self.da = util.DesktopAutomator()
        self.state = ""
        self.raw_search = search
        self.search = "".join(search.split()).lower()
        self.search_words = [self.generate_text(word.capitalize()) for word in search.split()]
    
    def change_state(self, new_state):
        if new_state == self.state:
            return False
        else:
            self.state = new_state
            print(new_state)
            return True
    
    def generate_text(self, text):
        left, top, right, bottom = self.templates["font"].getbbox(text, anchor='lt')
        width, height = right - left, bottom - top
        
        img = PIL.Image.new(
            'RGBA',
            (width, height),
            (0, 0, 0, 0)
        )
        
        drawer = PIL.ImageDraw.Draw(img)
        drawer.text((0, 0), text, (0, 255, 255, 255), font=self.templates["font"], anchor='lt')
        
        img = PIL.Image.fromarray(cv2.erode(np.array(img), np.ones((5,5), np.uint8), iterations=1))
        
        img = img.resize((int(img.size[0] * 1.333), img.size[1]))
        r = 13 / img.size[1]
        img = img.resize((int(img.size[0] * r), int(img.size[1] * r)))
        
        return np.array(img)
    
    def rate_similarity(self, a, b):
        return fuzz.ratio(a, b)
    
    def threaded_determine_candidate(self, index, text_image, output):
        text_image = cv2.copyMakeBorder(
            text_image,
            top=5,
            bottom=5,
            left=5,
            right=5,
            borderType=cv2.BORDER_CONSTANT,
            value=(0, 0, 0, 0)
        )
        candidates = []
        
        candidates.append(pytesseract.image_to_string(text_image))
        text_image = cv2.erode(text_image, np.ones((1, 1), 'uint8'))
        candidates.append(pytesseract.image_to_string(text_image))
        
        candidates = [re.sub(r"[^a-z]", "", "".join(c.split()).lower()) for c in candidates]
        candidates = [c for c in candidates if c]
        if not candidates:
            output[i] = {
                "score": 0,
                "best_candidate": "unknown",
            }
            return
        
        score, best_candidate = max((self.rate_similarity(candidate, self.search), candidate) for candidate in candidates)
        
        output[i] = {
            "score": score,
            "best_candidate": best_candidate,
        }
    
    def loop(self):
        fullscreen_image = self.da.grab_fullscreen()
        banner_x, banner_y, banner_match_diff = self.da.find_in_image(fullscreen_image, self.templates["banner"])
        
        if banner_match_diff > 0.01:
            return self.change_state("Please open the bazaar")
        else:
            self.change_state("Bazaar located!")
            
        store_x, store_y = banner_x - 430, banner_y
        store_width, store_height = 740, 550
        store_rect = (store_x, store_y, store_width, store_height)
        store_image = fullscreen_image[store_y:store_y+store_height, store_x:store_x+store_width]
        
        tab_height, tab_width, *_ = self.templates["selected_bazaar_tab"].shape
        tab_x, tab_y, tab_match_diff = self.da.find_in_image(store_image, self.templates["selected_bazaar_tab"])
        if tab_match_diff > 0.01:
            return self.change_state("Please go to the tab you would like to farm")
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
            _, _, loading_banner_diff = self.da.find_in_image(store_image, self.templates["loading_banner"])

        self.change_state(f"Looking for {self.raw_search!r}...")
        
        if self.search[0] > "m":
            # better off sorting back to front
            self.da.click(store_x + 371, store_y + 157)
        
        while True:
            store_image = self.da.grab(*store_rect)
            name_list_image = store_image[170:440, 246:496]
            name_list_threshold = cv2.inRange(
                name_list_image,
                (0, 200, 200, 0),
                (255, 255, 255, 255)
            )
            name_list_image = cv2.bitwise_and(name_list_image, name_list_image, mask=name_list_threshold)
            
            found = None
            for i in range(10):
                y = i * 27
                text_image = name_list_image[y+3:y+22, :]
                text_image = cv2.copyMakeBorder(
                    text_image,
                    top=5,
                    bottom=5,
                    left=5,
                    right=5,
                    borderType=cv2.BORDER_CONSTANT,
                    value=(0, 0, 0, 0)
                )
                candidates = []
                
                candidates.append(pytesseract.image_to_string(text_image))
                text_image = cv2.erode(text_image, np.ones((1, 1), 'uint8'))
                candidates.append(pytesseract.image_to_string(text_image))
                
                candidates = [re.sub(r"[^a-z]", "", "".join(c.split()).lower()) for c in candidates]
                candidates = [c for c in candidates if c]
                if not candidates:
                    continue
                
                score, best_candidate = max((self.rate_similarity(candidate, self.search), candidate) for candidate in candidates)
                print(f"recognized {best_candidate!r} which is a {score:.0f}% match")
                if score > 70:
                    found = i
                    break
            
            if found is not None:
                self.change_state("Found it! Puchasing...")
                self.da.click(store_x + 371, store_y + 170 + int(27 * (i + 0.5)))
                self.da.click(store_x + 195, store_y + 495)
                self.da.drag(
                    store_x + 359, store_y + 349,
                    store_x + 530, store_y + 349
                )
                self.da.click(store_x + 270, store_y + 480)
                
                ok_x, ok_y, ok_diff = 0, 0, 0
                while ok_diff < 0.01:
                    time.sleep(0.5)
                    store_image = self.da.grab(*store_rect)
                    ok_x, ok_y, ok_diff = self.da.find_in_image(store_image, self.templates["ok"])

                ok_height, ok_width, *_ = self.templates["ok"].shape
                self.da.click(store_x + ok_x + ok_width // 2, store_y + ok_y + ok_height // 2)
                self.change_state("Purchased!")
                time.sleep(1)
                break
            else:
                next_x, next_y, next_match_diff = self.da.find_in_image(store_image, self.templates["next_page"])
                if next_match_diff > 0.01:
                    break
                
                h, w, *_ = self.templates["next_page"].shape
                self.da.click(store_x + next_x + h // 2, store_y + next_y + w // 2)
