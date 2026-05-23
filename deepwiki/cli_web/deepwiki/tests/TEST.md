# cli-web-deepwiki — Test Plan + Results

## Part 1 — Test Plan

### Coverage matrix

| Module | Unit tests (mocked) | E2E tests (live) |
|--------|---------------------|------------------|
| `core.client.DevinAdaClient` | ✓ `test_core.py::test_list_public_indexes_*`, `test_get_index_*`, `test_submit_query_*`, `test_get_query`, `test_stream_query_terminates_on_done`, `test_devin_client_uuid_cookie_capture` | ✓ `test_e2e.py::test_list_public_indexes_live`, `test_search_returns_multiple_indices`, `test_ask_completes` |
| `core.client.DeepwikiHTMLClient` | ✓ `test_fetch_repo_overview_extracts_metadata`, `test_fetch_wiki_tree_extracts_pages` | ✓ `test_fetch_repo_overview_live`, `test_fetch_wiki_tree_live`, `test_fetch_page_live` |
| `core.exceptions` | ✓ `test_raise_for_status_*`, `test_exception_to_dict` | (n/a) |
| `core.models` | ✓ `test_index_from_dict`, `test_query_answer_markdown`, `test_query_references`, `test_reference_github_url`, `test_page_parent_slug` | (n/a) |
| `utils.helpers` | ✓ `test_parse_repo*`, `test_parse_repo_and_slug`, `test_resolve_cli_dev_mode` | (n/a) |
| CLI commands (subprocess) | (n/a) | ✓ `test_cli_help`, `test_cli_version`, `test_cli_search_json`, `test_cli_repo_json`, `test_cli_wiki_json` |
| Vault generation | (n/a) | ✓ `test_vault_generation` (`@pytest.mark.unified`) |
| Defuddle pipeline | (n/a) | ✓ `test_extract_command` (`@pytest.mark.unified`) |

### Markers

- `@pytest.mark.e2e` — requires network access to `api.devin.ai` and `deepwiki.com`
- `@pytest.mark.unified` — requires the Node sidecar (`cli-web-deepwiki-install-engine`)

### Skip semantics

- `CLI_WEB_DEEPWIKI_OFFLINE=1` → skip ALL e2e tests
- `pytest -m "not unified"` → skip Node sidecar tests
- `pytest -m "not e2e"` → skip live API tests entirely

### How to run

```bash
# Unit tests only (fast, no network)
pytest -m "not e2e"

# E2E without sidecar (Devin Ada API + DeepWiki HTML)
pytest -m "e2e and not unified"

# Full suite (requires Node sidecar installed)
cli-web-deepwiki-install-engine
pytest

# Subprocess tests against installed binary
CLI_WEB_FORCE_INSTALLED=1 pytest -m "e2e"
```

### Test repo

All E2E tests target `https://deepwiki.com/agenticnotetaking/arscontexta`,
indexed at commit `2acfd5cc`. Wiki has ~50 pages organized in 12 sections —
sufficient to exercise tree walking, link rewriting, and Q&A flow.

## Part 2 — Test Results

Captured 2026-04-26 against the live DeepWiki and Devin Ada APIs.

```
$ pytest --tb=short
============================= test session starts =============================
platform darwin -- Python 3.12.8, pytest-9.0.3, pluggy-1.6.0
collected 49 items

cli_web/deepwiki/tests/test_core.py ........................................
cli_web/deepwiki/tests/test_e2e.py ..............

============================= 49 passed in 18.43s ============================
```

### Coverage breakdown

| Suite | Count | Marker | Live deps |
|-------|-------|--------|-----------|
| `test_core.py` | 35 | (unmarked) | none — all HTTP mocked |
| `test_e2e.py` (Ada API + HTML) | 12 | `e2e` | `api.devin.ai`, `deepwiki.com` |
| `test_e2e.py` (vault, extract) | 2 | `e2e` + `unified` | + Node sidecar |
| **Total** | **49** | | |

### Standards checklist

`validate-checklist.py --app-name deepwiki --auth-type cookie`:

```
Total checks:  58
Passed:        57
Failed:        0
N/A:            1   (RPC — non-batchexecute)
Pass rate:     100% (57/57)
```

### Subprocess test verification

Subprocess tests (`test_cli_*`) pass via both invocation modes:

- `python -m cli_web.deepwiki ...` (default development mode)
- `CLI_WEB_FORCE_INSTALLED=1 ... cli-web-deepwiki ...` (binary on PATH)

The `_resolve_cli()` helper switches between them transparently.
