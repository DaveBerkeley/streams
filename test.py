#! /bin/env python3

import sys
import os
import importlib

dirname = "tests"

sys.path.append(dirname)

def get_tests(dirname):
    names = []
    for fname in os.listdir(dirname):
        if not fname.startswith("test_"):
            continue
        if not fname.endswith(".py"):
            continue
        names.append(fname)
    return names

for fname in get_tests(dirname):
    name = dirname + "." + fname[:-3]
    print("run", name)
    m = importlib.import_module(name)
    m.test(verbose=True)

#   FIN
