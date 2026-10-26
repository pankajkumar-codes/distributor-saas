import os

# Unset PLATFORM_ENV fails closed (QA-DEF-004), so the suite names its environment, as CI does.
os.environ["PLATFORM_ENV"] = "test"
