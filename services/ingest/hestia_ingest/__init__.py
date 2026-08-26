"""Hestia ingestion.

The adapter seam for the address-to-dossier pipeline. The discipline that
makes it testable: every provider is split into a pure ``build_request`` and a
pure ``map_response``, with one thin ``fetch`` shim between them. The mappers
are tested against RESPONSES RECORDED FROM THE LIVE PROVIDERS (see
``fixtures/``), so the tests exercise reality, not guesses about it — and CI
never touches the network.

Raw payloads are retained in ``ingestion_runs``: a mapping bug is fixed by
re-mapping stored payloads, never by re-fetching what a provider may no longer
serve.
"""

__all__ = ["fetch", "inference", "providers"]
