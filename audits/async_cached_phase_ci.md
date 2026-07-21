# Cached-phase Gaia async CI audit

Created: 2026-07-22

Encrypted relay run `29855735155` showed that the Gaia asynchronous job could finish its long-poll wait, then fail when the client made an unnecessary second 10-second status request through `job.phase`.

This audit covers the repair:

- the terminal phase returned by `wait()` is read from pyvo's cached UWS job state;
- no extra status request is issued before error checking or result retrieval;
- anonymous services are no longer asked to change execution duration by default;
- explicit execution-duration requests remain supported and audited when a service allows them;
- v7 and bounded v8 query contracts are statically tested;
- all prior HOU-COMPACT tests remain in the suite.

Passing CI validates software behavior. The next encrypted relay must confirm live Gaia result retrieval.
