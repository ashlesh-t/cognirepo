# CogniRepo Test Execution - Fri May  1 03:23:46 PM IST 2026

## Execution Log
```text
[1m============================= test session starts ==============================[0m
platform linux -- Python 3.14.3, pytest-9.0.3, pluggy-1.6.0 -- /home/ashlesh/my_works/cognirepo/venv/bin/python
cachedir: .pytest_cache
rootdir: /home/ashlesh/my_works/cognirepo
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.12.1, xdist-3.8.0, asyncio-1.3.0, timeout-2.4.0, cov-7.1.0, mock-3.15.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
[1mcollecting ... [0mcollected 644 items

tests/test_adapters.py::TestModelCallError::test_retryable_status_codes [32mPASSED[0m[32m [  0%][0m
tests/test_adapters.py::TestModelCallError::test_non_retryable_status_codes [32mPASSED[0m[32m [  0%][0m
tests/test_adapters.py::TestModelCallError::test_none_status_code_is_retryable [32mPASSED[0m[32m [  0%][0m
tests/test_adapters.py::TestModelCallError::test_str_contains_provider_and_code [32mPASSED[0m[32m [  0%][0m
tests/test_adapters.py::TestRetry::test_success_on_first_attempt [32mPASSED[0m[32m  [  0%][0m
tests/test_adapters.py::TestRetry::test_retries_on_429 [32mPASSED[0m[32m            [  0%][0m
tests/test_adapters.py::TestRetry::test_retries_on_500 [32mPASSED[0m[32m            [  1%][0m
tests/test_adapters.py::TestRetry::test_no_retry_on_401 [32mPASSED[0m[32m           [  1%][0m
tests/test_adapters.py::TestRetry::test_no_retry_on_400 [32mPASSED[0m[32m           [  1%][0m
tests/test_adapters.py::TestRetry::test_exhausts_all_retries_and_raises [32mPASSED[0m[32m [  1%][0m
tests/test_adapters.py::TestRetry::test_sleep_durations_are_exponential [32mPASSED[0m[32m [  1%][0m
tests/test_adapters.py::TestAnthropicAdapter::test_returns_model_response [32mPASSED[0m[32m [  1%][0m
tests/test_adapters.py::TestAnthropicAdapter::test_usage_populated [32mPASSED[0m[32m [  2%][0m
tests/test_adapters.py::TestAnthropicAdapter::test_rate_limit_raises_model_call_error [32mPASSED[0m[32m [  2%][0m
tests/test_adapters.py::TestAnthropicAdapter::test_auth_error_raises_model_call_error_401 [32mPASSED[0m[32m [  2%][0m
tests/test_adapters.py::TestOpenAIAdapter::test_returns_model_response [32mPASSED[0m[32m [  2%][0m
tests/test_adapters.py::TestOpenAIAdapter::test_rate_limit_raises_model_call_error [32mPASSED[0m[32m [  2%][0m
tests/test_adapters.py::TestOpenAIAdapter::test_auth_error_not_retried [32mPASSED[0m[32m [  2%][0m
tests/test_adapters.py::TestGrokAdapter::test_uses_xai_base_url [32mPASSED[0m[32m   [  2%][0m
tests/test_adapters.py::TestGrokAdapter::test_returns_model_response [32mPASSED[0m[32m [  3%][0m
tests/test_adapters.py::TestGeminiAdapter::test_returns_model_response [32mPASSED[0m[32m [  3%][0m
tests/test_adapters.py::TestGeminiAdapter::test_server_error_raises_model_call_error [32mPASSED[0m[32m [  3%][0m
tests/test_adapters.py::TestProviderFallback::test_available_providers_detects_keys [32mPASSED[0m[32m [  3%][0m
tests/test_adapters.py::TestProviderFallback::test_available_providers_empty_when_no_keys [32mPASSED[0m[32m [  3%][0m
tests/test_adapters.py::TestProviderFallback::test_fallback_skips_failed_provider [32mPASSED[0m[32m [  3%][0m
tests/test_adapters.py::TestAnthropicStreaming::test_stream_yields_chunks [32mPASSED[0m[32m [  4%][0m
tests/test_adapters.py::TestAnthropicStreaming::test_stream_assembles_full_text [32mPASSED[0m[32m [  4%][0m
tests/test_adapters.py::TestAnthropicStreaming::test_stream_returns_usage_via_stop_iteration [32mPASSED[0m[32m [  4%][0m
tests/test_adapters.py::TestAnthropicStreaming::test_stream_is_generator [32mPASSED[0m[32m [  4%][0m
tests/test_adapters.py::TestAnthropicStreaming::test_stream_rate_limit_raises_model_call_error [32mPASSED[0m[32m [  4%][0m
tests/test_adapters.py::TestAnthropicStreaming::test_non_stream_still_returns_model_response [32mPASSED[0m[32m [  4%][0m
tests/test_adapters.py::TestOpenAIStreaming::test_stream_yields_chunks [32mPASSED[0m[32m [  4%][0m
tests/test_adapters.py::TestOpenAIStreaming::test_stream_assembles_full_text [32mPASSED[0m[32m [  5%][0m
tests/test_adapters.py::TestOpenAIStreaming::test_stream_captures_usage_from_final_chunk [32mPASSED[0m[32m [  5%][0m
tests/test_adapters.py::TestOpenAIStreaming::test_stream_is_generator [32mPASSED[0m[32m [  5%][0m
tests/test_adapters.py::TestOpenAIStreaming::test_stream_rate_limit_raises_model_call_error [32mPASSED[0m[32m [  5%][0m
tests/test_adapters.py::TestOpenAIStreaming::test_stream_skips_empty_delta [32mPASSED[0m[32m [  5%][0m
tests/test_adapters.py::TestGrokStreaming::test_grok_stream_uses_xai_url [32mPASSED[0m[32m [  5%][0m
tests/test_adapters.py::TestGrokStreaming::test_grok_stream_provider_label [32mPASSED[0m[32m [  6%][0m
tests/test_adapters.py::TestStreamRoute::test_stream_route_yields_chunks [32mPASSED[0m[32m [  6%][0m
tests/test_adapters.py::TestStreamRoute::test_stream_route_collects_usage [32mPASSED[0m[32m [  6%][0m
tests/test_adapters.py::TestStreamRoute::test_stream_route_is_generator [32mPASSED[0m[32m [  6%][0m
tests/test_benchmark_metrics.py::TestTokenReductionMetric::test_context_pack_reduces_tokens_by_at_least_50pct [32mPASSED[0m[32m [  6%][0m
tests/test_benchmark_metrics.py::TestTokenReductionMetric::test_context_pack_stays_within_budget [32mPASSED[0m[32m [  6%][0m
tests/test_benchmark_metrics.py::TestTokenReductionMetric::test_context_pack_returns_nonzero_for_indexed_query [32mPASSED[0m[32m [  6%][0m
tests/test_benchmark_metrics.py::TestSymbolLookupLatency::test_lookup_under_10ms [32mPASSED[0m[32m [  7%][0m
tests/test_benchmark_metrics.py::TestSymbolLookupLatency::test_hit_rate_for_known_symbols [32mPASSED[0m[32m [  7%][0m
tests/test_benchmark_metrics.py::TestCacheSpeedup::test_warm_retrieve_is_faster_than_cold [32mPASSED[0m[32m [  7%][0m
tests/test_benchmark_metrics.py::TestCacheSpeedup::test_cache_stats_show_hit [32mPASSED[0m[32m [  7%][0m
tests/test_benchmark_metrics.py::TestMemoryRecall::test_stored_memory_recall_at_3 [32mPASSED[0m[32m [  7%][0m
tests/test_benchmark_metrics.py::TestMemoryRecall::test_retrieve_memory_returns_list [32mPASSED[0m[32m [  7%][0m
tests/test_benchmark_metrics.py::TestGraphScore::test_ast_candidate_gets_nonzero_graph_score [32mPASSED[0m[32m [  8%][0m
tests/test_benchmark_metrics.py::TestContextRelevance::test_context_sections_contain_query_keywords [32mPASSED[0m[32m [  8%][0m
tests/test_benchmark_metrics.py::TestPrecisionAtK::test_measure_precision_returns_required_keys [32mPASSED[0m[32m [  8%][0m
tests/test_benchmark_metrics.py::TestLatencyHistogram::test_measure_latency_returns_required_keys [32mPASSED[0m[32m [  8%][0m
tests/test_bm25.py::TestBackendConstant::test_backend_is_valid_string [32mPASSED[0m[32m [  8%][0m
tests/test_bm25.py::TestBackendConstant::test_backend_reported [32mPASSED[0m[32m    [  8%][0m
tests/test_bm25.py::TestBM25Core::test_empty_corpus_returns_empty [32mPASSED[0m[32m [  9%][0m
tests/test_bm25.py::TestBM25Core::test_empty_query_returns_empty [32mPASSED[0m[32m  [  9%][0m
tests/test_bm25.py::TestBM25Core::test_single_doc_match [32mPASSED[0m[32m           [  9%][0m
tests/test_bm25.py::TestBM25Core::test_ranked_order_five_docs [32mPASSED[0m[32m     [  9%][0m
tests/test_bm25.py::TestBM25Core::test_scores_descending [32mPASSED[0m[32m          [  9%][0m
tests/test_bm25.py::TestBM25Core::test_top_k_clamps_to_doc_count [32mPASSED[0m[32m  [  9%][0m
tests/test_bm25.py::TestBM25Core::test_top_k_zero [32mPASSED[0m[32m                 [  9%][0m
tests/test_bm25.py::TestBM25Core::test_no_match_returns_empty [32mPASSED[0m[32m     [ 10%][0m
tests/test_bm25.py::TestBM25Core::test_result_ids_are_strings [32mPASSED[0m[32m     [ 10%][0m
tests/test_bm25.py::TestBM25Core::test_result_scores_are_positive [32mPASSED[0m[32m [ 10%][0m
tests/test_bm25.py::TestBM25Core::test_reindex_replaces_corpus [32mPASSED[0m[32m    [ 10%][0m
tests/test_bm25.py::TestBM25Core::test_k1_b_params_accepted [32mPASSED[0m[32m       [ 10%][0m
tests/test_bm25.py::TestBackendParity::test_python_and_cpp_same_ranking [33mSKIPPED[0m[32m [ 10%][0m
tests/test_bm25.py::TestEpisodicBM25Filter::test_returns_list [32mPASSED[0m[32m     [ 11%][0m
tests/test_bm25.py::TestEpisodicBM25Filter::test_relevant_event_ranked_first [32mPASSED[0m[32m [ 11%][0m
tests/test_bm25.py::TestEpisodicBM25Filter::test_empty_log_returns_empty [32mPASSED[0m[32m [ 11%][0m
tests/test_bm25.py::TestEpisodicBM25Filter::test_top_k_respected [32mPASSED[0m[32m  [ 11%][0m
tests/test_bm25.py::TestEpisodicBM25Filter::test_time_range_filter [32mPASSED[0m[32m [ 11%][0m
tests/test_cache.py::TestLookupSymbolCache::test_lookup_returns_correct_locations [32mPASSED[0m[32m [ 11%][0m
tests/test_cache.py::TestLookupSymbolCache::test_lookup_missing_symbol_returns_empty [32mPASSED[0m[32m [ 11%][0m
tests/test_cache.py::TestLookupSymbolCache::test_repeated_calls_use_cache [32mPASSED[0m[32m [ 12%][0m
tests/test_cache.py::TestLookupSymbolCache::test_cache_cleared_after_build_reverse_index [32mPASSED[0m[32m [ 12%][0m
tests/test_cache.py::TestHybridRetrieveCache::test_cache_miss_then_hit [32mPASSED[0m[32m [ 12%][0m
tests/test_cache.py::TestHybridRetrieveCache::test_different_queries_not_shared [32mPASSED[0m[32m [ 12%][0m
tests/test_cache.py::TestHybridRetrieveCache::test_invalidate_clears_cache [32mPASSED[0m[32m [ 12%][0m
tests/test_cache.py::TestHybridRetrieveCache::test_cache_expires_after_ttl [32mPASSED[0m[32m [ 12%][0m
tests/test_cache.py::TestHybridRetrieveCache::test_cache_stats_available [32mPASSED[0m[32m [ 13%][0m
tests/test_ci_security.py::TestCIWorkflowExists::test_ci_yml_exists [32mPASSED[0m[32m [ 13%][0m
tests/test_ci_security.py::TestCIWorkflowExists::test_ci_yml_is_not_empty [32mPASSED[0m[32m [ 13%][0m
tests/test_ci_security.py::TestBanditIntegration::test_ci_yml_includes_bandit [32mPASSED[0m[32m [ 13%][0m
tests/test_ci_security.py::TestBanditIntegration::test_bandit_targets_high_severity [32mPASSED[0m[32m [ 13%][0m
tests/test_ci_security.py::TestTruffleHogIntegration::test_ci_yml_includes_trufflehog [32mPASSED[0m[32m [ 13%][0m
tests/test_ci_security.py::TestTruffleHogIntegration::test_trufflehog_uses_only_verified [32mPASSED[0m[32m [ 13%][0m
tests/test_ci_security.py::TestTrivyIntegration::test_ci_yml_includes_trivy [32mPASSED[0m[32m [ 14%][0m
tests/test_ci_security.py::TestTrivyIntegration::test_trivy_targets_critical_high [32mPASSED[0m[32m [ 14%][0m
tests/test_ci_security.py::TestTrivyIntegration::test_trivy_exit_code_is_1 [32mPASSED[0m[32m [ 14%][0m
tests/test_ci_security.py::TestPipAuditIntegration::test_ci_yml_includes_pip_audit [32mPASSED[0m[32m [ 14%][0m
tests/test_ci_security.py::TestPipAuditIntegration::test_pip_audit_runs_after_install [32mPASSED[0m[32m [ 14%][0m
tests/test_circuit_breaker_probes.py::test_rss_probe_ok_when_under_limit [32mPASSED[0m[32m [ 14%][0m
tests/test_circuit_breaker_probes.py::test_rss_probe_fails_when_over_limit [32mPASSED[0m[32m [ 15%][0m
tests/test_circuit_breaker_probes.py::test_disk_free_probe_ok_on_existing_path [32mPASSED[0m[32m [ 15%][0m
tests/test_circuit_breaker_probes.py::test_disk_free_probe_fails_on_huge_minimum [32mPASSED[0m[32m [ 15%][0m
tests/test_circuit_breaker_probes.py::test_fake_probe_trips_breaker [32mPASSED[0m[32m [ 15%][0m
tests/test_circuit_breaker_probes.py::test_passing_probes_keep_circuit_closed [32mPASSED[0m[32m [ 15%][0m
tests/test_circuit_breaker_probes.py::test_backward_compat_rss_only [32mPASSED[0m[32m [ 15%][0m
tests/test_circuit_breaker_probes.py::test_multiple_probes_first_failure_trips [32mPASSED[0m[32m [ 15%][0m
tests/test_circuit_breaker_probes.py::test_storage_size_probe_ok_when_under_limit [32mPASSED[0m[32m [ 16%][0m
tests/test_circuit_breaker_probes.py::test_storage_size_probe_fails_when_over_limit [32mPASSED[0m[32m [ 16%][0m
tests/test_circuit_breaker_probes.py::test_storage_probe_trips_breaker [32mPASSED[0m[32m [ 16%][0m
tests/test_circuit_breaker_probes.py::test_record_success_closes_circuit [32mPASSED[0m[32m [ 16%][0m
tests/test_classifier.py::TestHardOverrides::test_single_token_fast [32mPASSED[0m[32m [ 16%][0m
tests/test_classifier.py::TestHardOverrides::test_empty_single_token [32mPASSED[0m[32m [ 16%][0m
tests/test_classifier.py::TestHardOverrides::test_full_context_phrase_deep [32mPASSED[0m[32m [ 17%][0m
tests/test_classifier.py::TestHardOverrides::test_all_related_phrase_deep [32mPASSED[0m[32m [ 17%][0m
tests/test_classifier.py::TestHardOverrides::test_error_trace_minimum_balanced [32mPASSED[0m[32m [ 17%][0m
tests/test_classifier.py::TestHardOverrides::test_traceback_keyword [32mPASSED[0m[32m [ 17%][0m
tests/test_classifier.py::TestSignals::test_reasoning_keywords_increase_score [32mPASSED[0m[32m [ 17%][0m
tests/test_classifier.py::TestSignals::test_lookup_keywords_decrease_score [32mPASSED[0m[32m [ 17%][0m
tests/test_classifier.py::TestSignals::test_vague_referents_increase_score [32mPASSED[0m[32m [ 18%][0m
tests/test_classifier.py::TestSignals::test_cross_entity_count_signal [32mPASSED[0m[32m [ 18%][0m
tests/test_classifier.py::TestSignals::test_context_dependency_signal [32mPASSED[0m[32m [ 18%][0m
tests/test_classifier.py::TestSignals::test_token_length_signal [32mPASSED[0m[32m   [ 18%][0m
tests/test_classifier.py::TestSignals::test_imperative_abstract_signal [32mPASSED[0m[32m [ 18%][0m
tests/test_classifier.py::TestSignals::test_build_keyword_imperative [32mPASSED[0m[32m [ 18%][0m
tests/test_classifier.py::TestTierBoundaries::test_standard_tier [32mPASSED[0m[32m  [ 18%][0m
tests/test_classifier.py::TestTierBoundaries::test_complex_tier [32mPASSED[0m[32m   [ 19%][0m
tests/test_classifier.py::TestTierBoundaries::test_deep_tier_full_override [32mPASSED[0m[32m [ 19%][0m
tests/test_classifier.py::TestTierBoundaries::test_score_returned [32mPASSED[0m[32m [ 19%][0m
tests/test_classifier.py::TestTierBoundaries::test_model_and_provider_returned [32mPASSED[0m[32m [ 19%][0m
tests/test_classifier.py::TestTierBoundaries::test_force_model_overrides_model_id [32mPASSED[0m[32m [ 19%][0m
tests/test_claude_usefulness.py::TestTokenReduction::test_context_pack_under_budget [32mPASSED[0m[32m [ 19%][0m
tests/test_claude_usefulness.py::TestTokenReduction::test_context_pack_fewer_tokens_than_raw_file [32mPASSED[0m[32m [ 20%][0m
tests/test_claude_usefulness.py::TestTokenReduction::test_token_savings_reported [31mFAILED[0m[31m [ 20%][0m
tests/test_claude_usefulness.py::TestSymbolLookupEfficiency::test_lookup_returns_in_under_100ms [32mPASSED[0m[31m [ 20%][0m
tests/test_claude_usefulness.py::TestSymbolLookupEfficiency::test_lookup_returns_file_and_line [32mPASSED[0m[31m [ 20%][0m
tests/test_claude_usefulness.py::TestSymbolLookupEfficiency::test_lookup_vs_grep_equivalent [32mPASSED[0m[31m [ 20%][0m
tests/test_claude_usefulness.py::TestCacheEfficiency::test_hybrid_cache_hit_is_faster [32mPASSED[0m[31m [ 20%][0m
tests/test_claude_usefulness.py::TestCacheEfficiency::test_cache_stats_record_hits [32mPASSED[0m[31m [ 20%][0m
tests/test_claude_usefulness.py::TestMemoryRecall::test_stored_memory_is_retrievable [32mPASSED[0m[31m [ 21%][0m
tests/test_claude_usefulness.py::TestMemoryRecall::test_retrieval_returns_most_relevant_first [32mPASSED[0m[31m [ 21%][0m
tests/test_claude_usefulness.py::TestAnswerGrounding::test_context_pack_has_sections [32mPASSED[0m[31m [ 21%][0m
tests/test_claude_usefulness.py::TestAnswerGrounding::test_context_pack_sections_have_content [32mPASSED[0m[31m [ 21%][0m
tests/test_claude_usefulness.py::TestAnswerGrounding::test_context_pack_query_preserved [32mPASSED[0m[31m [ 21%][0m
tests/test_claude_usefulness.py::TestGlobalUserMemory::test_global_dir_accessible_from_any_cwd [32mPASSED[0m[31m [ 21%][0m
tests/test_claude_usefulness.py::TestGlobalUserMemory::test_user_preference_survives_cwd_change [32mPASSED[0m[31m [ 22%][0m
tests/test_claude_usefulness.py::TestHybridSignalMix::test_vector_score_present [32mPASSED[0m[31m [ 22%][0m
tests/test_claude_usefulness.py::TestRealProjectPortability::test_index_data_structure_stable [32mPASSED[0m[31m [ 22%][0m
tests/test_cli_config.py::test_missing_file_creates_defaults [32mPASSED[0m[31m      [ 22%][0m
tests/test_cli_config.py::test_empty_file_uses_defaults [32mPASSED[0m[31m           [ 22%][0m
tests/test_cli_config.py::test_valid_config_loaded_correctly [32mPASSED[0m[31m      [ 22%][0m
tests/test_cli_config.py::test_partial_config_fills_defaults [32mPASSED[0m[31m      [ 22%][0m
tests/test_cli_config.py::test_invalid_theme_falls_back_to_auto [32mPASSED[0m[31m   [ 23%][0m
tests/test_cli_config.py::test_invalid_tier_falls_back_to_empty [32mPASSED[0m[31m   [ 23%][0m
tests/test_cli_config.py::test_max_exchanges_below_one_resets_to_default [32mPASSED[0m[31m [ 23%][0m
tests/test_cli_config.py::test_corrupt_toml_falls_back_to_defaults [32mPASSED[0m[31m [ 23%][0m
tests/test_cli_config.py::test_force_tier_normalised_to_uppercase [32mPASSED[0m[31m [ 23%][0m
tests/test_cli_config.py::test_default_toml_contains_all_sections [32mPASSED[0m[31m [ 23%][0m
tests/test_cli_daemon.py::test_daemon_module_does_not_import_fcntl_at_toplevel [32mPASSED[0m[31m [ 24%][0m
tests/test_cli_daemon.py::test_daemon_start_friendly_error_on_unsupported_os [32mPASSED[0m[31m [ 24%][0m
tests/test_config_migration.py::test_migrate_renames_fast_to_standard [32mPASSED[0m[31m [ 24%][0m
tests/test_config_migration.py::test_migrate_dry_run_does_not_write [32mPASSED[0m[31m [ 24%][0m
tests/test_config_migration.py::test_migrate_no_op_when_already_migrated [32mPASSED[0m[31m [ 24%][0m
tests/test_config_migration.py::test_migrate_creates_backup [32mPASSED[0m[31m       [ 24%][0m
tests/test_config_migration.py::test_migrate_preserves_other_keys [32mPASSED[0m[31m [ 25%][0m
tests/test_config_migration.py::test_migrate_file_not_found [32mPASSED[0m[31m       [ 25%][0m
tests/test_config_migration.py::test_classifier_raises_on_legacy_config [32mPASSED[0m[31m [ 25%][0m
tests/test_config_migration.py::test_classifier_accepts_new_tier_names [32mPASSED[0m[31m [ 25%][0m
tests/test_config_migration.py::test_tier_renames_covers_all_old_names [32mPASSED[0m[31m [ 25%][0m
tests/test_context_builder.py::TestTokenEstimation::test_empty_string_is_zero [32mPASSED[0m[31m [ 25%][0m
tests/test_context_builder.py::TestTokenEstimation::test_four_chars_is_one_token [32mPASSED[0m[31m [ 25%][0m
tests/test_context_builder.py::TestTokenEstimation::test_scales_linearly [32mPASSED[0m[31m [ 26%][0m
tests/test_context_builder.py::TestTokenEstimation::test_long_text_estimated [32mPASSED[0m[31m [ 26%][0m
tests/test_context_builder.py::TestTierBudgets::test_standard_budget [32mPASSED[0m[31m [ 26%][0m
tests/test_context_builder.py::TestTierBudgets::test_complex_budget [32mPASSED[0m[31m [ 26%][0m
tests/test_context_builder.py::TestTierBudgets::test_expert_budget [32mPASSED[0m[31m [ 26%][0m
tests/test_context_builder.py::TestTierBudgets::test_build_sets_tier_budget [32mPASSED[0m[31m [ 26%][0m
tests/test_context_builder.py::TestTierBudgets::test_build_expert_budget [32mPASSED[0m[31m [ 27%][0m
tests/test_context_builder.py::TestNoBudgetExceeded::test_small_bundle_not_trimmed [32mPASSED[0m[31m [ 27%][0m
tests/test_context_builder.py::TestNoBudgetExceeded::test_token_count_set_even_without_trim [32mPASSED[0m[31m [ 27%][0m
tests/test_context_builder.py::TestEpisodicTrim::test_episodes_trimmed_first [32mPASSED[0m[31m [ 27%][0m
tests/test_context_builder.py::TestEpisodicTrim::test_oldest_episode_removed_first [32mPASSED[0m[31m [ 27%][0m
tests/test_context_builder.py::TestEpisodicTrim::test_all_episodes_can_be_removed [32mPASSED[0m[31m [ 27%][0m
tests/test_context_builder.py::TestGraphTrim::test_graph_lines_trimmed_from_end [32mPASSED[0m[31m [ 27%][0m
tests/test_context_builder.py::TestGraphTrim::test_graph_trimmed_after_episodes_exhausted [32mPASSED[0m[31m [ 28%][0m
tests/test_context_builder.py::TestMemoryTrim::test_lowest_score_memory_removed_first [32mPASSED[0m[31m [ 28%][0m
tests/test_context_builder.py::TestMemoryTrim::test_high_score_memory_survives_trim [32mPASSED[0m[31m [ 28%][0m
tests/test_context_builder.py::TestOverallBudget::test_30k_context_trimmed_to_budget [32mPASSED[0m[31m [ 28%][0m
tests/test_context_builder.py::TestOverallBudget::test_ast_hits_never_trimmed [32mPASSED[0m[31m [ 28%][0m
tests/test_context_builder.py::TestOverallBudget::test_was_trimmed_flag_set [32mPASSED[0m[31m [ 28%][0m
tests/test_context_builder.py::TestOverallBudget::test_system_prompt_updated_after_trim [32mPASSED[0m[31m [ 29%][0m
tests/test_context_pack.py::TestContextPack::test_returns_required_keys [32mPASSED[0m[31m [ 29%][0m
tests/test_context_pack.py::TestContextPack::test_query_preserved [32mPASSED[0m[31m [ 29%][0m
tests/test_context_pack.py::TestContextPack::test_max_tokens_not_exceeded [32mPASSED[0m[31m [ 29%][0m
tests/test_context_pack.py::TestContextPack::test_include_episodic_false_omits_episodic [32mPASSED[0m[31m [ 29%][0m
tests/test_context_pack.py::TestContextPack::test_include_symbols_false_skips_retrieval [32mPASSED[0m[31m [ 29%][0m
tests/test_context_pack.py::TestContextPack::test_sections_have_required_fields [32mPASSED[0m[31m [ 29%][0m
tests/test_context_pack.py::TestContextPack::test_episodic_sections_included [32mPASSED[0m[31m [ 30%][0m
tests/test_context_pack.py::TestContextPack::test_truncated_flag_set_when_budget_exceeded [32mPASSED[0m[31m [ 30%][0m
tests/test_context_pack.py::TestContextPack::test_token_count_accurate [32mPASSED[0m[31m [ 30%][0m
tests/test_cross_agent_recall.py::test_cross_agent_correction_recall [32mPASSED[0m[31m [ 30%][0m
tests/test_cross_agent_recall.py::test_retrieve_learnings_filtered_by_type [32mPASSED[0m[31m [ 30%][0m
tests/test_cross_repo.py::test_get_sibling_repos [32mPASSED[0m[31m                  [ 30%][0m
tests/test_cross_repo.py::test_query_org_memories_empty [32mPASSED[0m[31m           [ 31%][0m
tests/test_cursor_vscode.py::TestCursorMCP::test_creates_cursor_mcp_json [32mPASSED[0m[31m [ 31%][0m
tests/test_cursor_vscode.py::TestCursorMCP::test_server_name_includes_project_name [32mPASSED[0m[31m [ 31%][0m
tests/test_cursor_vscode.py::TestCursorMCP::test_idempotent_does_not_delete_siblings [32mPASSED[0m[31m [ 31%][0m
tests/test_cursor_vscode.py::TestCursorMCP::test_valid_json_output [32mPASSED[0m[31m [ 31%][0m
tests/test_cursor_vscode.py::TestVSCodeMCP::test_creates_vscode_mcp_json [32mPASSED[0m[31m [ 31%][0m
tests/test_cursor_vscode.py::TestVSCodeMCP::test_type_is_stdio [32mPASSED[0m[31m    [ 31%][0m
tests/test_cursor_vscode.py::TestVSCodeMCP::test_idempotent_does_not_delete_siblings [32mPASSED[0m[31m [ 32%][0m
tests/test_cursor_vscode.py::TestVSCodeMCP::test_valid_json_output [32mPASSED[0m[31m [ 32%][0m
tests/test_cursor_vscode.py::TestSetupMCPDispatch::test_cursor_target_creates_cursor_file [32mPASSED[0m[31m [ 32%][0m
tests/test_cursor_vscode.py::TestSetupMCPDispatch::test_vscode_target_creates_vscode_file [32mPASSED[0m[31m [ 32%][0m
tests/test_cursor_vscode.py::TestSetupMCPDispatch::test_both_targets_create_both_files [32mPASSED[0m[31m [ 32%][0m
tests/test_cursor_vscode.py::TestSetupMCPDispatch::test_empty_targets_creates_nothing [32mPASSED[0m[31m [ 32%][0m
tests/test_cursor_vscode.py::TestDoctorValidation::test_cursor_config_is_valid_json [32mPASSED[0m[31m [ 33%][0m
tests/test_cursor_vscode.py::TestDoctorValidation::test_vscode_config_is_valid_json [32mPASSED[0m[31m [ 33%][0m
tests/test_dependency_graph.py::TestDependencyGraph::test_missing_module_returns_error [32mPASSED[0m[31m [ 33%][0m
tests/test_dependency_graph.py::TestDependencyGraph::test_direct_imports [32mPASSED[0m[31m [ 33%][0m
tests/test_dependency_graph.py::TestDependencyGraph::test_imported_by [32mPASSED[0m[31m [ 33%][0m
tests/test_dependency_graph.py::TestDependencyGraph::test_direction_imports_only [32mPASSED[0m[31m [ 33%][0m
tests/test_dependency_graph.py::TestDependencyGraph::test_direction_imported_by_only [32mPASSED[0m[31m [ 34%][0m
tests/test_dependency_graph.py::TestDependencyGraph::test_transitive_depth_1_no_transitive [32mPASSED[0m[31m [ 34%][0m
tests/test_dependency_graph.py::TestDependencyGraph::test_transitive_depth_2 [32mPASSED[0m[31m [ 34%][0m
tests/test_dependency_graph.py::TestDependencyGraph::test_invalid_direction_returns_error [32mPASSED[0m[31m [ 34%][0m
tests/test_dependency_graph.py::TestDependencyGraph::test_partial_name_match [32mPASSED[0m[31m [ 34%][0m
tests/test_dependency_graph.py::TestDependencyGraph::test_result_has_depth_field [32mPASSED[0m[31m [ 34%][0m
tests/test_docs_index.py::test_chunk_markdown_missing_file [32mPASSED[0m[31m        [ 34%][0m
tests/test_docs_index.py::test_chunk_markdown_basic [32mPASSED[0m[31m               [ 35%][0m
tests/test_docs_index.py::test_chunk_markdown_splits_large_section [32mPASSED[0m[31m [ 35%][0m
tests/test_docs_index.py::test_chunk_markdown_heading_becomes_section [32mPASSED[0m[31m [ 35%][0m
tests/test_docs_index.py::test_chunk_markdown_skips_short_chunks [32mPASSED[0m[31m  [ 35%][0m
tests/test_docs_index.py::test_index_is_stale_missing_index [32mPASSED[0m[31m       [ 35%][0m
tests/test_docs_index.py::test_index_is_stale_missing_mtimes [32mPASSED[0m[31m      [ 35%][0m
tests/test_docs_index.py::test_index_is_stale_up_to_date [32mPASSED[0m[31m          [ 36%][0m
tests/test_docs_index.py::test_index_is_stale_when_file_updated [32mPASSED[0m[31m   [ 36%][0m
tests/test_docs_index.py::test_is_docs_query_positive [32mPASSED[0m[31m             [ 36%][0m
tests/test_docs_index.py::test_is_docs_query_negative [32mPASSED[0m[31m             [ 36%][0m
tests/test_docs_index.py::test_confidence_threshold_value [32mPASSED[0m[31m         [ 36%][0m
tests/test_docs_index.py::test_ensure_docs_index_returns_none_on_build_failure [32mPASSED[0m[31m [ 36%][0m
tests/test_docs_index.py::test_docs_index_answer_returns_results [32mPASSED[0m[31m  [ 36%][0m
tests/test_docs_index.py::test_docs_index_answer_empty_index [32mPASSED[0m[31m      [ 37%][0m
tests/test_docs_sync.py::test_classifier_thresholds_match_docs [32mPASSED[0m[31m    [ 37%][0m
tests/test_docs_sync.py::test_classifier_imperative_weight_matches_docs [32mPASSED[0m[31m [ 37%][0m
tests/test_docs_sync.py::test_edge_types_match_docs [32mPASSED[0m[31m               [ 37%][0m
tests/test_docs_sync.py::test_no_stale_edge_names_in_feature_md [32mPASSED[0m[31m   [ 37%][0m
tests/test_doctor.py::TestDoctorAllHealthy::test_exit_0_when_all_pass [32mPASSED[0m[31m [ 37%][0m
tests/test_doctor.py::TestDoctorAllHealthy::test_all_checks_show_tick [32mPASSED[0m[31m [ 38%][0m
tests/test_doctor.py::TestDoctorAllHealthy::test_summary_no_issues [32mPASSED[0m[31m [ 38%][0m
tests/test_doctor.py::TestDoctorNoApiKeys::test_exit_0_no_api_keys [32mPASSED[0m[31m [ 38%][0m
tests/test_doctor.py::TestDoctorNoApiKeys::test_all_four_key_names_in_output [32mPASSED[0m[31m [ 38%][0m
tests/test_doctor.py::TestDoctorNoApiKeys::test_warning_mark_on_api_key_check [32mPASSED[0m[31m [ 38%][0m
tests/test_doctor.py::TestDoctorFaissFailure::test_exit_1_faiss_missing [32mPASSED[0m[31m [ 38%][0m
tests/test_doctor.py::TestDoctorFaissFailure::test_cross_mark_on_faiss_check [32mPASSED[0m[31m [ 38%][0m
tests/test_doctor.py::TestDoctorGraphFailure::test_exit_1_graph_missing [32mPASSED[0m[31m [ 39%][0m
tests/test_doctor.py::TestDoctorGraphFailure::test_cross_mark_on_graph_check [32mPASSED[0m[31m [ 39%][0m
tests/test_doctor.py::TestDoctorMultipleFailures::test_issue_count_in_summary [32mPASSED[0m[31m [ 39%][0m
tests/test_doctor.py::TestDoctorVerbose::test_verbose_shows_optional_section [32mPASSED[0m[31m [ 39%][0m
tests/test_e2e_init.py::test_init_creates_index [32mPASSED[0m[31m                   [ 39%][0m
tests/test_e2e_init.py::test_no_index_flag_skips_indexing [32mPASSED[0m[31m         [ 39%][0m
tests/test_encryption.py::TestFernetHelpers::test_encrypt_decrypt_round_trip [32mPASSED[0m[31m [ 40%][0m
tests/test_encryption.py::TestFernetHelpers::test_key_persistence_returns_same_key [32mPASSED[0m[31m [ 40%][0m
tests/test_encryption.py::TestFernetHelpers::test_missing_cryptography_raises_import_error [32mPASSED[0m[31m [ 40%][0m
tests/test_encryption.py::TestEpisodicEncryption::test_encrypt_write_not_plaintext [32mPASSED[0m[31m [ 40%][0m
tests/test_encryption.py::TestEpisodicEncryption::test_encrypt_round_trip [32mPASSED[0m[31m [ 40%][0m
tests/test_encryption.py::TestEpisodicEncryption::test_disabled_encryption_plaintext [32mPASSED[0m[31m [ 40%][0m
tests/test_encryption.py::TestGraphEncryption::test_graph_pkl_encrypted [32mPASSED[0m[31m [ 40%][0m
tests/test_encryption.py::TestGraphEncryption::test_graph_disabled_encryption_is_pickle [32mPASSED[0m[31m [ 41%][0m
tests/test_encryption.py::TestGitignoreBlanket::test_gitignore_blanket_pattern [32mPASSED[0m[31m [ 41%][0m
tests/test_env_wizard.py::test_mask_short_value [32mPASSED[0m[31m                   [ 41%][0m
tests/test_env_wizard.py::test_mask_long_value [32mPASSED[0m[31m                    [ 41%][0m
tests/test_env_wizard.py::test_detect_missing_when_all_absent [32mPASSED[0m[31m     [ 41%][0m
tests/test_env_wizard.py::test_detect_missing_respects_dotenv [32mPASSED[0m[31m     [ 41%][0m
tests/test_env_wizard.py::test_detect_missing_respects_os_environ [32mPASSED[0m[31m [ 42%][0m
tests/test_env_wizard.py::test_set_and_read_dotenv_key [32mPASSED[0m[31m            [ 42%][0m
tests/test_env_wizard.py::test_set_dotenv_key_overwrites_existing [32mPASSED[0m[31m [ 42%][0m
tests/test_env_wizard.py::test_guided_flow_writes_key [32mPASSED[0m[31m             [ 42%][0m
tests/test_env_wizard.py::test_non_interactive_skips [32mPASSED[0m[31m              [ 42%][0m
tests/test_env_wizard.py::test_verify_keys_calls_probe [32mPASSED[0m[31m            [ 42%][0m
tests/test_env_wizard.py::test_verify_keys_skipped_with_flag [32mPASSED[0m[31m      [ 43%][0m
tests/test_env_wizard.py::test_key_masked_in_guided_flow [32mPASSED[0m[31m          [ 43%][0m
tests/test_episodic_search.py::TestBM25RankingInSearchEpisodes::test_specific_match_ranks_first [32mPASSED[0m[31m [ 43%][0m
tests/test_episodic_search.py::TestBM25RankingInSearchEpisodes::test_no_query_token_overlap_excluded [32mPASSED[0m[31m [ 43%][0m
tests/test_episodic_search.py::TestBM25RankingInSearchEpisodes::test_empty_corpus_returns_empty [32mPASSED[0m[31m [ 43%][0m
tests/test_episodic_search.py::TestBM25RankingInSearchEpisodes::test_limit_respected [32mPASSED[0m[31m [ 43%][0m
tests/test_episodic_search.py::TestBM25RankingInSearchEpisodes::test_results_are_full_episode_dicts [32mPASSED[0m[31m [ 43%][0m
tests/test_episodic_search.py::TestBM25CacheLifecycle::test_cache_built_on_first_search [32mPASSED[0m[31m [ 44%][0m
tests/test_episodic_search.py::TestBM25CacheLifecycle::test_cache_invalidated_on_save [32mPASSED[0m[31m [ 44%][0m
tests/test_episodic_search.py::TestBM25CacheLifecycle::test_cache_reused_without_save [32mPASSED[0m[31m [ 44%][0m
tests/test_explain_change.py::TestGitUtils::test_parse_since_days [32mPASSED[0m[31m [ 44%][0m
tests/test_explain_change.py::TestGitUtils::test_parse_since_iso_passthrough [32mPASSED[0m[31m [ 44%][0m
tests/test_explain_change.py::TestGitUtils::test_parse_since_weeks [32mPASSED[0m[31m [ 44%][0m
tests/test_explain_change.py::TestGitUtils::test_parse_git_log_output [32mPASSED[0m[31m [ 45%][0m
tests/test_explain_change.py::TestGitUtils::test_parse_empty_log [32mPASSED[0m[31m  [ 45%][0m
tests/test_explain_change.py::TestGitUtils::test_git_log_patch_returns_list [32mPASSED[0m[31m [ 45%][0m
tests/test_explain_change.py::TestGitUtils::test_git_not_found_raises [32mPASSED[0m[31m [ 45%][0m
tests/test_explain_change.py::TestGitUtils::test_nonzero_returncode_returns_empty [32mPASSED[0m[31m [ 45%][0m
tests/test_explain_change.py::TestExplainChange::test_returns_required_keys [32mPASSED[0m[31m [ 45%][0m
tests/test_explain_change.py::TestExplainChange::test_target_preserved [32mPASSED[0m[31m [ 45%][0m
tests/test_explain_change.py::TestExplainChange::test_git_summary_totals [32mPASSED[0m[31m [ 46%][0m
tests/test_explain_change.py::TestExplainChange::test_no_git_repo_returns_error [32mPASSED[0m[31m [ 46%][0m
tests/test_explain_change.py::TestExplainChange::test_episodic_context_included [32mPASSED[0m[31m [ 46%][0m
tests/test_explain_change.py::TestExplainChange::test_episodic_failure_doesnt_crash [32mPASSED[0m[31m [ 46%][0m
tests/test_explain_change.py::TestExplainChange::test_empty_git_history_still_returns_structure [32mPASSED[0m[31m [ 46%][0m
tests/test_fallback_chain.py::test_fallback_from_anthropic_to_gemini [32mPASSED[0m[31m [ 46%][0m
tests/test_fallback_chain.py::test_all_providers_fail_raises [32mPASSED[0m[31m      [ 47%][0m
tests/test_fallback_chain.py::test_non_retryable_error_does_not_try_fallback [32mPASSED[0m[31m [ 47%][0m
tests/test_fallback_chain.py::test_local_primary_with_no_api_keys_calls_adapter_once [32mPASSED[0m[31m [ 47%][0m
tests/test_fallback_chain.py::test_available_providers_lists_configured_keys [32mPASSED[0m[31m [ 47%][0m
tests/test_fresh_install.py::test_rank_bm25_importable [32mPASSED[0m[31m            [ 47%][0m
tests/test_fresh_install.py::test_episodic_search_no_import_error [32mPASSED[0m[31m [ 47%][0m
tests/test_ftx.py::TestIdempotentInit::test_reinit_prints_already_initialized [32mPASSED[0m[31m [ 47%][0m
tests/test_ftx.py::TestIdempotentInit::test_init_does_not_lose_existing_index [32mPASSED[0m[31m [ 48%][0m
tests/test_ftx.py::TestNonInteractiveFlag::test_non_interactive_skips_wizard [32mPASSED[0m[31m [ 48%][0m
tests/test_ftx.py::TestNonInteractiveFlag::test_non_interactive_flag_accepted_by_init_project [32mPASSED[0m[31m [ 48%][0m
tests/test_ftx.py::TestReadySummary::test_print_ready_summary_outputs_tools [32mPASSED[0m[31m [ 48%][0m
tests/test_ftx.py::TestReadySummary::test_print_ready_summary_shows_youre_ready [32mPASSED[0m[31m [ 48%][0m
tests/test_ftx.py::TestReadySummary::test_print_ready_summary_shows_next_steps [32mPASSED[0m[31m [ 48%][0m
tests/test_ftx.py::TestReadySummary::test_print_ready_summary_with_index_stats [32mPASSED[0m[31m [ 49%][0m
tests/test_ftx.py::TestReadySummary::test_print_ready_summary_with_token_estimate [32mPASSED[0m[31m [ 49%][0m
tests/test_graph.py::TestKnowledgeGraph::test_add_and_exists [32mPASSED[0m[31m      [ 49%][0m
tests/test_graph.py::TestKnowledgeGraph::test_add_edge_and_neighbours [32mPASSED[0m[31m [ 49%][0m
tests/test_graph.py::TestKnowledgeGraph::test_hop_distance [32mPASSED[0m[31m        [ 49%][0m
tests/test_graph.py::TestKnowledgeGraph::test_hop_distance_disconnected [32mPASSED[0m[31m [ 49%][0m
tests/test_graph.py::TestKnowledgeGraph::test_subgraph_around [32mPASSED[0m[31m     [ 50%][0m
tests/test_graph.py::TestKnowledgeGraph::test_save_and_reload [32mPASSED[0m[31m     [ 50%][0m
tests/test_graph.py::TestKnowledgeGraph::test_idempotent_add_node [32mPASSED[0m[31m [ 50%][0m
tests/test_graph.py::TestGraphUtils::test_extract_entities_snake_case [32mPASSED[0m[31m [ 50%][0m
tests/test_graph.py::TestGraphUtils::test_extract_entities_file_extension [32mPASSED[0m[31m [ 50%][0m
tests/test_graph.py::TestGraphUtils::test_format_subgraph_empty [32mPASSED[0m[31m   [ 50%][0m
tests/test_graph.py::TestGraphUtils::test_format_subgraph_with_nodes [32mPASSED[0m[31m [ 50%][0m
tests/test_hybrid_retrieval.py::TestHybridRetriever::test_returns_list [32mPASSED[0m[31m [ 51%][0m
tests/test_hybrid_retrieval.py::TestHybridRetriever::test_final_score_present [32mPASSED[0m[31m [ 51%][0m
tests/test_hybrid_retrieval.py::TestHybridRetriever::test_top_k_respected [32mPASSED[0m[31m [ 51%][0m
tests/test_hybrid_retrieval.py::TestHybridRetriever::test_cold_start_no_crash [32mPASSED[0m[31m [ 51%][0m
tests/test_hybrid_retrieval.py::TestHybridRetriever::test_empty_store_returns_empty [32mPASSED[0m[31m [ 51%][0m
tests/test_hybrid_retrieval.py::TestHybridRetriever::test_hybrid_retrieve_function [32mPASSED[0m[31m [ 51%][0m
tests/test_hybrid_retrieval.py::TestHybridRetriever::test_scores_sorted_descending [32mPASSED[0m[31m [ 52%][0m
tests/test_hybrid_retrieval.py::TestConcurrentCacheMiss::test_concurrent_misses_call_retriever_once [32mPASSED[0m[31m [ 52%][0m
tests/test_hybrid_retrieval.py::TestEpisodicBM25::test_episodic_filter [32mPASSED[0m[31m [ 52%][0m
tests/test_hybrid_retrieval.py::TestEpisodicBM25::test_time_range_excludes_out_of_range_events [32mPASSED[0m[31m [ 52%][0m
tests/test_idle_manager.py::TestIdleManagerCore::test_initial_idle_seconds_is_small [32mPASSED[0m[31m [ 52%][0m
tests/test_idle_manager.py::TestIdleManagerCore::test_touch_resets_timer [32mPASSED[0m[31m [ 52%][0m
tests/test_idle_manager.py::TestIdleManagerCore::test_is_evicted_false_initially [32mPASSED[0m[31m [ 52%][0m
tests/test_idle_manager.py::TestIdleManagerCore::test_force_evict_calls_callbacks [32mPASSED[0m[31m [ 53%][0m
tests/test_idle_manager.py::TestIdleManagerCore::test_force_evict_sets_evicted_flag [32mPASSED[0m[31m [ 53%][0m
tests/test_idle_manager.py::TestIdleManagerCore::test_touch_clears_evicted_flag [32mPASSED[0m[31m [ 53%][0m
tests/test_idle_manager.py::TestIdleManagerCore::test_multiple_callbacks_all_called [32mPASSED[0m[31m [ 53%][0m
tests/test_idle_manager.py::TestIdleManagerCore::test_failing_callback_does_not_abort_others [32mPASSED[0m[31m [ 53%][0m
tests/test_idle_manager.py::TestIdleManagerCore::test_ttl_property [32mPASSED[0m[31m [ 53%][0m
tests/test_idle_manager.py::TestBackgroundEviction::test_background_thread_evicts_after_ttl [32mPASSED[0m[31m [ 54%][0m
tests/test_idle_manager.py::TestBackgroundEviction::test_start_is_idempotent [32mPASSED[0m[31m [ 54%][0m
tests/test_idle_manager.py::TestBackgroundEviction::test_stop_terminates_thread [32mPASSED[0m[31m [ 54%][0m
tests/test_idle_manager.py::TestSingleton::test_get_idle_manager_returns_same_instance [32mPASSED[0m[31m [ 54%][0m
tests/test_idle_manager.py::TestSingleton::test_get_idle_manager_starts_thread [32mPASSED[0m[31m [ 54%][0m
tests/test_idle_manager.py::TestSingleton::test_reset_idle_manager_clears_singleton [32mPASSED[0m[31m [ 54%][0m
tests/test_idle_manager.py::TestSingleton::test_reset_stops_thread [32mPASSED[0m[31m [ 54%][0m
tests/test_idle_manager.py::TestEvictModel::test_evict_model_clears_global [32mPASSED[0m[31m [ 55%][0m
tests/test_idle_manager.py::TestEvictModel::test_evict_model_noop_when_already_none [32mPASSED[0m[31m [ 55%][0m
tests/test_indexer_multilang.py::TestPythonBaseline::test_three_functions_extracted [32mPASSED[0m[31m [ 55%][0m
tests/test_indexer_multilang.py::TestPythonBaseline::test_class_extracted [32mPASSED[0m[31m [ 55%][0m
tests/test_indexer_multilang.py::TestPythonBaseline::test_calls_extracted_for_python [32mPASSED[0m[31m [ 55%][0m
tests/test_indexer_multilang.py::TestPythonBaseline::test_unsupported_file_returns_empty [32mPASSED[0m[31m [ 55%][0m
tests/test_indexer_multilang.py::TestPythonBaseline::test_syntax_error_py_returns_empty_symbols [32mPASSED[0m[31m [ 56%][0m
tests/test_indexer_multilang.py::TestPythonBaseline::test_sha256_cache_skip [32mPASSED[0m[31m [ 56%][0m
tests/test_indexer_multilang.py::TestPythonBaseline::test_lookup_symbol_after_index [32mPASSED[0m[31m [ 56%][0m
tests/test_indexer_multilang.py::TestJavaScriptIndexing::test_js_function_extracted [32mPASSED[0m[31m [ 56%][0m
tests/test_indexer_multilang.py::TestJavaScriptIndexing::test_lookup_js_symbol [32mPASSED[0m[31m [ 56%][0m
tests/test_indexer_multilang.py::TestJavaScriptIndexing::test_ts_file_indexed [32mPASSED[0m[31m [ 56%][0m
tests/test_indexer_multilang.py::TestJavaIndexing::test_java_class_and_method_extracted [32mPASSED[0m[31m [ 56%][0m
tests/test_indexer_multilang.py::TestJavaIndexing::test_java_lookup_method [32mPASSED[0m[31m [ 57%][0m
tests/test_indexer_multilang.py::TestLanguageRegistry::test_supported_extensions_includes_python [32mPASSED[0m[31m [ 57%][0m
tests/test_indexer_multilang.py::TestLanguageRegistry::test_unsupported_ext_not_in_supported [32mPASSED[0m[31m [ 57%][0m
tests/test_indexer_multilang.py::TestLanguageRegistry::test_missing_grammar_returns_none_no_crash [32mPASSED[0m[31m [ 57%][0m
tests/test_indexer_multilang.py::TestLanguageRegistry::test_is_supported_python_always_true [32mPASSED[0m[31m [ 57%][0m
tests/test_indexer_multilang.py::TestLanguageRegistry::test_is_supported_ruby_false [32mPASSED[0m[31m [ 57%][0m
tests/test_indexer_multilang.py::TestIndexRepoSummary::test_summary_has_language_counts [32mPASSED[0m[31m [ 58%][0m
tests/test_indexer_multilang.py::TestIndexRepoSummary::test_summary_skips_unsupported_exts [32mPASSED[0m[31m [ 58%][0m
tests/test_indexer_multilang.py::TestIndexRepoSummary::test_summary_symbol_count [32mPASSED[0m[31m [ 58%][0m
tests/test_init_seed.py::TestInitProject::test_gitignore_is_created [32mPASSED[0m[31m [ 58%][0m
tests/test_init_seed.py::TestInitProject::test_gitignore_content [32mPASSED[0m[31m  [ 58%][0m
tests/test_init_seed.py::TestInitProject::test_config_json_created [32mPASSED[0m[31m [ 58%][0m
tests/test_init_seed.py::TestInitProject::test_no_index_returns_none_triple [32mPASSED[0m[31m [ 59%][0m
tests/test_init_seed.py::TestInitProject::test_idempotent_project_id_preserved [32mPASSED[0m[31m [ 59%][0m
tests/test_init_seed.py::TestInitProject::test_no_secrets_in_config_when_keyring_available [32mPASSED[0m[31m [ 59%][0m
tests/test_init_seed.py::TestInitProject::test_prompt_n_returns_none_triple [32mPASSED[0m[31m [ 59%][0m
tests/test_init_seed.py::TestInitProject::test_prompt_no_returns_none_triple [32mPASSED[0m[31m [ 59%][0m
tests/test_init_seed.py::TestInitProject::test_scaffold_dirs_created [32mPASSED[0m[31m [ 59%][0m
tests/test_init_seed.py::TestSeedFromGitLog::test_returns_dict [32mPASSED[0m[31m    [ 59%][0m
tests/test_init_seed.py::TestSeedFromGitLog::test_non_git_dir_returns_skipped [32mPASSED[0m[31m [ 60%][0m
tests/test_init_seed.py::TestSeedFromGitLog::test_already_seeded_is_idempotent [32mPASSED[0m[31m [ 60%][0m
tests/test_init_seed.py::TestSeedFromGitLog::test_dry_run_writes_nothing [32mPASSED[0m[31m [ 60%][0m
tests/test_init_seed.py::TestSeedFromGitLog::test_seed_in_git_repo_populates_weights [33mSKIPPED[0m[31m [ 60%][0m
tests/test_isolation.py::test_no_writes_to_real_home [32mPASSED[0m[31m              [ 60%][0m
tests/test_isolation.py::test_global_dir_override_respected [32mPASSED[0m[31m       [ 60%][0m
tests/test_key_probes.py::test_probe_anthropic_401_returns_not_ok [32mPASSED[0m[31m [ 61%][0m
tests/test_key_probes.py::test_probe_anthropic_ok [32mPASSED[0m[31m                 [ 61%][0m
tests/test_key_probes.py::test_probe_gemini_401 [32mPASSED[0m[31m                   [ 61%][0m
tests/test_key_probes.py::test_probe_gemini_ok [32mPASSED[0m[31m                    [ 61%][0m
tests/test_key_probes.py::test_probe_openai_401 [32mPASSED[0m[31m                   [ 61%][0m
tests/test_key_probes.py::test_probe_grok_401 [32mPASSED[0m[31m                     [ 61%][0m
tests/test_key_probes.py::test_provider_probes_registry_has_all_keys [32mPASSED[0m[31m [ 61%][0m
tests/test_key_probes.py::test_provider_probes_all_callable [32mPASSED[0m[31m       [ 62%][0m
tests/test_language_coverage.py::test_grammar_parses_fixture[.py-args0] [32mPASSED[0m[31m [ 62%][0m
tests/test_language_coverage.py::test_grammar_parses_fixture[.js-args1] [32mPASSED[0m[31m [ 62%][0m
tests/test_language_coverage.py::test_grammar_parses_fixture[.ts-args2] [32mPASSED[0m[31m [ 62%][0m
tests/test_language_coverage.py::test_grammar_parses_fixture[.java-args3] [32mPASSED[0m[31m [ 62%][0m
tests/test_language_coverage.py::test_grammar_parses_fixture[.go-args4] [32mPASSED[0m[31m [ 62%][0m
tests/test_language_coverage.py::test_grammar_parses_fixture[.rs-args5] [32mPASSED[0m[31m [ 63%][0m
tests/test_language_coverage.py::test_grammar_parses_fixture[.cpp-args6] [32mPASSED[0m[31m [ 63%][0m
tests/test_language_coverage.py::test_language_registry_declared_grammars_importable [32mPASSED[0m[31m [ 63%][0m
tests/test_learning_middleware.py::test_intercept_after_store_captures_correction [32mPASSED[0m[31m [ 63%][0m
tests/test_learning_middleware.py::test_intercept_after_store_ignores_normal_text [32mPASSED[0m[31m [ 63%][0m
tests/test_learning_middleware.py::test_intercept_after_episode_captures_prod_issue [32mPASSED[0m[31m [ 63%][0m
tests/test_learning_store.py::test_auto_tag_type[Fixed: used synchronous db call, corrected to async-correction] [32mPASSED[0m[31m [ 63%][0m
tests/test_learning_store.py::test_auto_tag_type[Mistake: wrong approach was used here-correction] [32mPASSED[0m[31m [ 64%][0m
tests/test_learning_store.py::test_auto_tag_type[Prod issue reported: feature A had race condition-prod_issue] [32mPASSED[0m[31m [ 64%][0m
tests/test_learning_store.py::test_auto_tag_type[Root cause was a missing lock in the scheduler-prod_issue] [32mPASSED[0m[31m [ 64%][0m
tests/test_learning_store.py::test_auto_tag_type[We decided to use async db calls throughout-decision] [32mPASSED[0m[31m [ 64%][0m
tests/test_learning_store.py::test_auto_tag_type[Decision: going with FAISS over ChromaDB-decision] [32mPASSED[0m[31m [ 64%][0m
tests/test_learning_store.py::test_auto_tag_type[Auth was slow on large responses-None] [32mPASSED[0m[31m [ 64%][0m
tests/test_learning_store.py::test_auto_tag_type[updated the README-None] [32mPASSED[0m[31m [ 65%][0m
tests/test_learning_store.py::test_auto_tag_global_scope_for_ai_correction [32mPASSED[0m[31m [ 65%][0m
tests/test_learning_store.py::test_auto_tag_project_scope_for_code_decision [32mPASSED[0m[31m [ 65%][0m
tests/test_learning_store.py::test_auto_tag_none_returns_none_none [32mPASSED[0m[31m [ 65%][0m
tests/test_learning_store.py::test_project_store_round_trip [32mPASSED[0m[31m       [ 65%][0m
tests/test_learning_store.py::test_project_store_filter_by_type [32mPASSED[0m[31m   [ 65%][0m
tests/test_learning_store.py::test_global_store_round_trip [32mPASSED[0m[31m        [ 65%][0m
tests/test_learning_store.py::test_composite_merges_both_scopes [32mPASSED[0m[31m   [ 66%][0m
tests/test_learning_store.py::test_composite_auto_scope [32mPASSED[0m[31m           [ 66%][0m
tests/test_learning_store.py::test_composite_deduplication [32mPASSED[0m[31m        [ 66%][0m
tests/test_learning_store.py::test_deprecate_hides_from_retrieve [32mPASSED[0m[31m  [ 66%][0m
tests/test_learning_store.py::test_deprecate_unknown_id_returns_false [32mPASSED[0m[31m [ 66%][0m
tests/test_learning_store.py::test_deprecate_idempotent [32mPASSED[0m[31m           [ 66%][0m
tests/test_learning_store.py::test_composite_deprecate_finds_project_scope [32mPASSED[0m[31m [ 67%][0m
tests/test_learning_store.py::test_composite_deprecate_finds_global_scope [32mPASSED[0m[31m [ 67%][0m
tests/test_learning_store.py::test_composite_deprecate_unknown [32mPASSED[0m[31m    [ 67%][0m
tests/test_learning_store.py::test_supersede_replaces_old_with_new [32mPASSED[0m[31m [ 67%][0m
tests/test_learning_store.py::test_supersede_new_record_carries_supersedes_field [32mPASSED[0m[31m [ 67%][0m
tests/test_learning_store.py::test_composite_supersede_end_to_end [32mPASSED[0m[31m [ 67%][0m
tests/test_learning_store.py::test_detect_conflicts_returns_similar_records [32mPASSED[0m[31m [ 68%][0m
tests/test_learning_store.py::test_detect_conflicts_ignores_deprecated [32mPASSED[0m[31m [ 68%][0m
tests/test_learning_store.py::test_detect_conflicts_no_match_returns_empty [32mPASSED[0m[31m [ 68%][0m
tests/test_learning_store.py::test_composite_detect_conflicts_merges_scopes [32mPASSED[0m[31m [ 68%][0m
tests/test_local_adapter.py::test_resolve_locally_returns_pattern_answer [32mPASSED[0m[31m [ 68%][0m
tests/test_local_adapter.py::test_resolve_locally_falls_through_to_docs [32mPASSED[0m[31m [ 68%][0m
tests/test_local_adapter.py::test_resolve_locally_returns_none_when_all_fail [32mPASSED[0m[31m [ 68%][0m
tests/test_local_adapter.py::test_resolve_locally_handles_exception_gracefully [32mPASSED[0m[31m [ 69%][0m
tests/test_local_adapter.py::test_call_returns_model_response_when_answer_found [32mPASSED[0m[31m [ 69%][0m
tests/test_local_adapter.py::test_call_raises_no_local_answer_when_nothing_found [32mPASSED[0m[31m [ 69%][0m
tests/test_local_adapter.py::test_call_stream_yields_answer [32mPASSED[0m[31m       [ 69%][0m
tests/test_local_adapter.py::test_call_stream_raises_no_local_answer [32mPASSED[0m[31m [ 69%][0m
tests/test_local_adapter.py::test_call_provider_is_local [32mPASSED[0m[31m          [ 69%][0m
tests/test_logging.py::test_new_trace_id_returns_hex_string [32mPASSED[0m[31m       [ 70%][0m
tests/test_logging.py::test_get_trace_id_returns_set_value [32mPASSED[0m[31m        [ 70%][0m
tests/test_logging.py::test_get_trace_id_none_when_unset [32mPASSED[0m[31m          [ 70%][0m
tests/test_logging.py::test_json_formatter_produces_valid_ndjson [32mPASSED[0m[31m  [ 70%][0m
tests/test_logging.py::test_json_formatter_trace_id_null_when_unset [32mPASSED[0m[31m [ 70%][0m
tests/test_logging.py::test_setup_logging_idempotent [32mPASSED[0m[31m              [ 70%][0m
tests/test_logging.py::test_setup_logging_does_not_write_to_stdout [32mPASSED[0m[31m [ 70%][0m
tests/test_mcp_server.py::TestMCPToolFunctions::test_store_memory_tool [32mPASSED[0m[31m [ 71%][0m
tests/test_mcp_server.py::TestMCPToolFunctions::test_retrieve_memory_tool_returns_list [32mPASSED[0m[31m [ 71%][0m
tests/test_mcp_server.py::TestMCPToolFunctions::test_retrieve_memory_empty_store [32mPASSED[0m[31m [ 71%][0m
tests/test_mcp_server.py::TestMCPToolFunctions::test_log_episode_tool [32mPASSED[0m[31m [ 71%][0m
tests/test_mcp_server.py::TestMCPToolFunctions::test_manifest_written [32mPASSED[0m[31m [ 71%][0m
tests/test_mcp_server.py::TestMCPToolFunctions::test_store_memory_importance_non_negative [32mPASSED[0m[31m [ 71%][0m
tests/test_mcp_server.py::TestMCPToolFunctions::test_store_memory_source_preserved [32mPASSED[0m[31m [ 72%][0m
tests/test_mcp_server.py::TestNewMCPTools::test_lookup_symbol_returns_list [32mPASSED[0m[31m [ 72%][0m
tests/test_mcp_server.py::TestNewMCPTools::test_lookup_symbol_entries_have_required_fields [32mPASSED[0m[31m [ 72%][0m
tests/test_mcp_server.py::TestNewMCPTools::test_who_calls_returns_list [32mPASSED[0m[31m [ 72%][0m
tests/test_mcp_server.py::TestNewMCPTools::test_who_calls_entries_have_required_fields [32mPASSED[0m[31m [ 72%][0m
tests/test_mcp_server.py::TestNewMCPTools::test_subgraph_returns_dict_with_nodes_and_edges [32mPASSED[0m[31m [ 72%][0m
tests/test_mcp_server.py::TestNewMCPTools::test_subgraph_is_json_serialisable [32mPASSED[0m[31m [ 72%][0m
tests/test_mcp_server.py::TestNewMCPTools::test_episodic_search_returns_list [32mPASSED[0m[31m [ 73%][0m
tests/test_mcp_server.py::TestNewMCPTools::test_episodic_search_matches_keyword [32mPASSED[0m[31m [ 73%][0m
tests/test_mcp_server.py::TestNewMCPTools::test_episodic_search_limit_respected [32mPASSED[0m[31m [ 73%][0m
tests/test_mcp_server.py::TestNewMCPTools::test_graph_stats_returns_expected_keys [32mPASSED[0m[31m [ 73%][0m
tests/test_mcp_server.py::TestNewMCPTools::test_graph_stats_counts_are_non_negative [32mPASSED[0m[31m [ 73%][0m
tests/test_mcp_server.py::TestNewMCPTools::test_graph_stats_top_concepts_is_list [32mPASSED[0m[31m [ 73%][0m
tests/test_mcp_server.py::TestNewMCPTools::test_manifest_includes_new_tools [32mPASSED[0m[31m [ 74%][0m
tests/test_mcp_server.py::TestEmptyGraphWarnings::test_lookup_symbol_warns_when_graph_empty [32mPASSED[0m[31m [ 74%][0m
tests/test_mcp_server.py::TestEmptyGraphWarnings::test_who_calls_warns_when_graph_empty [32mPASSED[0m[31m [ 74%][0m
tests/test_mcp_server.py::TestEmptyGraphWarnings::test_subgraph_warns_when_graph_empty [32mPASSED[0m[31m [ 74%][0m
tests/test_mcp_server.py::TestEmptyGraphWarnings::test_warning_message_contains_index_repo_hint [32mPASSED[0m[31m [ 74%][0m
tests/test_mcp_server.py::TestEmptyGraphWarnings::test_no_warning_after_graph_populated [32mPASSED[0m[31m [ 74%][0m
tests/test_mcp_server.py::TestManifestFormat::test_manifest_tools_have_required_fields [32mPASSED[0m[31m [ 75%][0m
tests/test_mcp_server.py::TestManifestFormat::test_openai_spec_export [32mPASSED[0m[31m [ 75%][0m
tests/test_memory.py::TestSemanticMemory::test_store_and_retrieve [32mPASSED[0m[31m [ 75%][0m
tests/test_memory.py::TestSemanticMemory::test_importance_score_positive [32mPASSED[0m[31m [ 75%][0m
tests/test_memory.py::TestSemanticMemory::test_multiple_store_retrieve [32mPASSED[0m[31m [ 75%][0m
tests/test_memory.py::TestSemanticMemory::test_retrieve_top_k_respected [32mPASSED[0m[31m [ 75%][0m
tests/test_memory.py::TestEpisodicMemory::test_log_and_retrieve [32mPASSED[0m[31m   [ 75%][0m
tests/test_memory.py::TestEpisodicMemory::test_history_order [32mPASSED[0m[31m      [ 76%][0m
tests/test_memory.py::TestEpisodicMemory::test_history_limit [32mPASSED[0m[31m      [ 76%][0m
tests/test_memory.py::TestEpisodicMemory::test_event_has_required_fields [32mPASSED[0m[31m [ 76%][0m
tests/test_memory.py::TestEpisodicMemory::test_metadata_stored [32mPASSED[0m[31m    [ 76%][0m
tests/test_metrics.py::test_metrics_endpoint_exists [33mSKIPPED[0m (REST AP...)[31m [ 76%][0m
tests/test_metrics.py::test_metrics_content_when_available [33mSKIPPED[0m (...)[31m [ 76%][0m
tests/test_metrics.py::test_metrics_501_when_unavailable [33mSKIPPED[0m (RE...)[31m [ 77%][0m
tests/test_metrics.py::test_memory_ops_counter_increments [32mPASSED[0m[31m         [ 77%][0m
tests/test_metrics.py::test_circuit_breaker_gauge_updates [32mPASSED[0m[31m         [ 77%][0m
tests/test_metrics_server.py::test_standalone_metrics_server_serves_metrics [32mPASSED[0m[31m [ 77%][0m
tests/test_metrics_server.py::test_standalone_metrics_server_404_on_unknown_path [32mPASSED[0m[31m [ 77%][0m
tests/test_multilang_indexer.py::TestTypeScriptIndexing::test_ts_function_extracted [32mPASSED[0m[31m [ 77%][0m
tests/test_multilang_indexer.py::TestTypeScriptIndexing::test_ts_interface_extracted [32mPASSED[0m[31m [ 77%][0m
tests/test_multilang_indexer.py::TestTypeScriptIndexing::test_tsx_function_extracted [32mPASSED[0m[31m [ 78%][0m
tests/test_multilang_indexer.py::TestTypeScriptIndexing::test_lookup_ts_symbol [32mPASSED[0m[31m [ 78%][0m
tests/test_multilang_indexer.py::TestTypeScriptIndexing::test_ts_uses_typescript_grammar_not_javascript [32mPASSED[0m[31m [ 78%][0m
tests/test_multilang_indexer.py::TestGoIndexing::test_go_function_extracted [32mPASSED[0m[31m [ 78%][0m
tests/test_multilang_indexer.py::TestGoIndexing::test_lookup_go_symbol [32mPASSED[0m[31m [ 78%][0m
tests/test_multilang_indexer.py::TestGoIndexing::test_go_symbol_count_positive [32mPASSED[0m[31m [ 78%][0m
tests/test_multilang_indexer.py::TestRustIndexing::test_rust_function_extracted [32mPASSED[0m[31m [ 79%][0m
tests/test_multilang_indexer.py::TestLanguageRegistryV2::test_ts_grammar_is_typescript_not_javascript [32mPASSED[0m[31m [ 79%][0m
tests/test_multilang_indexer.py::TestLanguageRegistryV2::test_tsx_uses_tsx_function [32mPASSED[0m[31m [ 79%][0m
tests/test_multilang_indexer.py::TestLanguageRegistryV2::test_ts_lang_name_is_typescript [32mPASSED[0m[31m [ 79%][0m
tests/test_multilang_indexer.py::TestLanguageRegistryV2::test_go_supported [32mPASSED[0m[31m [ 79%][0m
tests/test_multilang_indexer.py::TestLanguageRegistryV2::test_rust_supported [32mPASSED[0m[31m [ 79%][0m
tests/test_multilang_indexer.py::TestWatchdogCoverage::test_supported_extensions_trigger_reindex[.ts] [32mPASSED[0m[31m [ 79%][0m
tests/test_multilang_indexer.py::TestWatchdogCoverage::test_supported_extensions_trigger_reindex[.tsx] [32mPASSED[0m[31m [ 80%][0m
tests/test_multilang_indexer.py::TestWatchdogCoverage::test_supported_extensions_trigger_reindex[.go] [32mPASSED[0m[31m [ 80%][0m
tests/test_multilang_indexer.py::TestWatchdogCoverage::test_supported_extensions_trigger_reindex[.rs] [32mPASSED[0m[31m [ 80%][0m
tests/test_multilang_indexer.py::TestWatchdogCoverage::test_supported_extensions_trigger_reindex[.java] [32mPASSED[0m[31m [ 80%][0m
tests/test_multilang_indexer.py::TestWatchdogCoverage::test_supported_extensions_trigger_reindex[.py] [32mPASSED[0m[31m [ 80%][0m
tests/test_multilang_indexer.py::TestWatchdogCoverage::test_unsupported_ext_not_triggered [32mPASSED[0m[31m [ 80%][0m
tests/test_multilang_indexer.py::TestWatchdogCoverage::test_cache_invalidated_on_reindex [32mPASSED[0m[31m [ 81%][0m
tests/test_multilang_indexer.py::TestWatchdogCoverage::test_cache_invalidated_on_remove [32mPASSED[0m[31m [ 81%][0m
tests/test_org_graph.py::TestOrgGraphConcurrentWrite::test_two_thread_writes_no_corruption [32mPASSED[0m[31m [ 81%][0m
tests/test_org_graph.py::TestOrgGraphEncryption::test_plaintext_round_trip [32mPASSED[0m[31m [ 81%][0m
tests/test_org_graph.py::TestOrgGraphEncryption::test_encrypt_round_trip [32mPASSED[0m[31m [ 81%][0m
tests/test_org_graph.py::TestOrgGraphEncryption::test_corrupt_file_falls_back_to_empty [32mPASSED[0m[31m [ 81%][0m
tests/test_orgs.py::test_create_and_list_orgs [32mPASSED[0m[31m                     [ 81%][0m
tests/test_orgs.py::test_link_and_unlink_repo [32mPASSED[0m[31m                     [ 82%][0m
tests/test_orgs.py::test_get_repo_org_none [32mPASSED[0m[31m                        [ 82%][0m
tests/test_post_release.py::test_version_is_semver [32mPASSED[0m[31m                [ 82%][0m
tests/test_post_release.py::test_hard_dependencies_importable [32mPASSED[0m[31m     [ 82%][0m
tests/test_post_release.py::test_cli_entrypoint_responds [32mPASSED[0m[31m          [ 82%][0m
tests/test_post_release.py::test_no_dev_path_imports [32mPASSED[0m[31m              [ 82%][0m
tests/test_prune_memory.py::test_rebuild_writes_to_configured_path [32mPASSED[0m[31m [ 83%][0m
tests/test_router.py::TestWhereIs::test_basic [32mPASSED[0m[31m                     [ 83%][0m
tests/test_router.py::TestWhereIs::test_with_question_mark [32mPASSED[0m[31m        [ 83%][0m
tests/test_router.py::TestWhereIs::test_where_can_i_find [32mPASSED[0m[31m          [ 83%][0m
tests/test_router.py::TestWhereIs::test_lookup_none_falls_through [32mPASSED[0m[31m [ 83%][0m
tests/test_router.py::TestWhoCalls::test_basic [32mPASSED[0m[31m                    [ 83%][0m
tests/test_router.py::TestWhoCalls::test_with_question_mark [32mPASSED[0m[31m       [ 84%][0m
tests/test_router.py::TestWhoCalls::test_who_calls_none_falls_through [32mPASSED[0m[31m [ 84%][0m
tests/test_router.py::TestListFiles::test_list_files [32mPASSED[0m[31m              [ 84%][0m
tests/test_router.py::TestListFiles::test_what_files [32mPASSED[0m[31m              [ 84%][0m
tests/test_router.py::TestListFiles::test_show_files [32mPASSED[0m[31m              [ 84%][0m
tests/test_router.py::TestListFiles::test_list_files_none_falls_through [32mPASSED[0m[31m [ 84%][0m
tests/test_router.py::TestGraphStats::test_graph_stats [31mFAILED[0m[31m            [ 84%][0m
tests/test_router.py::TestGraphStats::test_how_many_nodes [32mPASSED[0m[31m         [ 85%][0m
tests/test_router.py::TestGraphStats::test_graph_size [31mFAILED[0m[31m             [ 85%][0m
tests/test_router.py::TestRecentHistory::test_recent_history [32mPASSED[0m[31m      [ 85%][0m
tests/test_router.py::TestRecentHistory::test_what_did_i_do [32mPASSED[0m[31m       [ 85%][0m
tests/test_router.py::TestRecentHistory::test_show_history [32mPASSED[0m[31m        [ 85%][0m
tests/test_router.py::TestFallthrough::test_complex_reasoning_query [32mPASSED[0m[31m [ 85%][0m
tests/test_router.py::TestFallthrough::test_architectural_query [32mPASSED[0m[31m   [ 86%][0m
tests/test_router.py::TestFallthrough::test_greeting [32mPASSED[0m[31m              [ 86%][0m
tests/test_router.py::TestFallthrough::test_unrelated_question [32mPASSED[0m[31m    [ 86%][0m
tests/test_scheduler.py::test_scheduler_fires_task [32mPASSED[0m[31m                [ 86%][0m
tests/test_scheduler.py::test_scheduler_stop_prevents_future_runs [32mPASSED[0m[31m [ 86%][0m
tests/test_scheduler.py::test_scheduler_skips_when_breaker_open [32mPASSED[0m[31m   [ 86%][0m
tests/test_scheduler.py::test_scheduler_next_run_advances [32mPASSED[0m[31m         [ 86%][0m
tests/test_semantic_search_code.py::TestSemanticSearchCode::test_returns_list [32mPASSED[0m[31m [ 87%][0m
tests/test_semantic_search_code.py::TestSemanticSearchCode::test_returns_empty_when_no_index [32mPASSED[0m[31m [ 87%][0m
tests/test_semantic_search_code.py::TestSemanticSearchCode::test_result_fields [32mPASSED[0m[31m [ 87%][0m
tests/test_semantic_search_code.py::TestSemanticSearchCode::test_language_filter_python [32mPASSED[0m[31m [ 87%][0m
tests/test_semantic_search_code.py::TestSemanticSearchCode::test_language_filter_typescript [32mPASSED[0m[31m [ 87%][0m
tests/test_semantic_search_code.py::TestSemanticSearchCode::test_no_episodic_entries_in_results [32mPASSED[0m[31m [ 87%][0m
tests/test_semantic_search_code.py::TestSemanticSearchCode::test_retrieve_memory_unaffected [32mPASSED[0m[31m [ 88%][0m
tests/test_session.py::TestCreateLoad::test_create_returns_session_dict [32mPASSED[0m[31m [ 88%][0m
tests/test_session.py::TestCreateLoad::test_create_writes_json_file [32mPASSED[0m[31m [ 88%][0m
tests/test_session.py::TestCreateLoad::test_create_sets_current_pointer [32mPASSED[0m[31m [ 88%][0m
tests/test_session.py::TestCreateLoad::test_load_session_returns_dict [32mPASSED[0m[31m [ 88%][0m
tests/test_session.py::TestCreateLoad::test_load_missing_session_returns_none [32mPASSED[0m[31m [ 88%][0m
tests/test_session.py::TestCreateLoad::test_load_current_session [32mPASSED[0m[31m  [ 88%][0m
tests/test_session.py::TestCreateLoad::test_load_current_session_when_none_exists [32mPASSED[0m[31m [ 89%][0m
tests/test_session.py::TestCreateLoad::test_create_model_stored [32mPASSED[0m[31m   [ 89%][0m
tests/test_session.py::TestFindSession::test_exact_id_match [32mPASSED[0m[31m       [ 89%][0m
tests/test_session.py::TestFindSession::test_prefix_match [32mPASSED[0m[31m         [ 89%][0m
tests/test_session.py::TestFindSession::test_ambiguous_prefix_returns_none [32mPASSED[0m[31m [ 89%][0m
tests/test_session.py::TestFindSession::test_nonexistent_prefix_returns_none [32mPASSED[0m[31m [ 89%][0m
tests/test_session.py::TestAppendExchange::test_append_adds_two_messages [32mPASSED[0m[31m [ 90%][0m
tests/test_session.py::TestAppendExchange::test_append_persists_to_disk [32mPASSED[0m[31m [ 90%][0m
tests/test_session.py::TestAppendExchange::test_second_exchange_accumulates [32mPASSED[0m[31m [ 90%][0m
tests/test_session.py::TestAppendExchange::test_history_capped_at_max_exchanges [32mPASSED[0m[31m [ 90%][0m
tests/test_session.py::TestAppendExchange::test_oldest_exchange_dropped_on_overflow [32mPASSED[0m[31m [ 90%][0m
tests/test_session.py::TestAppendExchange::test_newest_messages_survive_trim [32mPASSED[0m[31m [ 90%][0m
tests/test_session.py::TestAppendExchange::test_cap_at_one_exchange [32mPASSED[0m[31m [ 90%][0m
tests/test_session.py::TestAppendExchange::test_messages_remain_balanced_after_trim [32mPASSED[0m[31m [ 91%][0m
tests/test_session.py::TestListSessions::test_empty_when_no_sessions [32mPASSED[0m[31m [ 91%][0m
tests/test_session.py::TestListSessions::test_returns_created_sessions [32mPASSED[0m[31m [ 91%][0m
tests/test_session.py::TestListSessions::test_sorted_newest_first [32mPASSED[0m[31m [ 91%][0m
tests/test_session.py::TestListSessions::test_limit_respected [32mPASSED[0m[31m     [ 91%][0m
tests/test_session.py::TestListSessions::test_no_limit_returns_all [32mPASSED[0m[31m [ 91%][0m
tests/test_session.py::TestListSessions::test_current_session_pointer [32mPASSED[0m[31m [ 92%][0m
tests/test_session.py::TestAdapterHistory::test_anthropic_history_in_messages [32mPASSED[0m[31m [ 92%][0m
tests/test_session.py::TestAdapterHistory::test_openai_history_after_system_message [32mPASSED[0m[31m [ 92%][0m
tests/test_session.py::TestAdapterHistory::test_gemini_history_converts_assistant_to_model [32mPASSED[0m[31m [ 92%][0m
tests/test_session.py::TestAdapterHistory::test_gemini_no_history_returns_string [32mPASSED[0m[31m [ 92%][0m
tests/test_session_isolation.py::test_project_dir_isolates_sessions [32mPASSED[0m[31m [ 92%][0m
tests/test_session_listener.py::test_on_session_end_marks_closed [32mPASSED[0m[31m  [ 93%][0m
tests/test_session_listener.py::test_on_session_end_idempotent [32mPASSED[0m[31m    [ 93%][0m
tests/test_session_listener.py::test_recover_unclosed_sessions [32mPASSED[0m[31m    [ 93%][0m
tests/test_stale_cleanup.py::TestGraphRemoveFileNodes::test_removes_symbol_nodes_and_file_node [32mPASSED[0m[31m [ 93%][0m
tests/test_stale_cleanup.py::TestGraphRemoveFileNodes::test_returns_empty_for_unknown_file [32mPASSED[0m[31m [ 93%][0m
tests/test_stale_cleanup.py::TestGraphRemoveFileNodes::test_edges_removed_with_nodes [32mPASSED[0m[31m [ 93%][0m
tests/test_stale_cleanup.py::TestEpisodicMarkStale::test_matching_entries_tagged_stale [32mPASSED[0m[31m [ 93%][0m
tests/test_stale_cleanup.py::TestEpisodicMarkStale::test_stale_entries_still_queryable [32mPASSED[0m[31m [ 94%][0m
tests/test_stale_cleanup.py::TestEpisodicMarkStale::test_already_stale_not_double_tagged [32mPASSED[0m[31m [ 94%][0m
tests/test_stale_cleanup.py::TestFileWatcherRemove::test_removes_file_from_index_data [32mPASSED[0m[31m [ 94%][0m
tests/test_stale_cleanup.py::TestFileWatcherRemove::test_rebuild_and_save_called [32mPASSED[0m[31m [ 94%][0m
tests/test_stale_cleanup.py::TestFileWatcherRemove::test_rename_delete_then_create [32mPASSED[0m[31m [ 94%][0m
tests/test_storage_adapter.py::TestAdapterABC::test_cannot_instantiate_abc [32mPASSED[0m[31m [ 94%][0m
tests/test_storage_adapter.py::TestAdapterABC::test_all_abstract_methods_declared [32mPASSED[0m[31m [ 95%][0m
tests/test_storage_adapter.py::TestLocalVectorDB::test_implements_adapter_interface [32mPASSED[0m[31m [ 95%][0m
tests/test_storage_adapter.py::TestLocalVectorDB::test_add_and_search [32mPASSED[0m[31m [ 95%][0m
tests/test_storage_adapter.py::TestLocalVectorDB::test_search_with_scores_returns_distance [32mPASSED[0m[31m [ 95%][0m
tests/test_storage_adapter.py::TestLocalVectorDB::test_remove_is_soft_delete [32mPASSED[0m[31m [ 95%][0m
tests/test_storage_adapter.py::TestLocalVectorDB::test_persist_calls_save [32mPASSED[0m[31m [ 95%][0m
tests/test_storage_adapter.py::TestLocalVectorDB::test_source_filter [32mPASSED[0m[31m [ 95%][0m
tests/test_storage_adapter.py::TestLocalVectorDB::test_update_behaviour_score [32mPASSED[0m[31m [ 96%][0m
tests/test_storage_adapter.py::TestChromaDBAdapter::test_raises_import_error_when_chromadb_missing [32mPASSED[0m[31m [ 96%][0m
tests/test_storage_adapter.py::TestChromaDBAdapter::test_implements_adapter_interface [32mPASSED[0m[31m [ 96%][0m
tests/test_storage_adapter.py::TestGetVectorAdapter::test_default_returns_local_vector_db [32mPASSED[0m[31m [ 96%][0m
tests/test_storage_adapter.py::TestGetVectorAdapter::test_chroma_config_returns_chroma_adapter_class [32mPASSED[0m[31m [ 96%][0m
tests/test_summarizer.py::test_summarize_file_logic [32mPASSED[0m[31m               [ 96%][0m
tests/test_summarizer.py::test_run_full_summarization [32mPASSED[0m[31m             [ 97%][0m
tests/test_tier1_dogfood.py::test_classifier_routes_cognirepo_question_to_quick [32mPASSED[0m[31m [ 97%][0m
tests/test_tier1_dogfood.py::test_classifier_routes_mcp_question_to_quick [32mPASSED[0m[31m [ 97%][0m
tests/test_tier1_dogfood.py::test_classifier_docs_override_does_not_fire_for_unrelated [32mPASSED[0m[31m [ 97%][0m
tests/test_tier1_dogfood.py::test_try_local_resolve_returns_docs_answer_above_threshold [32mPASSED[0m[31m [ 97%][0m
tests/test_tier1_dogfood.py::test_try_local_resolve_ignores_low_confidence_docs [32mPASSED[0m[31m [ 97%][0m
tests/test_tier1_dogfood.py::test_try_local_resolve_skips_docs_when_not_docs_query [32mPASSED[0m[31m [ 97%][0m
tests/test_tier1_dogfood.py::test_try_local_resolve_handles_docs_index_none [32mPASSED[0m[31m [ 98%][0m
tests/test_tier1_dogfood.py::test_try_local_resolve_handles_docs_index_exception [32mPASSED[0m[31m [ 98%][0m
tests/test_tool_init.py::test_cursor_mcp_creates_file [32mPASSED[0m[31m             [ 98%][0m
tests/test_tool_init.py::test_cursor_mcp_contains_project_dir [32mPASSED[0m[31m     [ 98%][0m
tests/test_tool_init.py::test_cursor_mcp_idempotent [32mPASSED[0m[31m               [ 98%][0m
tests/test_tool_init.py::test_cursor_mcp_no_binary_falls_back_to_python [32mPASSED[0m[31m [ 98%][0m
tests/test_tool_init.py::test_vscode_mcp_creates_file [32mPASSED[0m[31m             [ 99%][0m
tests/test_tool_init.py::test_vscode_mcp_has_type_stdio [32mPASSED[0m[31m           [ 99%][0m
tests/test_tool_init.py::test_vscode_mcp_idempotent [32mPASSED[0m[31m               [ 99%][0m
tests/test_tool_init.py::test_setup_mcp_cursor_only [32mPASSED[0m[31m               [ 99%][0m
tests/test_tool_init.py::test_setup_mcp_vscode_only [32mPASSED[0m[31m               [ 99%][0m
tests/test_tool_init.py::test_setup_mcp_all_tools [32mPASSED[0m[31m                 [ 99%][0m
tests/test_tool_init.py::test_setup_mcp_empty_targets [32mPASSED[0m[31m             [100%][0m

=================================== FAILURES ===================================
[31m[1m________________ TestTokenReduction.test_token_savings_reported ________________[0m
[1m[31m/home/ashlesh/my_works/cognirepo/tests/test_claude_usefulness.py[0m:87: in test_token_savings_reported
    [0m[94massert[39;49;00m result[[33m"[39;49;00m[33mtoken_count[39;49;00m[33m"[39;49;00m] > [94m0[39;49;00m[90m[39;49;00m
[1m[31mE   assert 0 > 0[0m
---------------------------- Captured stdout setup -----------------------------
Already initialized — updating config without losing existing index.
Updated /tmp/pytest-of-ashlesh/pytest-14/test_token_savings_reported0/.cognirepo/config.json with missing keys.
.env created from .env.example — review it to tune circuit breaker limits or add API keys.

CogniRepo initialised.

Storage encryption: disabled
  → Enable: set storage.encrypt: true in .cognirepo/config.json
Skipping index (--no-index). Run 'cognirepo index-repo .' when ready.
  Embedding 6 texts in batches of 256…
Indexed 3 symbols across 3 files
  Python: 3 files

  Cold-start status:
    graph_score     : 0.0 (cold)
    behaviour_score : 0.0 (needs ~50 queries to calibrate, have 0)
    Currently running: pure vector search
    Run `cognirepo seed --from-git` to prime graph from git history

[31m[1m_______________________ TestGraphStats.test_graph_stats ________________________[0m
[1m[31m/home/ashlesh/my_works/cognirepo/tests/test_router.py[0m:106: in test_graph_stats
    [0m[94massert[39;49;00m m.called[90m[39;49;00m
[1m[31mE   AssertionError: assert False[0m
[1m[31mE    +  where False = <MagicMock name='_graph_stats' id='139757624653344'>.called[0m
[31m[1m________________________ TestGraphStats.test_graph_size ________________________[0m
[1m[31m/home/ashlesh/my_works/cognirepo/tests/test_router.py[0m:116: in test_graph_size
    [0m[94massert[39;49;00m m.called[90m[39;49;00m
[1m[31mE   AssertionError: assert False[0m
[1m[31mE    +  where False = <MagicMock name='_graph_stats' id='139757258603360'>.called[0m
[36m[1m=========================== short test summary info ============================[0m
[31mFAILED[0m tests/test_claude_usefulness.py::[1mTestTokenReduction::test_token_savings_reported[0m - assert 0 > 0
[31mFAILED[0m tests/test_router.py::[1mTestGraphStats::test_graph_stats[0m - AssertionError: assert False
[31mFAILED[0m tests/test_router.py::[1mTestGraphStats::test_graph_size[0m - AssertionError: assert False
[31m============= [31m[1m3 failed[0m, [32m636 passed[0m, [33m5 skipped[0m[31m in 113.97s (0:01:53)[0m[31m =============[0m
```

## Summary of Failures
```text
=================================== FAILURES ===================================
[31m[1m________________ TestTokenReduction.test_token_savings_reported ________________[0m
[1m[31m/home/ashlesh/my_works/cognirepo/tests/test_claude_usefulness.py[0m:87: in test_token_savings_reported
    [0m[94massert[39;49;00m result[[33m"[39;49;00m[33mtoken_count[39;49;00m[33m"[39;49;00m] > [94m0[39;49;00m[90m[39;49;00m
[1m[31mE   assert 0 > 0[0m
---------------------------- Captured stdout setup -----------------------------
Already initialized — updating config without losing existing index.
Updated /tmp/pytest-of-ashlesh/pytest-14/test_token_savings_reported0/.cognirepo/config.json with missing keys.
.env created from .env.example — review it to tune circuit breaker limits or add API keys.

CogniRepo initialised.

Storage encryption: disabled
  → Enable: set storage.encrypt: true in .cognirepo/config.json
Skipping index (--no-index). Run 'cognirepo index-repo .' when ready.
  Embedding 6 texts in batches of 256…
Indexed 3 symbols across 3 files
  Python: 3 files

  Cold-start status:
    graph_score     : 0.0 (cold)
    behaviour_score : 0.0 (needs ~50 queries to calibrate, have 0)
    Currently running: pure vector search
    Run `cognirepo seed --from-git` to prime graph from git history

[31m[1m_______________________ TestGraphStats.test_graph_stats ________________________[0m
[1m[31m/home/ashlesh/my_works/cognirepo/tests/test_router.py[0m:106: in test_graph_stats
    [0m[94massert[39;49;00m m.called[90m[39;49;00m
[1m[31mE   AssertionError: assert False[0m
[1m[31mE    +  where False = <MagicMock name='_graph_stats' id='139757624653344'>.called[0m
[31m[1m________________________ TestGraphStats.test_graph_size ________________________[0m
[1m[31m/home/ashlesh/my_works/cognirepo/tests/test_router.py[0m:116: in test_graph_size
    [0m[94massert[39;49;00m m.called[90m[39;49;00m
[1m[31mE   AssertionError: assert False[0m
[1m[31mE    +  where False = <MagicMock name='_graph_stats' id='139757258603360'>.called[0m
[36m[1m=========================== short test summary info ============================[0m
[31mFAILED[0m tests/test_claude_usefulness.py::[1mTestTokenReduction::test_token_savings_reported[0m - assert 0 > 0
[31mFAILED[0m tests/test_router.py::[1mTestGraphStats::test_graph_stats[0m - AssertionError: assert False
[31mFAILED[0m tests/test_router.py::[1mTestGraphStats::test_graph_size[0m - AssertionError: assert False
[31m============= [31m[1m3 failed[0m, [32m636 passed[0m, [33m5 skipped[0m[31m in 113.97s (0:01:53)[0m[31m =============[0m
```
