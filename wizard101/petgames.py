from wizard101 import util
import time, keyboard

class DanceGameSolver:
    def __init__(self):
        self.templates = {
            "down": util.img_resource("dance_down.png"),
            "right": util.img_resource("dance_right.png"),
            "up": util.img_resource("dance_up.png"),
            "left": util.img_resource("dance_left.png"),
            "empty": util.img_resource("dance_empty.png"),
        }
        
        self.maxTemplateSize = [0, 0] # x, y
        for k, img in self.templates.items():
            self.maxTemplateSize[0] = max(self.maxTemplateSize[0], img.shape[1])
            self.maxTemplateSize[1] = max(self.maxTemplateSize[1], img.shape[0])
        
        self.known_location = [xy / 2.0 for xy in self.maxTemplateSize] # x, y CENTER!!
        self.da = util.DesktopAutomator()
        
        self.state = None
        self.last_state = None
        self.time_state_changed = 0
        self.printed_not_found = False
        
        self.sequence = None
    
    def change_state(self, new_state):
        self.last_state = self.state
        self.state = new_state
        self.time_state_changed = time.time()
    
    def loop(self):
        [cx, cy] = self.known_location
        [w, h] = self.maxTemplateSize
        ox, oy = int(cx + 0.5 - w / 2 - 10), int(cy + 0.5 - h / 2 - 10)
        src = self.da.grab(ox, oy, w + 20, h + 20)
        
        # figure out which template is in the image
        d = []
        for k, img in self.templates.items():
            d.append([k, *self.da.find_in_image(src, img)])
        
        d.sort(key = lambda x: x[-1])
        [k, x, y, t] = d[0]
        x += ox
        y += oy
        
        if t > 0.01:
            if self.state == None:
                if time.time() - self.time_state_changed > 1: # found nothing for 1 second... user moved window or closed pet game
                    self.time_state_changed = time.time() # reset the timer as to only search every 1 second
                    self.sequence = None # cancel any sequence
                    
                    fullscreen = self.da.grab_fullscreen()
                    empty = self.templates["empty"]
                    
                    w, h, _ = empty.shape
                    x, y, t = self.da.find_in_image(fullscreen, empty)
                    if t < 0.01: # FOUND!
                        print("Found game window! Now tracking dance sequences.")
                        self.known_location = [x + w / 2, y + h / 2]
                        self.change_state("empty")
                    elif not self.printed_not_found: # not found
                        print("Waiting for you to enter the dance game... Make sure you're playing in 1280x720 resolution. (prefer no fullscreen)")
                        self.printed_not_found = True
                else:
                    pass # failed to find 
            else:
                self.change_state(None)
        elif k != self.state and k in ["down", "right", "up", "left"]:
            if self.sequence == None:
                self.sequence = []
            self.sequence.append(k)
            print("Remember:", k)
        elif k == "empty" and k == self.state and time.time() - self.time_state_changed > 1 and self.sequence != None and len(self.sequence) >= 3:
            print("Entering full sequence:", ", ".join(self.sequence))
            for dir in self.sequence:
                keyboard.press_and_release(dir)
                time.sleep(0.01)
            self.sequence = None
        
        if t <= 0.01 and k != self.state:
            self.printed_not_found = False
            self.change_state(k)
