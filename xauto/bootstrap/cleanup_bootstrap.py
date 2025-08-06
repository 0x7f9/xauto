#!/usr/bin/env python3

# run clean up with:
# python -m xauto.bootstrap.cleanup_bootstrap

# or 

# cd xauto_root\xauto\bootstrap
# python cleanup_bootstrap.py

import sys 
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from xauto.bootstrap.build import cleanup_bootstrap


print("Cleaning up bootstrap...")
cleanup_bootstrap()
print("Done.")

