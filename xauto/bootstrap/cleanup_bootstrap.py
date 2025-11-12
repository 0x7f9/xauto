#!/usr/bin/env python3

# run clean up with:

# cd xauto_root
# python xauto/bootstrap/cleanup_bootstrap.py

import sys 
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from xauto.bootstrap.build import cleanup_bootstrap


print("Cleaning up bootstrap...")
cleanup_bootstrap()
print("Done.")

