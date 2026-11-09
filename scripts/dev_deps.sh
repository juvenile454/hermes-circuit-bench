# Development-only packages (never plugin dependencies). cryptography: pypdf needs it for AES-encrypted vendor
# datasheets in the citation corpus. Sourced by the local dev scripts; CI uses the same list
# (tests/test_p0_ci.py keeps .github/workflows/ci.yml in step).
# pypdf >= 6.21.4: the module evidence (excerpt lines, page text) was extracted with 6.21.4; older text layers differ.
DEV_DEPS='pytest>=8,<10 httpx>=0.27,<1 fastapi>=0.115,<1 pyyaml>=6,<7 pypdf>=6.21.4,<7 cryptography>=42,<47 ruff>=0.8,<1'
