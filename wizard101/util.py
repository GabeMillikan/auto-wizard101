import cv2, mss
import numpy as np
import pathlib
from PIL import ImageFont
import mouse
import time
fileroot = pathlib.Path(__file__).parent

class DesktopAutomator:
    def __init__(self):
        self.sct = mss.mss()
    
    def __del__(self):
        try:
            del self.sct
        except:
            pass
    
    def grab_monitor(self, mon):
        return np.array(self.sct.grab(mon))
    
    def grab(self, x, y, w, h):
        return self.grab_monitor({"top": y, "left": x, "width": w, "height": h})
    
    def grab_fullscreen(self):
        return self.grab_monitor(self.sct.monitors[0])
    
    def find_in_image(self, image, template):
        mask = None
        
        if template.shape[-1] == 4: # has alpha, use mask
            if str(template.dtype).startswith("float"):
                if template.dtype == "float32":
                    mask = template[:, :, 3:]
                else:
                    mask = np.float32(template[:, :, 3:])
            else:
                mask = template[:, :, 3:] / np.float32(255)
            
            if image.shape[-1] == 3: # image has no alpha, but template does. Add alpha to image
                opaque = np.uint8(255)
                if str(image.dtype).startswith("float"):
                    opaque = np.float32(1)
                
                image = numpy.dstack((image.copy(), numpy.full(image.shape[:2], opaque)))
        else:
            if image.shape[-1] == 4: # image has alpha but template does not, strip alpha from image
                image = image.copy()[:, :, :3]
        
        match = cv2.matchTemplate(image, template, cv2.TM_SQDIFF_NORMED, None, mask)
        minv, maxv, minloc, maxloc = cv2.minMaxLoc(match)
        
        return minloc[0], minloc[1], minv
    
    def image_contains(self, img, other, maxDifference):
        x, y, t = self.find_in_image(img, other)
        return t < maxDifference
    
    def move(self, x, y):
        _x, _y = mouse.get_position()
        mouse.move(x, y, duration=0.05)
        time.sleep(0.05)
        return _x, _y
    
    def click(self, x, y):
        _op = self.move(x, y)
        mouse.press()
        time.sleep(0.05)
        mouse.release()
        time.sleep(0.01)
        self.move(*_op)
    
    def drag(self, x1, y1, x2, y2):
        _op = self.move(x1, y1)
        mouse.press()
        time.sleep(0.05)
        self.move(x2, y2)
        time.sleep(0.01)
        mouse.release()
        self.move(*_op)

def img_resource(name):
    fpath = str(fileroot / "resource" / name)
    return cv2.imread(fpath, cv2.IMREAD_UNCHANGED)

def font_resource(name, size):
    fpath = str(fileroot / "resource" / name)
    return ImageFont.truetype(fpath, size)
