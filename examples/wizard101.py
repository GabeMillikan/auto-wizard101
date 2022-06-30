# IGNORE THIS FILE!
# THERE IS NO NEED TO READ OR UNDERSTAND THIS FILE
# But if you're interested:
# This file makes it possible to do `import wizard101` from
# the other example files by using some less-than-ideal
# importlib hacking to import `wizard101` via its absolute path

import sys, pathlib, importlib.util

examples_folder = pathlib.Path(__file__).parent
repository_folder = examples_folder.parent
library_entry_point = repository_folder / 'wizard101' / '__init__.py'

wizard101_spec = importlib.util.spec_from_file_location('wizard101', str(library_entry_point.absolute()))
wizard101 = importlib.util.module_from_spec(wizard101_spec)
sys.modules['wizard101'] = wizard101
wizard101_spec.loader.exec_module(wizard101)
