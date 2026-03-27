/**
 * cognirepo/_bm25/bm25.cpp
 * Okapi BM25 implementation — see bm25.hpp for API documentation.
 */
#include "bm25.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <unordered_map>
#include <utility>

namespace cognirepo {

// ── construction ─────────────────────────────────────────────────────────────

BM25::BM25(float k1, float b) : k1_(k1), b_(b) {}

// ── tokenization ─────────────────────────────────────────────────────────────

std::vector<std::string> BM25::tokenize(const std::string& text) const {
    std::vector<std::string> tokens;
    std::string token;
    for (unsigned char ch : text) {
        if (std::isalnum(ch)) {
            token += static_cast<char>(std::tolower(ch));
        } else {
            if (!token.empty()) {
                tokens.push_back(std::move(token));
                token.clear();
            }
        }
    }
    if (!token.empty()) {
        tokens.push_back(std::move(token));
    }
    return tokens;
}

// ── indexing ─────────────────────────────────────────────────────────────────

void BM25::index(const std::vector<Document>& docs) {
    docs_ = docs;
    doc_lengths_.clear();
    inverted_.clear();

    long total_length = 0;
    for (int i = 0; i < static_cast<int>(docs_.size()); ++i) {
        auto tokens = tokenize(docs_[i].text);
        int dl = static_cast<int>(tokens.size());
        doc_lengths_.push_back(dl);
        total_length += dl;

        // count term frequencies per document
        std::unordered_map<std::string, int> tf_map;
        for (const auto& t : tokens) {
            tf_map[t]++;
        }
        for (const auto& [term, freq] : tf_map) {
            inverted_[term].emplace_back(i, freq);
        }
    }

    int n = static_cast<int>(docs_.size());
    avg_dl_ = n > 0 ? static_cast<float>(total_length) / n : 0.0f;
}

// ── search ────────────────────────────────────────────────────────────────────

std::vector<std::pair<std::string, float>>
BM25::search(const std::string& query, int top_k) const {
    if (docs_.empty() || top_k <= 0) {
        return {};
    }

    int n = static_cast<int>(docs_.size());
    std::vector<float> scores(n, 0.0f);

    auto query_terms = tokenize(query);
    if (query_terms.empty()) {
        return {};
    }

    // deduplicate query terms to avoid double-counting
    std::sort(query_terms.begin(), query_terms.end());
    query_terms.erase(std::unique(query_terms.begin(), query_terms.end()), query_terms.end());

    for (const auto& term : query_terms) {
        auto it = inverted_.find(term);
        if (it == inverted_.end()) continue;

        const auto& postings = it->second;
        int df = static_cast<int>(postings.size());
        // Robertson–Spärck Jones IDF
        float idf = std::log(
            (static_cast<float>(n) - df + 0.5f) / (df + 0.5f) + 1.0f
        );

        for (const auto& [doc_idx, tf] : postings) {
            float dl   = static_cast<float>(doc_lengths_[doc_idx]);
            float denom = tf + k1_ * (
                avg_dl_ > 0.0f
                    ? (1.0f - b_ + b_ * dl / avg_dl_)
                    : 1.0f
            );
            scores[doc_idx] += idf * static_cast<float>(tf) * (k1_ + 1.0f) / denom;
        }
    }

    // collect non-zero results and sort descending
    std::vector<std::pair<int, float>> ranked;
    ranked.reserve(n);
    for (int i = 0; i < n; ++i) {
        if (scores[i] > 0.0f) {
            ranked.emplace_back(i, scores[i]);
        }
    }
    std::sort(ranked.begin(), ranked.end(),
              [](const auto& a, const auto& b_) { return a.second > b_.second; });

    int limit = std::min(top_k, n);
    std::vector<std::pair<std::string, float>> results;
    results.reserve(limit);
    for (int k = 0; k < limit && k < static_cast<int>(ranked.size()); ++k) {
        results.emplace_back(docs_[ranked[k].first].id, ranked[k].second);
    }
    return results;
}

} // namespace cognirepo
