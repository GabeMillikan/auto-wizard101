import cv2, mss
import numpy as np
import pathlib
from PIL import ImageFont
import mouse
import time
import sqlite3

file_root = pathlib.Path(__file__).parent


class DesktopAutomator:
    def __init__(self):
        self.sct = mss.mss()

    def __del__(self):
        try:
            del self.sct
        except:
            pass

    def grab_monitor(self, mon) -> np.ndarray:
        return np.array(self.sct.grab(mon))

    def grab(self, x: int | float, y: int | float, w: int | float, h: int | float) -> np.ndarray:
        return self.grab_monitor({"top": y, "left": x, "width": w, "height": h})

    def grab_fullscreen(self) -> np.ndarray:
        return self.grab_monitor(self.sct.monitors[0])

    def find_in_image(self, image: np.ndarray, template: np.ndarray) -> tuple[int, int, float]:
        mask = None

        if template.shape[-1] == 4:  # has alpha, use mask
            if str(template.dtype).startswith("float"):
                if template.dtype == "float32":
                    mask = template[:, :, 3:]
                else:
                    mask = np.float32(template[:, :, 3:])
            else:
                mask = template[:, :, 3:] / np.float32(255)

            if image.shape[-1] == 3:  # image has no alpha, but template does. Add alpha to image
                opaque = np.uint8(255)
                if str(image.dtype).startswith("float"):
                    opaque = np.float32(1)

                image = np.dstack((image.copy(), np.full(image.shape[:2], opaque)))
        else:
            if image.shape[-1] == 4:  # image has alpha but template does not, strip alpha from image
                image = image.copy()[:, :, :3]

        match = cv2.matchTemplate(image, template, cv2.TM_SQDIFF_NORMED, None, mask)  # type: ignore
        min_value, max_value, min_loc, max_loc = cv2.minMaxLoc(match)

        return min_loc[0], min_loc[1], min_value

    def image_contains(self, img: np.ndarray, other: np.ndarray, maxDifference: int | float) -> bool:
        x, y, t = self.find_in_image(img, other)
        return t < maxDifference

    def move(self, x: float | int, y: float | int) -> tuple[int, int]:
        _x, _y = mouse.get_position()
        mouse.move(x, y, duration=0.05)  # type: ignore because duration is not an int
        time.sleep(0.05)
        return _x, _y

    def click(self, x: float | int, y: float | int) -> None:
        _op = self.move(x, y)
        mouse.press()
        time.sleep(0.05)
        mouse.release()
        time.sleep(0.01)
        self.move(*_op)

    def drag(self, x1: float | int, y1: float | int, x2: float | int, y2: float | int) -> None:
        _op = self.move(x1, y1)
        mouse.press()
        time.sleep(0.05)
        self.move(x2, y2)
        time.sleep(0.01)
        mouse.release()
        self.move(*_op)


def img_resource(name: str) -> np.ndarray:
    fpath = str(file_root / "resource" / name)
    return cv2.imread(fpath, cv2.IMREAD_UNCHANGED)


def font_resource(name: str, size: int) -> ImageFont.FreeTypeFont:
    fpath = str(file_root / "resource" / name)
    return ImageFont.truetype(fpath, size)


def database_resource(name: str) -> sqlite3.Connection:
    fpath = str(file_root / "resource" / name)
    return sqlite3.connect(fpath)
