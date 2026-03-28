/**
 * cognirepo/_bm25/bindings.cpp
 * pybind11 Python bindings for the C++ BM25 extension.
 *
 * Exposes:
 *   _bm25_ext.Document(id: str, text: str)
 *   _bm25_ext.BM25(k1=1.5, b=0.75)
 *     .index(docs: list[Document]) -> None
 *     .search(query: str, top_k: int = 10) -> list[tuple[str, float]]
 */
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "bm25.hpp"

namespace py = pybind11;

PYBIND11_MODULE(_bm25_ext, m) {
    m.doc() = "CogniRepo high-performance BM25 extension (C++17 + pybind11)";

    py::class_<cognirepo::Document>(m, "Document",
        "A unit of text to be indexed and retrieved.\n\n"
        "Attributes\n----------\n"
        "id   : str  — caller-assigned identifier\n"
        "text : str  — raw content to rank\n")
        .def(py::init<std::string, std::string>(),
             py::arg("id"), py::arg("text"))
        .def_readwrite("id",   &cognirepo::Document::id)
        .def_readwrite("text", &cognirepo::Document::text)
        .def("__repr__", [](const cognirepo::Document& d) {
            return "Document(id=" + d.id + ", text=" + d.text.substr(0, 40) + "...)";
        });

    py::class_<cognirepo::BM25>(m, "BM25",
        "Okapi BM25 ranker.\n\n"
        "Parameters\n----------\n"
        "k1 : float — TF saturation (default 1.5)\n"
        "b  : float — length normalisation (default 0.75)\n")
        .def(py::init<float, float>(),
             py::arg("k1") = 1.5f,
             py::arg("b")  = 0.75f)
        .def("index", &cognirepo::BM25::index,
             py::arg("docs"),
             "Build the inverted index from a list of Document objects.\n"
             "Replaces any previously indexed corpus.")
        .def("search", &cognirepo::BM25::search,
             py::arg("query"),
             py::arg("top_k") = 10,
             "Rank all indexed documents against *query*.\n\n"
             "Returns list[tuple[str, float]] — (document_id, score) pairs\n"
             "sorted by descending score, length ≤ min(top_k, corpus_size).");
}
