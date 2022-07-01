print("Python is running! Hold on...")

from wizard101 import bazaar
print("Imported wizard101 bazaar automator.")

ab = bazaar.AutoBuyer(input("What are you looking for?\n> "))
print("Ready to autobuy. Hold 'E' or 'CTRL' to quit.")

import keyboard
while not keyboard.is_pressed('e') and not keyboard.is_pressed('ctrl'):
    ab.loop()
