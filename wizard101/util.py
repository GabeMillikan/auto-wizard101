from sys import platform
import mss
import numpy as np
import cv2, mss
import pathlib
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
    
    def find_in_image(self, img, other):
        mask = None
        
        if other.shape[-1] == 4: # has alpha, use mask
            if str(other.dtype).startswith("float"):
                if other.dtype == "float32":
                    mask = other[:, :, 3:]
                else:
                    mask = np.float32(other[:, :, 3:])
            else:
                mask = other[:, :, 3:] / np.float32(255)
            
            if img.shape[-1] == 3: # img has no alpha, but other does. Add alpha to image
                opaque = np.uint8(255)
                if str(img.dtype).startswith("float"):
                    opaque = np.float32(1)
                
                img = numpy.dstack((img.copy(), numpy.full(img.shape[:2], opaque)))
        else:
            if img.shape[-1] == 4: # img has alpha but other does not, strip alpha from img
                img = img.copy()[:, :, :3]
        
        
        match = cv2.matchTemplate(img, other, cv2.TM_SQDIFF_NORMED, None, mask)
        minv, maxv, minloc, maxloc = cv2.minMaxLoc(match)
        
        return minloc[0], minloc[1], minv
    
    def image_contains(self, img, other, maxDifference):
        x, y, t = self.find_in_image(img, other)
        return t < maxDifference

def img_resource(name):
    fpath = str(fileroot / "resource" / name)
    return cv2.imread(fpath, cv2.IMREAD_UNCHANGED)