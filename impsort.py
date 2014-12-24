#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
impsort
=======

Based on `vim-sort-python-imports <https://github.com/public/vim-sort-python-imports/blob/master/plugin/sort_imports.py>`_

TODO
----
+ [ ] Add support for shared library modules which are installed in `{exec_prefix}/lib/python{X.Y}/lib-dynload`

Links
-----
+ https://www.python.org/dev/peps/pep-0008/#imports
+ https://github.com/reddit/reddit/wiki/PythonImportGuidelines
+ https://google-styleguide.googlecode.com/svn/trunk/pyguide.html#Imports
"""
from __future__ import print_function

import argparse
import ast
import imp
import keyword
import pkgutil
import re
import sys
import tokenize
from collections import defaultdict
from distutils import sysconfig

def isidentifier(value):
    if value in keyword.kwlist:
        return False
    return re.match('^' + tokenize.Name + '$', value, re.I) is not None


class ImpSorter(ast.NodeVisitor):
    """
    This class visits all the import nodes at the root of tree
    and generates new import nodes that are sorted according to the Google
    and PEP8 coding guidelines.

    In practice this means that they are sorted according to this tuple.

        (stdlib, site_packages, names)

    We also make sure only 1 name is imported per import statement.
    """

    def __init__(self):
        self.original_nodes = []
        self.imports = set()
        self.from_imports = defaultdict(set)
        self.stdlibs = set(self.iter_stdmodules()) | set(sys.builtin_module_names) | set(['itertools', 'operator'])
        self.python_paths = [p for p in sys.path if p]

    def visit_Import(self, node):
        if node.col_offset != 0:
            return
        self.imports.update((nm.name, nm.asname) for nm in node.names)
        self.original_nodes.append(node)

    def visit_ImportFrom(self, node):
        if node.col_offset != 0:
            return
        # we need to group the names imported from each module
        # into single from X import N,M,P,... groups so we store the names
        # and regenerate the node when we find more
        # we'll then insert this into the full imports chain when we're done
        self.from_imports[(node.level, node.module)].update(
            (nm.name, nm.asname) for nm in node.names
        )
        self.original_nodes.append(node)

    @staticmethod
    def iter_stdmodules():
        stdlib_path = sysconfig.get_python_lib(standard_lib=True)
        importer = pkgutil.ImpImporter(stdlib_path)
        return (m for m, _ in importer.iter_modules())

    def is_thirdparty(self, modname):
        try:
            imp.find_module(modname, self.python_paths)
            thirdparty = True
        except ImportError:
            thirdparty = False
        return thirdparty

    # :: Node -> Key
    def _node_sort_key(self, node):
        """
        where key is a tuple of the form::

            (future, stdlib, site package, name, fromimport, from_names)
        """
        future = 1
        stdlib = 1
        thirdparty = 1
        if isinstance(node, ast.Import):
            name = [node.names[0].name, node.names[0].asname]
            from_names = None
            fromimport = 0
        elif isinstance(node, ast.ImportFrom):
            name = [node.module]
            from_names = [nm.name for nm in node.names]
            fromimport = 1
        else:
            raise TypeError(node)
        modname = name[0].split('.')[0]
        if modname == '__future__':
            future = 0
        elif modname in self.stdlibs:
            stdlib = 0
        elif self.is_thirdparty(modname):
            thirdparty = 0
        return (future, stdlib, thirdparty, fromimport, name, from_names)

    def new_nodes(self):
        """
        Generate a list of tuples with the form `(Key, Node)`.
        """
        nodes = []
        for (level, module), names in self.from_imports.items():
            for nm, asnm in sorted(names):
                node = ast.ImportFrom(
                    module=module,
                    names=[ast.alias(name=nm, asname=asnm)],
                    level=level
                )
                nodes.append((self._node_sort_key(node), node))
        for nm, asnm in self.imports:
            node = ast.Import(names=[ast.alias(name=nm, asname=asnm)])
            nodes.append((self._node_sort_key(node), node))
        return nodes

    def write_sorted(self, file=sys.stdout):
        """
        Write sorted imports to file.

        file: a file-like object (stream).
        """
        pkey = None
        for key, node in sorted(self.new_nodes()):
            # insert new lines between groups
            if pkey and key[:3] != pkey[:3]:
                print(u'', file=file)
            pkey = key

            # names here will actually always only have 1 element in it
            # because we are only allowed 1 per line, but it's easy
            # enough to cope with multiple anyway.
            all_names = ', '.join(
                (' as '.join(nm for nm in (name.name, name.asname) if nm))
                for name in node.names
            )

            if isinstance(node, ast.Import):
                print(u'import {0}'.format(all_names), file=file)
            elif isinstance(node, ast.ImportFrom):
                print(u'from {0}{1} import {2}'.format('.' * node.level, node.module, all_names), file=file)


def main():
    parser = argparse.ArgumentParser(description="Python sort imports.")
    parser.add_argument('infile', nargs='?', type=argparse.FileType('r'),
                        default=sys.stdin)
    parser.add_argument('outfile', nargs='?', type=argparse.FileType('w'),
                        default=sys.stdout)

    args = parser.parse_args()
    with args.infile as infile, args.outfile as outfile:
        tree = ast.parse(infile.read())
        i = ImpSorter()
        i.visit(tree)
        i.write_sorted(outfile)


if __name__ == '__main__':
    main()