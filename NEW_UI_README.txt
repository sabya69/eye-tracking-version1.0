NEUMORPHIC + GLASS UI  --  what changed
=======================================
Copy everything in this folder over your project folder (same names, nothing else touched).
Then:  pip install -r requirements.txt     (adds pillow)

NEW FILES
  neo_ui.py   shared kit: raised/pressed buttons, inset text wells, frosted glass panels/cards, keyboard
  neo_cv.py   same look for the OpenCV windows

UPDATED FILES
  launcher.py, emergency.py, keyboardaccuracy.py   -> new look, new keyboard
  virtual_keyboard.py, text_pad.py                  -> OpenCV gaze keyboard / text pad restyled
  requirements.txt                                  -> + pillow

DELETE KEY
  "Delete" (wipes ALL text) is no longer next to Space / arrows.
  It is now "Clear all", alone in the top-right corner, and needs a SECOND tap
  (within 3 s) to actually clear.  Tap any other key and it cancels.
  OpenCV gaze keyboard: first dwell arms it; you must look away and dwell again.
  One-tap behaviour:  neo_ui.py -> CONFIRM_CLEAR_ALL = False
                      virtual_keyboard.py -> CLEAR_CONFIRM = False

NOTES
  * Fixation-cross and memorise screens use a plain flat background on purpose (stimulus screens).
  * Experiment logging is unchanged (it reads text changes, so Clear all still counts as backspaces).
  * Colours still follow THEME_MODE in theme.py.
