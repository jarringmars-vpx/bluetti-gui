"""PyInstaller runtime hook for the Community-only public build."""
import os
os.environ["BLUETTI_COMMUNITY_RELEASE"] = "1"
