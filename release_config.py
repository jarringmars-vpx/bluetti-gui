"""Build-time release feature switches.

The normal source checkout keeps every backend available. The Community-only
PyInstaller build overrides BLUETTI_COMMUNITY_RELEASE at build/run time and
also excludes the Official backend module from the frozen application.
"""

import os

COMMUNITY_ONLY = os.environ.get("BLUETTI_COMMUNITY_RELEASE", "0") == "1"
