#pragma once
/**
 * cognirepo/_bm25/bm25.hpp
 *
 * Okapi BM25 ranker header.
 *
 * Algorithm:
 *   score(d, q) = Σ_{t∈q}  IDF(t) · tf(t,d)·(k1+1) / (tf(t,d) + k1·(1−b+b·|d|/avgdl))
 *   IDF(t)      = log((N − df(t) + 0.5) / (df(t) + 0.5) + 1)
 *
 * Thread-safety: index() is NOT thread-safe; search() is read-only and safe
 * to call concurrently after index() has returned.
 */
#include <string>
#include <vector>
#include <unordered_map>
#include <utility>

namespace cognirepo {

/** A unit of text to be indexed and retrieved. */
struct Document {
    std::string id;    ///< Caller-assigned identifier (e.g. event id, UUID)
    std::string text;  ///< Raw text content to tokenize and rank

    Document() = default;
    Document(std::string id_, std::string text_)
        : id(std::move(id_)), text(std::move(text_)) {}
};

/**
 * BM25 ranker over a fixed corpus of Documents.
 *
 * Typical usage:
 *   BM25 bm25;
 *   bm25.index({{"d1", "the quick brown fox"}, {"d2", "lazy dog"}});
 *   auto results = bm25.search("quick fox", 5);
 *   // results == [("d1", 1.23), ("d2", 0.0)]
 */
class BM25 {
public:
    /**
     * @param k1  Term-frequency saturation parameter (default 1.5).
     * @param b   Length normalisation factor (default 0.75).
     */
    explicit BM25(float k1 = 1.5f, float b = 0.75f);

    /**
     * Build (or rebuild) the inverted index from *docs*.
     * Replaces any previously indexed corpus.
     */
    void index(const std::vector<Document>& docs);

    /**
     * Rank all indexed documents against *query*.
     *
     * @param query  Free-text query string (tokenised internally).
     * @param top_k  Maximum number of results to return.
     * @return       Vector of (document_id, score) pairs sorted by descending
     *               score, size ≤ min(top_k, corpus_size).
     */
    std::vector<std::pair<std::string, float>>
    search(const std::string& query, int top_k = 10) const;

private:
    float k1_;
    float b_;
    float avg_dl_ = 0.0f;

    std::vector<Document> docs_;
    std::vector<int>      doc_lengths_;

    /** Inverted index: term → list of (doc_index, term_frequency) pairs. */
    std::unordered_map<std::string, std::vector<std::pair<int, int>>> inverted_;

    /** Lowercase + split on non-alphanumeric characters. */
    std::vector<std::string> tokenize(const std::string& text) const;
};

} // namespace cognirepo
