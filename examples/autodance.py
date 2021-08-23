print("Python is running! Hold on...")

from wizard101 import petgames as pg
print("Imported wizard101 pet games automator.")

dgs = pg.DanceGameSolver()
print("Ready to solve the dance game. Press 'E' or 'CTRL' to quit.")

import keyboard
while not keyboard.is_pressed('e') and not keyboard.is_pressed('ctrl'):
    dgs.loop()

# long quit
import time
for t in range(3, 0, -1):
    print("You pressed 'E' or 'CTRL'. Quitting in %d second(s)." % t, end = "    \r")
    time.sleep(1)
quit()