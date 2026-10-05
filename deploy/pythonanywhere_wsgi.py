# PythonAnywhere WSGI file for Bullion Register.
#
# Copy everything below into the WSGI configuration file that PythonAnywhere
# shows on the Web tab (the link next to "WSGI configuration file"), replacing
# what is there. Then change the three lines marked CHANGE ME and press Reload.
#
# This file lives only on PythonAnywhere, never on GitHub, so your password stays private.

import os
import sys

USERNAME = "your-pythonanywhere-username"            # CHANGE ME
project = f"/home/{USERNAME}/BULLION-REGISTER"
if project not in sys.path:
    sys.path.insert(0, project)

# Owner account for the cloud copy. Used only to create the account the very first time.
os.environ["ADMIN_USERNAME"] = "choose-a-username"     # CHANGE ME
os.environ["ADMIN_PASSWORD"] = "choose-a-strong-password"  # CHANGE ME (12+ characters)

os.environ["COOKIE_SECURE"] = "1"   # the site is served over https
os.environ["BEHIND_PROXY"] = "1"    # PythonAnywhere's front server passes on the visitor's address

from wsgi import app as application  # noqa: E402,F401
