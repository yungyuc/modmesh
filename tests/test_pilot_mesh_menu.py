# Copyright (c) 2026, solvcon team <contact@solvcon.net>
# BSD 3-Clause License, see COPYING


import os
import unittest

import solvcon

try:
    from solvcon import pilot
    from solvcon.pilot import _mesh, _oblique
    from solvcon.pilot import airfoil
    from PySide6.QtCore import Qt
except ImportError:
    pilot = None

GITHUB_ACTIONS = os.getenv('GITHUB_ACTIONS', False)


def _leaf_texts(menu):
    """Titles of the plain (non-submenu, non-separator) actions of ``menu``."""
    return [a.text() for a in menu.actions()
            if a.menu() is None and not a.isSeparator()]


@unittest.skipIf(GITHUB_ACTIONS or not solvcon.HAS_PILOT,
                 "GUI is not available in GitHub Actions")
class MeshSampleDialogTC(unittest.TestCase):
    """The example meshes live behind one "Sample mesh..." dialog that lists
    them grouped by category and creates the selected one (issue #985)."""

    def setUp(self):
        self.mgr = pilot.RManager.instance.setUp()
        # The RManager singleton lives across tests, so reset the Mesh menu.
        self.mgr.meshMenu.clear()
        # Keep the feature instances referenced: the dialog stores their
        # bound methods and invokes them to build meshes.
        self.sm = _mesh.SampleMesh(mgr=self.mgr)
        self.osm = _oblique.ObliqueShockMesh(mgr=self.mgr)
        self.oss = _oblique.ObliqueShockSolver(mgr=self.mgr)
        self.naca = airfoil.Naca4Airfoil(mgr=self.mgr)
        self.entries = (self.sm.sample_entries() + self.osm.sample_entries()
                        + self.oss.sample_entries()
                        + self.naca.sample_entries())
        self.dialog = _mesh.SampleMeshDialog(mgr=self.mgr,
                                             entries=self.entries)

    def test_every_example_is_gathered(self):
        # 6 basic/mixed + 3 oblique meshes + 1 oblique solution + 1 airfoil;
        # a dropped feature would change this count.
        self.assertEqual(len(self.entries), 11)

    def test_menu_shows_only_the_dialog_item(self):
        self.dialog.populate_menu()
        self.assertEqual(_leaf_texts(self.mgr.meshMenu), ["Sample mesh..."])

    def test_dialog_groups_entries_by_category(self):
        self.dialog._build_dialog()
        tree = self.dialog._tree
        cats = [tree.topLevelItem(i).text(0)
                for i in range(tree.topLevelItemCount())]
        self.assertEqual(cats, ["Basic shapes", "Mixed elements",
                                "Oblique-shock reflection", "Airfoil"])
        counts = [tree.topLevelItem(i).childCount()
                  for i in range(tree.topLevelItemCount())]
        self.assertEqual(counts, [3, 3, 4, 1])

    def test_category_rows_are_not_creatable(self):
        self.dialog._build_dialog()
        group = self.dialog._tree.topLevelItem(0)
        self.assertIsNone(group.data(0, Qt.UserRole))
        self.assertFalse(bool(group.flags() & Qt.ItemIsSelectable))

    def test_create_selected_builds_the_mesh(self):
        self.dialog._build_dialog()
        leaf = self.dialog._tree.topLevelItem(0).child(0)
        # "Triangle (2D)" is the first leaf; creating it opens a 3D viewer
        # holding the 3-cell triangle mesh.
        self.assertEqual(leaf.text(0), "Triangle (2D)")
        self.dialog._invoke(leaf)
        current = self.mgr.currentR3DWidget()
        self.assertIsNotNone(current)
        self.assertIsNotNone(current.mesh)
        self.assertEqual(current.mesh.ncell, 3)

    def test_invoke_ignores_none_and_category_rows(self):
        # The guard keeps a null selection or a category header inert; without
        # it, item.data(None) or calling a None creator would raise.
        self.dialog._build_dialog()
        category = self.dialog._tree.topLevelItem(0)
        self.assertIsNone(self.dialog._invoke(None))
        self.assertIsNone(self.dialog._invoke(category))


@unittest.skipIf(GITHUB_ACTIONS or not solvcon.HAS_PILOT,
                 "GUI is not available in GitHub Actions")
class MeshMenuAssemblyTC(unittest.TestCase):
    """The Mesh menu top level: the sample dialog, a separator, then the real
    mesh operation."""

    def setUp(self):
        self.mgr = pilot.RManager.instance.setUp()
        self.mgr.meshMenu.clear()

    def test_top_level_layout(self):
        _mesh.SampleMeshDialog(mgr=self.mgr, entries=[]).populate_menu()
        self.mgr.meshMenu.addSeparator()
        _mesh.RectangularDomain(mgr=self.mgr).populate_menu()
        acts = self.mgr.meshMenu.actions()
        self.assertEqual(len(acts), 3)
        self.assertEqual(acts[0].text(), "Sample mesh...")
        self.assertTrue(acts[1].isSeparator())
        self.assertEqual(acts[2].text(),
                         "Create triangle mesh in rectangular domain")
        # No example mesh leaks onto the top level.
        self.assertNotIn("Triangle (2D)", _leaf_texts(self.mgr.meshMenu))


# vim: set ff=unix fenc=utf8 et sw=4 ts=4 sts=4:
