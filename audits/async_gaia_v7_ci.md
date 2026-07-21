# Asynchronous Gaia v7 acquisition CI audit

Created: 2026-07-22

The live encrypted relay established that query v7 parses but the synchronous Gaia TAP endpoint aborts the joined and ordered pilot before completion. This audit covers the repair:

- asynchronous UWS job submission is now the command-line default;
- requested server execution duration and client wait timeout are explicit;
- remote job ID, URL and terminal phase are preserved in manifests;
- result-fetch retries and optional remote-job retention are configurable;
- remote cleanup failures cannot invalidate a locally checksummed result;
- synchronous acquisition remains available for short queries and backward compatibility;
- success, remote-error, cleanup, limit validation, and existing-output behavior are tested;
- query v7 retains the corrected `ORDER BY pk1_cubed_proxy` syntax;
- all prior HOU-COMPACT tests remain in the suite.

Passing CI validates software behavior. A fresh encrypted relay must still establish live Gaia completion and downstream DESI products.
