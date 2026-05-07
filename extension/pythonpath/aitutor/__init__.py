"""AI Essay Tutor — LibreOffice extension client side.

Stdlib-only. LibreOffice's bundled Python is missing many third-party
packages (no requests, sometimes no ssl) and pip-installing into it is
unreliable, so this module talks to the local AI server over plain HTTP
using urllib.
"""
