#include <modmesh/inout/pymod/inout_pymod.hpp>
#include <modmesh/modmesh.hpp>

namespace modmesh
{

namespace python
{

class MODMESH_PYTHON_WRAPPER_VISIBILITY WrapGmsh
    : public WrapBase<WrapGmsh, inout::Gmsh, std::shared_ptr<inout::Gmsh>>
{
public:

    using base_type = WrapBase<WrapGmsh, inout::Gmsh, std::shared_ptr<inout::Gmsh>>;
    using wrapped_type = typename base_type::wrapped_type;

    friend root_base_type;

protected:

    WrapGmsh(pybind11::module & mod, char const * pyname, char const * pydoc)
        : WrapBase<WrapGmsh, inout::Gmsh, std::shared_ptr<inout::Gmsh>>(mod, pyname, pydoc)
    {
        namespace py = pybind11; // NOLINT(misc-unused-alias-decls)

        (*this)
            .def(
                py::init(
                    [](const py::bytes & data)
                    { return std::make_shared<inout::Gmsh>(data); }),
                py::arg("data"))
            .def("to_block", &wrapped_type::to_block);
        ;
    }

}; /* end class WrapGmsh */

void wrap_Gmsh(pybind11::module & mod)
{
    WrapGmsh::commit(mod, "Gmsh", "Gmsh");
}

} /* end namespace python */

} /* end namespace modmesh */

// vim: set ff=unix fenc=utf8 et sw=4 ts=4 sts=4:
