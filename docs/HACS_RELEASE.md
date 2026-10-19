# Release and HACS checklist

The repository can be installed as a HACS custom integration. Inclusion in the
default catalog is an external review, not something local tests can grant.

Before a release:

1. Complete physical read/command/reload/restart tests for the six matrix models.
   Record firmware and observed results; keep feeding tests supervised.
2. Review identity migrations with a backed-up disposable HA configuration.
   Confirm existing entity IDs and recorder statistics IDs remain unchanged.
3. Run pytest with full-source coverage, Ruff, mypy, resource validation, the
   isolated HA smoke test, HACS and Hassfest. Inspect the reports, not only badges.
   mypy currently covers four dependency-independent files; the legacy modules
   and complete config flow are not fully type-checked or covered at 95%.
4. Change manifest version, prepare release notes with breaking changes and a
   rollback procedure, then tag that exact commit with matching `vX.Y.Z`.
5. The published-release workflow validates the version and attaches the ZIP.
   Do not publish a release before the tested commit has been approved.
6. Verify icon/brand requirements against the current HACS rules. Existing local
   assets do not prove acceptance into Home Assistant brands.
7. Set descriptive GitHub topics (home-assistant, hacs, philips, homeid, tuya,
   air-purifier) and submit the repository through the current HACS default-list
   contribution process. Record the resulting submission/review URL.

No default-catalog acceptance or submission is claimed by this document.
