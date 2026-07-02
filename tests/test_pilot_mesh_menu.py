# Copyright (c) 2026, solvcon team <contact@solvcon.net>
# BSD 3-Clause License, see COPYING


import os
import unittest

import solvcon

try:
    from solvcon import pilot
    from solvcon.pilot import _gui, _mesh, _oblique
    from solvcon.pilot import airfoil
except ImportError:
    pilot = None

GITHUB_ACTIONS = os.getenv('GITHUB_ACTIONS', False)


def _submenus(menu):
    """Map submenu title to the child QMenu for every submenu of ``menu``."""
    return {a.text(): a.menu()
            for a in menu.actions() if a.menu() is not None}


def _leaf_texts(menu):
    """Titles of the plain (non-submenu, non-separator) actions of ``menu``."""
    return [a.text() for a in menu.actions()
            if a.menu() is None and not a.isSeparator()]


@unittest.skipIf(GITHUB_ACTIONS or not solvcon.HAS_PILOT,
                 "GUI is not available in GitHub Actions")
class MeshMenuLayoutTC(unittest.TestCase):
    """The Mesh menu groups example meshes under a "Samples" submenu and
    keeps real mesh operations at the top level (issue #985)."""

    def setUp(self):
        self.mgr = pilot.RManager.instance.setUp()
        # The RManager is a singleton that lives across tests, so reset the
        # Mesh menu before rebuilding it to keep each test deterministic.
        self.mgr.meshMenu.clear()
        self.ctrl = _gui._Controller()
        self.ctrl._rmgr = self.mgr
        self.ctrl._setup_mesh_menu()

    def _populate(self):
        _mesh.SampleMesh(mgr=self.mgr,
                         basic_menu=self.ctrl.samples_basic,
                         mixed_menu=self.ctrl.samples_mixed).populate_menu()
        _oblique.ObliqueShockMesh(
            mgr=self.mgr, menu=self.ctrl.samples_oblique).populate_menu()
        _oblique.ObliqueShockSolver(
            mgr=self.mgr, menu=self.ctrl.samples_oblique).populate_menu()
        airfoil.Naca4Airfoil(
            mgr=self.mgr, menu=self.ctrl.samples_airfoil).populate_menu()
        _mesh.RectangularDomain(mgr=self.mgr).populate_menu()

    def test_samples_submenu_categories_in_order(self):
        cats = _submenus(self.ctrl.samples_menu)
        self.assertEqual(list(cats), ["Basic shapes", "Mixed elements",
                                      "Oblique-shock reflection", "Airfoil"])

    def test_sample_items_land_in_their_category(self):
        self._populate()
        cats = _submenus(self.ctrl.samples_menu)
        self.assertEqual(_leaf_texts(cats["Basic shapes"]),
                         ["Triangle (2D)", "Tetrahedron (3D)",
                          '"solvcon" text (2D)'])
        self.assertEqual(_leaf_texts(cats["Mixed elements"]),
                         ["Small (2D)", "Larger (2D)", "3D"])
        self.assertEqual(_leaf_texts(cats["Oblique-shock reflection"]),
                         ["Quad mesh (2D)", "Triangle mesh (2D)",
                          "Unstructured mesh (2D)", "Solution: density"])
        self.assertEqual(_leaf_texts(cats["Airfoil"]), ["NACA 4-digit"])

    def test_real_operation_stays_at_top_level(self):
        self._populate()
        mesh = self.mgr.meshMenu
        self.assertTrue(any(a.isSeparator() for a in mesh.actions()))
        self.assertIn("Create triangle mesh in rectangular domain",
                      _leaf_texts(mesh))

    def test_no_sample_prefix_and_top_level_free_of_examples(self):
        self._populate()
        # Every example lives under "Samples"; none leaks to the top level.
        top_subs = _submenus(self.mgr.meshMenu)
        self.assertEqual(list(top_subs), ["Samples"])
        # The redundant "Sample:" prefix is gone from the labels.
        cats = _submenus(self.ctrl.samples_menu)
        for sub in cats.values():
            for text in _leaf_texts(sub):
                self.assertFalse(text.startswith("Sample:"), text)


@unittest.skipIf(GITHUB_ACTIONS or not solvcon.HAS_PILOT,
                 "GUI is not available in GitHub Actions")
class MeshFeatureFallbackTC(unittest.TestCase):
    """A mesh feature built without a target submenu falls back to the Mesh
    menu, so the classes stay usable in isolation."""

    def setUp(self):
        self.mgr = pilot.RManager.instance.setUp()
        self.mgr.meshMenu.clear()

    def test_oblique_mesh_defaults_to_mesh_menu(self):
        feature = _oblique.ObliqueShockMesh(mgr=self.mgr)
        self.assertIsNone(feature._menu)
        feature.populate_menu()
        self.assertEqual(_leaf_texts(self.mgr.meshMenu),
                         ["Quad mesh (2D)", "Triangle mesh (2D)",
                          "Unstructured mesh (2D)"])

    def test_sample_mesh_without_menus_uses_mesh_menu(self):
        feature = _mesh.SampleMesh(mgr=self.mgr)
        self.assertIsNone(feature._basic_menu)
        self.assertIsNone(feature._mixed_menu)
        feature.populate_menu()
        # All six samples fall back onto the Mesh menu itself.
        self.assertEqual(len(_leaf_texts(self.mgr.meshMenu)), 6)


# vim: set ff=unix fenc=utf8 et sw=4 ts=4 sts=4:
